"""Reference asynchronous question lifecycle, independent of queue transport."""

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from threading import RLock
from typing import Literal, Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from phineas.analysis import analyze_transactions
from phineas.narratives import NarrativeProvider
from phineas.questions import QuestionIntent, QuestionResponse, answer_intent, classify_question
from phineas.sessions import SessionStore, SessionUnavailable, utc_now

MAX_ATTEMPTS = 3
LEASE = timedelta(seconds=150)
MAX_PENDING_AGE = timedelta(minutes=25)
MAX_JOBS_PER_SESSION = 10


class JobUnavailable(ValueError):
    def __init__(self) -> None:
        super().__init__("job_unavailable")


class JobConflict(ValueError):
    """Idempotency key reused for a different intent."""


class JobLimitExceeded(ValueError):
    def __init__(self) -> None:
        super().__init__("question_job_limit_reached")


class QueueUnavailable(Exception):
    """Enqueue failed or its outcome was ambiguous; safe to retry the request."""


class WorkerRetry(Exception):
    """Delivery must remain unacknowledged for later retry."""


class JobMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    session_id: str = Field(repr=False)
    job_id: UUID
    intent: QuestionIntent


class SubmitQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    question: str = Field(min_length=1, max_length=200, repr=False)


@dataclass(frozen=True)
class Job:
    session_id: str = field(repr=False)
    job_id: UUID
    intent: QuestionIntent
    created_at: datetime
    expires_at: datetime
    state: Literal["pending", "running", "succeeded", "failed"] = "pending"
    attempts: int = 0
    lease_token: str | None = field(default=None, repr=False)
    lease_expires_at: datetime | None = None
    result: QuestionResponse | None = field(default=None, repr=False)
    error_code: str | None = None


class JobView(BaseModel):
    job_id: UUID
    state: Literal["pending", "running", "succeeded", "failed"]
    attempts: int
    result: QuestionResponse | None = None
    error_code: str | None = None


class JobQueue(Protocol):
    def enqueue(self, message: JobMessage) -> None: ...


class JobStore(Protocol):
    def create(self, session_id: str, request_id: UUID, intent: QuestionIntent) -> Job: ...
    def get(self, session_id: str, job_id: UUID) -> Job: ...
    def claim(self, session_id: str, job_id: UUID) -> Job | None: ...
    def finish(self, claim: Job, result: QuestionResponse | None) -> bool: ...
    def purge(self, session_id: str) -> None: ...


