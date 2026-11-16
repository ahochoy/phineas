from datetime import UTC, datetime, timedelta
from unittest.mock import Mock, patch
from typing import Any
from uuid import uuid4

import boto3
import pytest
from fastapi.testclient import TestClient
from moto import mock_aws

from phineas.api import create_configured_app
from phineas.dynamodb_jobs import DynamoDBJobStore
from phineas.dynamodb_sessions import DynamoDBSessionStore
from phineas.jobs import JobConflict, JobMessage, JobUnavailable, QuestionJobService, QuestionWorker, SubmitQuestion, WorkerRetry
from phineas.narratives import NarrativeUnavailable
from phineas.questions import QuestionIntent
from phineas.samples import ingest_sample
from phineas.sessions import SessionStoreError, SessionUnavailable


@pytest.fixture
def setup(monkeypatch):
    for key in ("AWS_PROFILE", "AWS_DEFAULT_PROFILE"):
        monkeypatch.delenv(key, raising=False)
    for key in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
        monkeypatch.setenv(key, "testing")
    with mock_aws():
        resource: Any = boto3.resource("dynamodb", region_name="us-east-2")
        table = resource.create_table(TableName="jobs", BillingMode="PAY_PER_REQUEST",
            KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}, {"AttributeName": "sk", "KeyType": "RANGE"}],
            AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}, {"AttributeName": "sk", "AttributeType": "S"}])
        clock = [datetime(2026, 1, 1, tzinfo=UTC)]
        sessions = DynamoDBSessionStore("jobs", clock=lambda: clock[0])
        session = sessions.create("analysis-demo", ingest_sample("analysis-demo"))
        jobs = DynamoDBJobStore(sessions, clock=lambda: clock[0])
        provider = Mock()
        provider.select.return_value = '{"fact_ids":["fee"]}'
        queue = Mock()
        service = QuestionJobService(sessions, jobs, queue)
        yield clock, sessions, session.session_id, jobs, provider, queue, service, table


def test_durable_result_duplicate_delivery_and_privacy(setup):
    clock, sessions, sid, jobs, provider, queue, service, table = setup
    request = SubmitQuestion(request_id=uuid4(), question="Explain fees")
    view = service.submit(sid, request)
    # A separate resource/store instance, as in another Lambda process.
    other_sessions = DynamoDBSessionStore("jobs", clock=lambda: clock[0])
    other_jobs = DynamoDBJobStore(other_sessions, clock=lambda: clock[0])
    worker = QuestionWorker(other_sessions, other_jobs, provider)
    message = queue.enqueue.call_args.args[0]
    idle = sessions.peek(sid).idle_expires_at
    clock[0] += timedelta(minutes=5)
    worker.process(message)
    worker.process(message)
    assert provider.select.call_count == 1
    assert sessions.peek(sid).idle_expires_at == idle
    done = jobs.get(sid, view.job_id)
    assert done.state == "succeeded"
    assert done.result is not None
    assert done.result.facts[0].fact_id == "fee"
    assert service.submit(sid, request).job_id == view.job_id
    with pytest.raises(JobConflict):
        service.submit(sid, SubmitQuestion(request_id=request.request_id, question="Show subscriptions"))
    row = next(item for item in table.scan()["Items"] if item["sk"].startswith("JOB#"))
    assert row["expires_at"] == int(done.expires_at.timestamp())
    assert "Explain fees" not in str(row)
    assert "original_description" not in str(row)
    service.purge(sid)
    assert table.scan()["Items"] == []


def test_claim_fences_old_worker_and_revision(setup):
    clock, _, sid, jobs, _, _, _, _ = setup
    job = jobs.create(sid, uuid4(), QuestionIntent.FEES)
    first = jobs.claim(sid, job.job_id)
    assert first is not None
    with pytest.raises(WorkerRetry):
        jobs.claim(sid, job.job_id)
    clock[0] += timedelta(seconds=150)
    second = jobs.claim(sid, job.job_id)
    assert second is not None
    assert second.lease_token != first.lease_token
    assert jobs.finish(first, None) is False
    assert jobs._write(first, 0) is False
    assert jobs.get(sid, job.job_id).lease_token == second.lease_token


