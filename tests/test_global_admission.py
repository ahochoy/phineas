from datetime import UTC, datetime, timedelta, timezone
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from phineas.admission import (
    DAILY_JOB_LIMIT, DailyJobLimitExceeded, DemoAdmissionsPaused,
    counter_expires_at, daily_counter_key, utc_day,
)
from phineas.api import create_app
from phineas.jobs import InMemoryJobStore, QuestionJobService, SubmitQuestion
from phineas.questions import QuestionIntent
from phineas.sessions import InMemorySessionStore


def test_local_daily_budget_survives_purge_and_new_sessions():
    sessions = InMemorySessionStore()
    jobs = InMemoryJobStore(sessions)
    service = QuestionJobService(sessions, jobs, Mock())
    for _ in range(DAILY_JOB_LIMIT):
        sid = sessions.create("empty", ()).session_id
        jobs.create(sid, uuid4(), QuestionIntent.UNSUPPORTED)
        service.purge(sid)
    sid = sessions.create("empty", ()).session_id
    with pytest.raises(DailyJobLimitExceeded):
        jobs.create(sid, uuid4(), QuestionIntent.FEES)


def test_local_pause_preserves_replay_and_resuming_does_not_reset_count():
    sessions = InMemorySessionStore()
    jobs = InMemoryJobStore(sessions)
    sid = sessions.create("empty", ()).session_id
    first = jobs.create(sid, uuid4(), QuestionIntent.UNSUPPORTED)
    jobs.set_admissions_enabled(False)
    assert jobs.create(sid, first.job_id, first.intent).job_id == first.job_id
    with pytest.raises(DemoAdmissionsPaused):
        jobs.create(sid, uuid4(), QuestionIntent.FEES)
    jobs.set_admissions_enabled(True)
    jobs.create(sid, uuid4(), QuestionIntent.FEES)
    assert sum(jobs._daily_counts.values()) == 2


def test_local_rollover_counts_new_jobs_not_replays():
    now = [datetime(2026, 1, 1, 23, 59, tzinfo=UTC)]
    sessions = InMemorySessionStore(lambda: now[0])
    jobs = InMemoryJobStore(sessions, lambda: now[0])
    admitted = []
    for _ in range(DAILY_JOB_LIMIT):
        sid = sessions.create("empty", ()).session_id
        admitted.append(jobs.create(sid, uuid4(), QuestionIntent.UNSUPPORTED))
    first = admitted[-1]
    now[0] += timedelta(minutes=2)
    jobs.create(first.session_id, first.job_id, first.intent)
    jobs.create(first.session_id, uuid4(), QuestionIntent.UNSUPPORTED)
    assert jobs._daily_counts == {"2026-01-01": 25, "2026-01-02": 1}


def test_global_http_rejection_codes_no_store_and_no_enqueue():
    sessions = InMemorySessionStore()
    jobs = InMemoryJobStore(sessions)
    queue = Mock()
    service = QuestionJobService(sessions, jobs, queue)
    for _ in range(DAILY_JOB_LIMIT):
        sid = sessions.create("empty", ()).session_id
        jobs.create(sid, uuid4(), QuestionIntent.UNSUPPORTED)
    sid = sessions.create("empty", ()).session_id
    with TestClient(create_app(sessions, job_service=service)) as client:
        def submit():
            return client.post(f"/sessions/{sid}/question-jobs", json={
                "request_id": str(uuid4()), "question": "Tell me a joke"})
        rejected = submit()
        assert rejected.status_code == 429
        assert rejected.json() == {"detail": "demo_daily_job_limit_reached"}
        jobs.set_admissions_enabled(False)
        paused = submit()
        assert paused.status_code == 503
        assert paused.json() == {"detail": "demo_admissions_paused"}
        assert rejected.headers["cache-control"] == paused.headers["cache-control"] == "no-store"
        assert client.get(f"/sessions/{sid}/analysis").status_code == 200
        assert client.delete(f"/sessions/{sid}").status_code == 204
    queue.enqueue.assert_not_called()


def test_ambiguous_send_reserves_once_and_retry_reuses_slot():
    from phineas.jobs import QueueUnavailable
    sessions = InMemorySessionStore()
    jobs = InMemoryJobStore(sessions)
    queue = Mock()
    service = QuestionJobService(sessions, jobs, queue)
    sid = sessions.create("empty", ()).session_id
    request = SubmitQuestion(request_id=uuid4(), question="Tell me a joke")
    queue.enqueue.side_effect = QueueUnavailable()
    with pytest.raises(QueueUnavailable):
        service.submit(sid, request)
    queue.enqueue.side_effect = None
    jobs.set_admissions_enabled(False)
    service.submit(sid, request)
    assert sum(jobs._daily_counts.values()) == 1


def test_counter_dates_are_utc_and_expiry_cannot_refill_current_day():
    instant = datetime(2026, 1, 1, 17, tzinfo=timezone(timedelta(hours=-8)))
    assert utc_day(instant) == "2026-01-02"
    assert daily_counter_key(instant) == {"pk": "ADMISSION#2026-01-02", "sk": "COUNTER"}
    assert counter_expires_at(instant) == int(datetime(2026, 1, 4, tzinfo=UTC).timestamp())
    with pytest.raises(ValueError, match="admission_clock_requires_timezone"):
        utc_day(datetime(2026, 1, 1))