class InMemoryJobStore:
    """Local reference only; distributed implementations need atomic conditions.

    Jobs contain no user question text. Session authorization is checked on every
    operation; the service coordinates explicit purge of both local stores.
    """

    MAX_ATTEMPTS = MAX_ATTEMPTS
    LEASE = LEASE
    MAX_PENDING_AGE = MAX_PENDING_AGE

    def __init__(self, sessions: SessionStore, clock: Callable[[], datetime] = utc_now) -> None:
        self._sessions = sessions
        self._clock = clock
        self._jobs: dict[tuple[str, UUID], Job] = {}
        self._lock = RLock()

    def _sweep(self) -> None:
        for key, job in tuple(self._jobs.items()):
            try:
                self._sessions.peek(job.session_id)
            except SessionUnavailable:
                del self._jobs[key]
                continue
            if (job.state in ("pending", "running")
                    and self._clock() >= job.created_at + self.MAX_PENDING_AGE):
                self._jobs[key] = replace(job, state="failed", lease_token=None,
                    lease_expires_at=None, error_code="job_deadline_exceeded")

    def create(self, session_id: str, request_id: UUID, intent: QuestionIntent) -> Job:
        with self._lock:
            self._sweep()
            session = self._sessions.peek(session_id)
            key = (session_id, request_id)
            existing = self._jobs.get(key)
            if existing is not None:
                if existing.intent is not intent:
                    raise JobConflict()
                return existing
            if sum(sid == session_id for sid, _ in self._jobs) >= MAX_JOBS_PER_SESSION:
                raise JobLimitExceeded()
            job = Job(session_id, request_id, intent, self._clock(), session.absolute_expires_at)
            self._jobs[key] = job
            return job

    def get(self, session_id: str, job_id: UUID) -> Job:
        with self._lock:
            self._sweep()
            self._sessions.peek(session_id)
            job = self._jobs.get((session_id, job_id))
            if job is None:
                raise JobUnavailable()
            return job

    def claim(self, session_id: str, job_id: UUID) -> Job | None:
        with self._lock:
            job = self.get(session_id, job_id)
            now = self._clock()
            if job.state in ("succeeded", "failed"):
                return None
            if job.state == "running" and job.lease_expires_at is not None and now < job.lease_expires_at:
                raise WorkerRetry()
            if job.attempts >= self.MAX_ATTEMPTS:
                self._jobs[(session_id, job_id)] = replace(job, state="failed",
                    error_code="attempts_exhausted", lease_token=None, lease_expires_at=None)
                return None
            claimed = replace(job, state="running", attempts=job.attempts + 1,
                lease_token=uuid4().hex, lease_expires_at=now + self.LEASE)
            self._jobs[(session_id, job_id)] = claimed
            return claimed

    def finish(self, claim: Job, result: QuestionResponse | None) -> bool:
        with self._lock:
            job = self.get(claim.session_id, claim.job_id)
            if (job.state != "running" or job.lease_token != claim.lease_token
                    or job.lease_expires_at is None or self._clock() >= job.lease_expires_at):
                return False
            state = "succeeded" if result is not None else (
                "failed" if job.attempts >= self.MAX_ATTEMPTS else "pending")
            self._jobs[(job.session_id, job.job_id)] = replace(job, state=state,
                result=result, lease_token=None, lease_expires_at=None,
                error_code="generation_unavailable" if state == "failed" else None)
            return True

    def purge(self, session_id: str) -> None:
        with self._lock:
            for key in tuple(self._jobs):
                if key[0] == session_id:
                    del self._jobs[key]


class QuestionJobService:
    def __init__(self, sessions: SessionStore, jobs: JobStore, queue: JobQueue) -> None:
        self._sessions, self._jobs, self._queue = sessions, jobs, queue

    def submit(self, session_id: str, request: SubmitQuestion) -> JobView:
        intent = classify_question(request.question)
        job = self._jobs.create(session_id, request.request_id, intent)
        self._sessions.access(session_id)
        if job.state == "pending":
            # Re-enqueue on a repeated request: this recovers an ambiguous send
            # without requiring a distributed transaction with the queue.
            self._queue.enqueue(JobMessage(session_id=session_id, job_id=job.job_id, intent=intent))
        return self.view(job)

    def poll(self, session_id: str, job_id: UUID) -> JobView:
        job = self._jobs.get(session_id, job_id)
        self._sessions.access(session_id)
        return self.view(job)

    def purge(self, session_id: str) -> None:
        self._sessions.purge(session_id)
        self._jobs.purge(session_id)

    @staticmethod
    def view(job: Job) -> JobView:
        return JobView(job_id=job.job_id, state=job.state, attempts=job.attempts,
            result=job.result, error_code=job.error_code)


class QuestionWorker:
    def __init__(self, sessions: SessionStore, jobs: JobStore, provider: NarrativeProvider) -> None:
        self._sessions, self._jobs, self._provider = sessions, jobs, provider

    def process(self, message: JobMessage) -> None:
        try:
            current = self._jobs.get(message.session_id, message.job_id)
            if current.intent is not message.intent:
                raise JobUnavailable()
            claim = self._jobs.claim(message.session_id, message.job_id)
            if claim is None:
                return
            session = self._sessions.peek(message.session_id)
            answer = answer_intent(analyze_transactions(session.transactions), claim.intent, self._provider)
            self._sessions.peek(message.session_id)
            if answer.narrative.narrative_status == "unavailable":
                if not self._jobs.finish(claim, None):
                    raise WorkerRetry()
                if claim.attempts < MAX_ATTEMPTS:
                    raise WorkerRetry()
                return
            if not self._jobs.finish(claim, answer):
                raise WorkerRetry()
        except (SessionUnavailable, JobUnavailable):
            # Invalidated work is acknowledged without calling the model again.
            return
