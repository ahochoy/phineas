"""Durable jobs sharing the sanitized session partition and purge boundary."""

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from uuid import UUID, uuid4

from botocore.exceptions import BotoCoreError, ClientError
from pydantic import TypeAdapter, ValidationError

from phineas.dynamodb_sessions import DynamoDBSessionStore
from phineas.jobs import LEASE, MAX_ATTEMPTS, MAX_PENDING_AGE, Job, JobConflict, JobUnavailable, WorkerRetry
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
            try:
                client.transact_write_items(TransactItems=[
                    {"ConditionCheck": {"TableName": self._sessions._name,
                        "Key": self._sessions._key(job.session_id),
                        "ConditionExpression": "attribute_exists(pk) AND attribute_not_exists(purging) AND idle_expires_at > :now AND absolute_expires_at > :now",
                        "ExpressionAttributeValues": {":now": now}}},
                    {"Put": put}])
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

    def create(self, session_id: str, request_id: UUID, intent: QuestionIntent) -> Job:
        try:
            metadata = self._sessions._metadata(session_id)
            job = Job(session_id, request_id, intent, self._clock(),
                datetime.fromisoformat(metadata["absolute_expires_at"]))
            if self._write(job, None):
                return job
            existing = self.get(session_id, request_id)
            if existing.intent is not intent:
                raise JobConflict()
            return existing
        except SessionUnavailable:
            raise
        except (BotoCoreError, ClientError, KeyError):
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