def test_failures_and_crashes_are_bounded(setup):
    clock, sessions, sid, jobs, provider, queue, service, _ = setup
    view = service.submit(sid, SubmitQuestion(request_id=uuid4(), question="Explain fees"))
    worker = QuestionWorker(sessions, jobs, provider)
    provider.select.side_effect = NarrativeUnavailable()
    message = queue.enqueue.call_args.args[0]
    for _ in range(2):
        with pytest.raises(WorkerRetry):
            worker.process(message)
    worker.process(message)
    assert jobs.get(sid, view.job_id).error_code == "generation_unavailable"
    crashed = jobs.create(sid, uuid4(), QuestionIntent.FEES)
    for _ in range(3):
        assert jobs.claim(sid, crashed.job_id) is not None
        clock[0] += timedelta(seconds=150)
    assert jobs.claim(sid, crashed.job_id) is None
    assert jobs.get(sid, crashed.job_id).error_code == "attempts_exhausted"


def test_expiration_deadline_and_cross_session_isolation(setup):
    clock, sessions, sid, jobs, _, _, _, _ = setup
    job = jobs.create(sid, uuid4(), QuestionIntent.FEES)
    other = sessions.create("empty", ())
    with pytest.raises(JobUnavailable):
        jobs.get(other.session_id, job.job_id)
    clock[0] += timedelta(minutes=25)
    assert jobs.get(sid, job.job_id).error_code == "job_deadline_exceeded"
    clock[0] += timedelta(minutes=5)
    with pytest.raises(SessionUnavailable):
        jobs.get(sid, job.job_id)


def test_session_invalidated_between_read_and_write(setup):
    _, sessions, sid, jobs, _, _, _, table = setup
    job = jobs.create(sid, uuid4(), QuestionIntent.FEES)
    claim = jobs.claim(sid, job.job_id)
    assert claim is not None
    table.update_item(Key=sessions._key(sid), UpdateExpression="SET purging = :yes",
        ExpressionAttributeValues={":yes": True})
    # Direct transaction bypasses preliminary read: session check still fences it.
    with pytest.raises(SessionUnavailable):
        jobs._write(claim, 1)
    with pytest.raises(SessionUnavailable):
        sessions.access(sid)


def test_purge_during_inference_discards_result(setup):
    _, sessions, sid, jobs, provider, queue, service, table = setup
    service.submit(sid, SubmitQuestion(request_id=uuid4(), question="Explain fees"))
    def purge_then_reply(facts):
        service.purge(sid)
        return '{"fact_ids":["fee"]}'
    provider.select.side_effect = purge_then_reply
    QuestionWorker(sessions, jobs, provider).process(queue.enqueue.call_args.args[0])
    assert table.scan()["Items"] == []


def test_large_partition_purge_is_retryable_after_cleanup_failure(setup):
    _, sessions, sid, _, _, _, _, table = setup
    for i in range(105):
        table.put_item(Item={"pk": f"SESSION#{sid}", "sk": f"JOB#{i}", "payload": "synthetic"})
    with patch.object(sessions._table(), "batch_writer", side_effect=SessionStoreError()):
        with pytest.raises(SessionStoreError):
            sessions.purge(sid)
    with pytest.raises(SessionUnavailable):
        sessions.peek(sid)
    sessions.purge(sid)
    assert table.scan()["Items"] == []


def test_configured_http_submission_reaches_sqs_and_durable_worker(setup, monkeypatch):
    _, _, _, _, provider, _, _, _ = setup
    sqs = boto3.client("sqs", region_name="us-east-2")
    url = sqs.create_queue(QueueName="question-jobs")["QueueUrl"]
    monkeypatch.setenv("PHINEAS_SESSIONS_TABLE", "jobs")
    monkeypatch.setenv("PHINEAS_QUESTION_QUEUE_URL", url)
    monkeypatch.delenv("PHINEAS_HARNESS_ARN", raising=False)
    monkeypatch.setenv("AWS_REGION", "us-east-2")
    with TestClient(create_configured_app()) as client:
        sid = client.post("/sessions", json={"sample_id": "analysis-demo"}).json()["session_id"]
        submitted = client.post(f"/sessions/{sid}/question-jobs", json={
            "request_id": str(uuid4()), "question": "Explain fees"})
        assert submitted.status_code == 202
        job_id = submitted.json()["job_id"]
        delivery = sqs.receive_message(QueueUrl=url)["Messages"][0]
        message = JobMessage.model_validate_json(delivery["Body"])
        assert message.session_id == sid
        assert "Explain fees" not in delivery["Body"]
        sessions = DynamoDBSessionStore("jobs")
        QuestionWorker(sessions, DynamoDBJobStore(sessions), provider).process(message)
        result = client.get(f"/sessions/{sid}/jobs/{job_id}")
        assert result.json()["state"] == "succeeded"
        assert result.json()["result"]["facts"][0]["fact_id"] == "fee"
        assert client.delete(f"/sessions/{sid}").status_code == 204
        assert client.get(f"/sessions/{sid}/jobs/{job_id}").json() == {"detail": "session_unavailable"}
