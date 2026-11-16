"""Durable jobs sharing the sanitized session partition and purge boundary."""

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from uuid import UUID, uuid4

from botocore.exceptions import BotoCoreError, ClientError
from pydantic import TypeAdapter, ValidationError

from phineas.admission import (
    DAILY_JOB_LIMIT, AdmissionControl, DailyCounter, DailyJobLimitExceeded,
    DemoAdmissionsPaused, control_key, counter_expires_at, daily_counter_key,
)
from phineas.dynamodb_sessions import DynamoDBSessionStore
from phineas.jobs import (
    LEASE, MAX_ATTEMPTS, MAX_JOBS_PER_SESSION, MAX_PENDING_AGE,
    Job, JobConflict, JobLimitExceeded, JobUnavailable, WorkerRetry,
)
from phineas.questions import QuestionIntent, QuestionResponse
from phineas.sessions import SessionStoreError, SessionUnavailable, utc_now


class DynamoDBJobStore:
    """Optimistic job revisions plus a transactional session validity check.

    No question text is persisted. Session idle time is never extended here.
    """

    MAX_ATTEMPTS = MAX_ATTEMPTS
    LEASE = LEASE
    MAX_PENDING_AGE = MAX_PENDING_AGE
    _codec = TypeAdapter(Job)

    def __init__(self, sessions: DynamoDBSessionStore, *,
                 clock: Callable[[], datetime] = utc_now) -> None:
        self._sessions = sessions
        self._clock = clock

    @staticmethod
    def _key(session_id: str, job_id: UUID) -> dict[str, str]:
        return {"pk": f"SESSION#{session_id}", "sk": f"JOB#{job_id}"}

    def _read(self, session_id: str, job_id: UUID) -> tuple[Job, int]:
        try:
            self._sessions._metadata(session_id)
            item = self._sessions._table().get_item(
                Key=self._key(session_id, job_id), ConsistentRead=True).get("Item")
            if item is None:
                raise JobUnavailable()
            job = self._codec.validate_json(item["payload"])
            if job.session_id != session_id or job.job_id != job_id:
                raise SessionStoreError()
            self._sessions._metadata(session_id)
            return job, int(item["revision"])
        except (SessionUnavailable, JobUnavailable):
            raise
        except (BotoCoreError, ClientError, ValidationError, KeyError, ValueError):
            raise SessionStoreError() from None

    def _write(self, job: Job, revision: int | None) -> bool:
        """False means a competing writer won; all other failures fail closed."""
        try:
            now = self._clock().isoformat()
            item = {**self._key(job.session_id, job.job_id),
                "revision": 0 if revision is None else revision + 1,
                "expires_at": int(job.expires_at.timestamp()),
                "payload": self._codec.dump_json(job).decode()}
            if len(str(item).encode()) > 350000:
                raise SessionStoreError()
            put: dict = {"TableName": self._sessions._name, "Item": item,
                "ConditionExpression": "attribute_not_exists(pk)" if revision is None else "revision = :revision"}
            if revision is not None:
                put["ExpressionAttributeValues"] = {":revision": revision}
            client = self._sessions._table().meta.client
            admission_actions: list[dict] = []
            validity = "attribute_exists(pk) AND attribute_not_exists(purging) AND idle_expires_at > :now AND absolute_expires_at > :now"
            session_action = {"ConditionCheck": {"TableName": self._sessions._name,
                "Key": self._sessions._key(job.session_id),
                "ConditionExpression": validity,
                "ExpressionAttributeValues": {":now": now}}}
            if revision is None:
                # A new job and its lifetime slot are committed together.
                # Never default a missing counter to zero: legacy jobs might
                # already exist and must not silently bypass the new limit.
                session_action = {"Update": {"TableName": self._sessions._name,
                    "Key": self._sessions._key(job.session_id),
                    "UpdateExpression": "ADD question_job_count :one",
                    "ConditionExpression": validity + " AND question_job_count >= :zero AND question_job_count < :limit",
                    "ExpressionAttributeValues": {":now": now, ":one": 1,
                        ":zero": 0, ":limit": MAX_JOBS_PER_SESSION}}}
                admission_actions = [
                    {"ConditionCheck": {"TableName": self._sessions._name,
                        "Key": control_key(),
                        "ConditionExpression": "schema_version = :version AND #enabled = :yes",
                        "ExpressionAttributeNames": {"#enabled": "enabled"},
                        "ExpressionAttributeValues": {":version": "1", ":yes": True}}},
                    {"Update": {"TableName": self._sessions._name,
                        "Key": daily_counter_key(job.created_at),
                        "UpdateExpression": "SET admitted_jobs = if_not_exists(admitted_jobs, :zero) + :one, expires_at = if_not_exists(expires_at, :ttl)",
                        "ConditionExpression": "attribute_not_exists(pk) OR (admitted_jobs >= :zero AND admitted_jobs < :limit AND expires_at = :ttl)",
                        "ExpressionAttributeValues": {":zero": 0, ":one": 1,
                            ":ttl": counter_expires_at(job.created_at), ":limit": DAILY_JOB_LIMIT}}},
                ]
            try:
                client.transact_write_items(TransactItems=[
                    *admission_actions, session_action, {"Put": put}])
                return True
            except client.exceptions.TransactionCanceledException as error:
                self._sessions._metadata(job.session_id)
                reasons = error.response.get("CancellationReasons", [])
                if any(reason.get("Code") == "ConditionalCheckFailed" for reason in reasons):
                    return False
                raise SessionStoreError() from None
        except SessionUnavailable:
            raise
        except (BotoCoreError, ClientError):
            raise SessionStoreError() from None

    def _raise_admission_rejection(self, instant: datetime) -> None:
        """Classify a failed admission without converting outages into quota resets."""
        table = self._sessions._table()
        item = table.get_item(Key=control_key(), ConsistentRead=True).get("Item")
        control = AdmissionControl.model_validate(item)
        if not control.enabled:
            raise DemoAdmissionsPaused()
        item = table.get_item(Key=daily_counter_key(instant), ConsistentRead=True).get("Item")
        if item is not None:
            counter = DailyCounter.model_validate(item)
            if counter.expires_at != counter_expires_at(instant):
                raise SessionStoreError()
            if counter.admitted_jobs >= DAILY_JOB_LIMIT:
                raise DailyJobLimitExceeded()

    def create(self, session_id: str, request_id: UUID, intent: QuestionIntent) -> Job:
        try:
            try:
                existing = self.get(session_id, request_id)
            except JobUnavailable:
                existing = None
            if existing is not None:
                if existing.intent is not intent:
                    raise JobConflict()
                return existing
            metadata = self._sessions._metadata(session_id)
            if "question_job_count" not in metadata:
                raise SessionStoreError()
            job = Job(session_id, request_id, intent, self._clock(),
                datetime.fromisoformat(metadata["absolute_expires_at"]))
            if self._write(job, None):
                return job
            try:
                existing = self.get(session_id, request_id)
            except JobUnavailable:
                metadata = self._sessions._metadata(session_id)
                if metadata.get("question_job_count", 0) >= MAX_JOBS_PER_SESSION:
                    raise JobLimitExceeded() from None
                self._raise_admission_rejection(job.created_at)
                raise WorkerRetry() from None
            if existing.intent is not intent:
                raise JobConflict()
            return existing
        except SessionUnavailable:
            raise
        except (BotoCoreError, ClientError, KeyError, ValidationError):
            raise SessionStoreError() from None

    def _current(self, session_id: str, job_id: UUID) -> tuple[Job, int]:
        for _ in range(4):
            job, revision = self._read(session_id, job_id)
            if (job.state not in ("pending", "running")
                    or self._clock() < job.created_at + self.MAX_PENDING_AGE):
                return job, revision
            failed = replace(job, state="failed", lease_token=None,
                lease_expires_at=None, error_code="job_deadline_exceeded")
            if self._write(failed, revision):
                return failed, revision + 1
        raise WorkerRetry()

    def get(self, session_id: str, job_id: UUID) -> Job:
        return self._current(session_id, job_id)[0]

    def claim(self, session_id: str, job_id: UUID) -> Job | None:
        for _ in range(4):
            job, revision = self._current(session_id, job_id)
            now = self._clock()
            if job.state in ("succeeded", "failed"):
                return None
            if job.state == "running" and job.lease_expires_at is not None and now < job.lease_expires_at:
                raise WorkerRetry()
            if job.attempts >= self.MAX_ATTEMPTS:
                failed = replace(job, state="failed", error_code="attempts_exhausted",
                    lease_token=None, lease_expires_at=None)
                if self._write(failed, revision):
                    return None
                continue
            claimed = replace(job, state="running", attempts=job.attempts + 1,
                lease_token=uuid4().hex, lease_expires_at=now + self.LEASE)
            if self._write(claimed, revision):
                return claimed
        raise WorkerRetry()

    def finish(self, claim: Job, result: QuestionResponse | None) -> bool:
        job, revision = self._current(claim.session_id, claim.job_id)
        if (job.state != "running" or job.lease_token != claim.lease_token
                or job.lease_expires_at is None or self._clock() >= job.lease_expires_at):
            return False
        state = "succeeded" if result is not None else (
            "failed" if job.attempts >= self.MAX_ATTEMPTS else "pending")
        finished = replace(job, state=state, result=result, lease_token=None,
            lease_expires_at=None, error_code="generation_unavailable" if state == "failed" else None)
        return self._write(finished, revision)

    def purge(self, session_id: str) -> None:
        # DynamoDBSessionStore owns partition-wide deletion, including JOB# rows.
        pass
