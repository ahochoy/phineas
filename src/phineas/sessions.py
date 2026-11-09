"""Local session lifecycle. Store operations are atomic within one process."""

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from secrets import token_urlsafe
from threading import RLock
from typing import Protocol

from phineas.application import IngestionSummary, summarize_transactions
from phineas.domain.transactions import SanitizedTransaction
from phineas.samples import ingest_sample
from phineas.analysis import AnalysisResult, analyze_transactions


class SessionUnavailable(ValueError):
    def __init__(self) -> None:
        super().__init__("session_unavailable")


@dataclass(frozen=True)
class SessionRecord:
    session_id: str = field(repr=False)
    created_at: datetime
    last_activity_at: datetime
    idle_expires_at: datetime
    absolute_expires_at: datetime
    sample_id: str
    transactions: tuple[SanitizedTransaction, ...] = field(repr=False)


class SessionStore(Protocol):
    def create(self, sample_id: str, transactions: tuple[SanitizedTransaction, ...]) -> SessionRecord: ...
    def access(self, session_id: str) -> SessionRecord: ...
    def purge(self, session_id: str) -> None: ...


def utc_now() -> datetime:
    return datetime.now(UTC)


class InMemorySessionStore:
    """Ephemeral single-process store; expired records are swept on operations."""

    def __init__(self, clock: Callable[[], datetime] = utc_now) -> None:
        self._clock = clock
        self._records: dict[str, SessionRecord] = {}
        self._lock = RLock()

    def _sweep(self, now: datetime) -> None:
        for key in list(self._records):
            record = self._records[key]
            if now >= min(record.idle_expires_at, record.absolute_expires_at):
                del self._records[key]

    def create(self, sample_id: str, transactions: tuple[SanitizedTransaction, ...]) -> SessionRecord:
        with self._lock:
            now = self._clock()
            self._sweep(now)
            record = SessionRecord(
                session_id=token_urlsafe(32), created_at=now,
                last_activity_at=now, idle_expires_at=now + timedelta(minutes=30),
                absolute_expires_at=now + timedelta(hours=4),
                sample_id=sample_id, transactions=transactions,
            )
            self._records[record.session_id] = record
            return record

    def access(self, session_id: str) -> SessionRecord:
        with self._lock:
            now = self._clock()
            self._sweep(now)
            record = self._records.get(session_id)
            if record is None:
                raise SessionUnavailable()
            record = replace(record, last_activity_at=now,
                idle_expires_at=min(now + timedelta(minutes=30), record.absolute_expires_at))
            self._records[session_id] = record
            return record

    def purge(self, session_id: str) -> None:
        with self._lock:
            self._sweep(self._clock())
            if self._records.pop(session_id, None) is None:
                raise SessionUnavailable()


class SessionService:
    def __init__(self, store: SessionStore) -> None:
        self._store = store

    def create(self, sample_id: str) -> SessionRecord:
        return self._store.create(sample_id, ingest_sample(sample_id))

    def summary(self, session_id: str) -> IngestionSummary:
        return summarize_transactions(self._store.access(session_id).transactions)

    def purge(self, session_id: str) -> None:
        self._store.purge(session_id)

    def analysis(self, session_id: str) -> AnalysisResult:
        return analyze_transactions(self._store.access(session_id).transactions)
