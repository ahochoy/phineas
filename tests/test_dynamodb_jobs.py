from datetime import UTC, datetime, timedelta
from unittest.mock import Mock, patch
from typing import Any
from uuid import uuid4

import boto3
import pytest
from fastapi.testclient import TestClient
from moto import mock_aws

from phineas.api import create_configured_app
from phineas.admission import (
    DAILY_JOB_LIMIT, DailyJobLimitExceeded, DemoAdmissionsPaused,
    control_key, counter_expires_at, daily_counter_key,
)
from phineas.dynamodb_jobs import DynamoDBJobStore
from phineas.dynamodb_sessions import DynamoDBSessionStore
from phineas.jobs import MAX_JOBS_PER_SESSION, JobConflict, JobLimitExceeded, JobMessage, JobUnavailable, QuestionJobService, QuestionWorker, SubmitQuestion, WorkerRetry
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
        table.put_item(Item={**control_key(), "schema_version": "1", "enabled": True})
        clock = [datetime(2026, 1, 1, tzinfo=UTC)]
        sessions = DynamoDBSessionStore("jobs", clock=lambda: clock[0])
        session = sessions.create("analysis-demo", ingest_sample("analysis-demo"))
        jobs = DynamoDBJobStore(sessions, clock=lambda: clock[0])
        provider = Mock()
        provider.select.return_value = '{"fact_ids":["fee"]}'
        queue = Mock()
        service = QuestionJobService(sessions, jobs, queue)
        yield clock, sessions, session.session_id, jobs, provider, queue, service, table


def session_rows(table):
    # Operational control/counter records intentionally survive session purge.
    return [row for row in table.scan()["Items"] if row["pk"].startswith("SESSION#")]


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
    assert session_rows(table) == []


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
    assert session_rows(table) == []


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
    assert session_rows(table) == []


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


def test_durable_admission_limit_replays_and_failure_do_not_refund(setup):
    clock, sessions, sid, jobs, _, _, _, table = setup
    ids = [uuid4() for _ in range(MAX_JOBS_PER_SESSION)]
    for job_id in ids:
        jobs.create(sid, job_id, QuestionIntent.FEES)
    other = DynamoDBJobStore(sessions, clock=lambda: clock[0])
    assert other.create(sid, ids[0], QuestionIntent.FEES).job_id == ids[0]
    with pytest.raises(JobConflict):
        other.create(sid, ids[0], QuestionIntent.SUBSCRIPTIONS)
    with pytest.raises(JobLimitExceeded):
        other.create(sid, uuid4(), QuestionIntent.FEES)
    clock[0] += timedelta(minutes=25)
    assert jobs.get(sid, ids[0]).state == "failed"
    with pytest.raises(JobLimitExceeded):
        jobs.create(sid, uuid4(), QuestionIntent.FEES)
    assert sessions._metadata(sid)["question_job_count"] == MAX_JOBS_PER_SESSION
    assert len([row for row in table.scan()["Items"] if row["sk"].startswith("JOB#")]) == MAX_JOBS_PER_SESSION


def test_duplicate_put_rolls_back_counter_increment(setup):
    clock, sessions, sid, jobs, _, _, _, table = setup
    job = jobs.create(sid, uuid4(), QuestionIntent.FEES)
    assert jobs._write(job, None) is False
    assert sessions._metadata(sid)["question_job_count"] == 1
    claim = jobs.claim(sid, job.job_id)
    assert claim is not None
    assert jobs.finish(claim, None)
    assert sessions._metadata(sid)["question_job_count"] == 1
    assert table.get_item(Key=daily_counter_key(clock[0]))["Item"]["admitted_jobs"] == 1


def test_competing_writer_takes_last_slot_between_read_and_transaction(setup):
    clock, sessions, sid, jobs, _, _, _, table = setup
    for _ in range(MAX_JOBS_PER_SESSION - 1):
        jobs.create(sid, uuid4(), QuestionIntent.FEES)
    original_write = jobs._write
    competitor = DynamoDBJobStore(sessions, clock=lambda: clock[0])

    def competing_write(job, revision):
        competitor.create(sid, uuid4(), QuestionIntent.FEES)
        return original_write(job, revision)

    rejected_id = uuid4()
    with patch.object(jobs, "_write", side_effect=competing_write):
        with pytest.raises(JobLimitExceeded):
            jobs.create(sid, rejected_id, QuestionIntent.FEES)
    assert sessions._metadata(sid)["question_job_count"] == MAX_JOBS_PER_SESSION
    assert "Item" not in table.get_item(Key=jobs._key(sid, rejected_id))


def test_old_session_without_counter_fails_closed_but_existing_job_is_readable(setup):
    _, sessions, sid, jobs, _, _, _, table = setup
    job = jobs.create(sid, uuid4(), QuestionIntent.FEES)
    table.update_item(Key=sessions._key(sid), UpdateExpression="REMOVE question_job_count")
    assert jobs.create(sid, job.job_id, QuestionIntent.FEES).job_id == job.job_id
    with pytest.raises(SessionStoreError):
        jobs.create(sid, uuid4(), QuestionIntent.FEES)
    assert jobs.get(sid, job.job_id).state == "pending"
    sessions.purge(sid)
    assert session_rows(table) == []


def test_session_counter_is_independent_and_does_not_change_activity(setup):
    clock, sessions, sid, jobs, _, _, _, _ = setup
    first = sessions.peek(sid)
    clock[0] += timedelta(minutes=1)
    jobs.create(sid, uuid4(), QuestionIntent.FEES)
    assert sessions.peek(sid).idle_expires_at == first.idle_expires_at
    other = sessions.create("empty", ())
    jobs.create(other.session_id, uuid4(), QuestionIntent.FEES)
    assert sessions._metadata(sid)["question_job_count"] == 1
    assert sessions._metadata(other.session_id)["question_job_count"] == 1


def test_global_daily_limit_across_sessions_and_instances_survives_purge(setup):
    clock, sessions, _, jobs, _, _, _, table = setup
    admitted = []
    for _ in range(DAILY_JOB_LIMIT):
        sid = sessions.create("empty", ()).session_id
        admitted.append(jobs.create(sid, uuid4(), QuestionIntent.UNSUPPORTED))
    other = DynamoDBJobStore(DynamoDBSessionStore("jobs", clock=lambda: clock[0]), clock=lambda: clock[0])
    first = admitted[0]
    assert other.create(first.session_id, first.job_id, first.intent).job_id == first.job_id
    for job in admitted:
        sessions.purge(job.session_id)
    sid = sessions.create("empty", ()).session_id
    with pytest.raises(DailyJobLimitExceeded):
        other.create(sid, uuid4(), QuestionIntent.FEES)
    assert sessions._metadata(sid)["question_job_count"] == 0
    counter = table.get_item(Key=daily_counter_key(clock[0]))["Item"]
    assert counter["admitted_jobs"] == DAILY_JOB_LIMIT
    assert set(counter) == {"pk", "sk", "admitted_jobs", "expires_at"}
    assert counter["expires_at"] == counter_expires_at(clock[0])
    assert table.get_item(Key=control_key())["Item"]["enabled"] is True


def test_global_limit_rolls_over_by_utc_date_not_ttl_deletion(setup):
    clock, sessions, _, jobs, _, _, _, table = setup
    clock[0] = datetime(2026, 1, 1, 23, 59, tzinfo=UTC)
    admitted = []
    for _ in range(DAILY_JOB_LIMIT):
        sid = sessions.create("empty", ()).session_id
        admitted.append(jobs.create(sid, uuid4(), QuestionIntent.UNSUPPORTED))
    last = admitted[-1]
    previous_key = daily_counter_key(clock[0])
    clock[0] += timedelta(minutes=2)
    assert jobs.create(last.session_id, last.job_id, last.intent).job_id == last.job_id
    assert "Item" not in table.get_item(Key=daily_counter_key(clock[0]))
    jobs.create(last.session_id, uuid4(), QuestionIntent.FEES)
    assert table.get_item(Key=previous_key)["Item"]["admitted_jobs"] == DAILY_JOB_LIMIT
    assert table.get_item(Key=daily_counter_key(clock[0]))["Item"]["admitted_jobs"] == 1


def test_pause_blocks_new_jobs_but_not_replays_or_previously_queued_work(setup):
    clock, sessions, sid, jobs, provider, queue, service, table = setup
    request = SubmitQuestion(request_id=uuid4(), question="Explain fees")
    view = service.submit(sid, request)
    message = queue.enqueue.call_args.args[0]
    idle = sessions.peek(sid).idle_expires_at
    clock[0] += timedelta(minutes=1)
    table.update_item(Key=control_key(), UpdateExpression="SET #e = :no",
        ExpressionAttributeNames={"#e": "enabled"}, ExpressionAttributeValues={":no": False})
    with pytest.raises(DemoAdmissionsPaused):
        service.submit(sid, SubmitQuestion(request_id=uuid4(), question="Explain fees"))
    assert sessions.peek(sid).idle_expires_at == idle
    assert queue.enqueue.call_count == 1
    assert service.submit(sid, request).job_id == view.job_id
    QuestionWorker(sessions, jobs, provider).process(message)
    assert service.poll(sid, view.job_id).state == "succeeded"
    assert table.get_item(Key=daily_counter_key(clock[0]))["Item"]["admitted_jobs"] == 1
    table.update_item(Key=control_key(), UpdateExpression="SET #e = :yes",
        ExpressionAttributeNames={"#e": "enabled"}, ExpressionAttributeValues={":yes": True})
    jobs.create(sid, uuid4(), QuestionIntent.FEES)
    assert table.get_item(Key=daily_counter_key(clock[0]))["Item"]["admitted_jobs"] == 2


def test_last_global_slot_is_fenced_transactionally(setup):
    clock, sessions, sid, jobs, _, _, _, table = setup
    table.put_item(Item={**daily_counter_key(clock[0]), "admitted_jobs": DAILY_JOB_LIMIT - 1,
        "expires_at": counter_expires_at(clock[0])})
    competitor = DynamoDBJobStore(sessions, clock=lambda: clock[0])
    other = sessions.create("empty", ())
    original_write = jobs._write
    def competing_write(job, revision):
        competitor.create(other.session_id, uuid4(), QuestionIntent.UNSUPPORTED)
        return original_write(job, revision)
    rejected = uuid4()
    with patch.object(jobs, "_write", side_effect=competing_write):
        with pytest.raises(DailyJobLimitExceeded):
            jobs.create(sid, rejected, QuestionIntent.FEES)
    assert sessions._metadata(sid)["question_job_count"] == 0
    assert "Item" not in table.get_item(Key=jobs._key(sid, rejected))
    assert table.get_item(Key=daily_counter_key(clock[0]))["Item"]["admitted_jobs"] == DAILY_JOB_LIMIT


def test_same_id_concurrent_creator_charges_only_once(setup):
    clock, sessions, sid, jobs, _, _, _, table = setup
    competitor = DynamoDBJobStore(sessions, clock=lambda: clock[0])
    original_write = jobs._write
    def competing_write(job, revision):
        competitor.create(sid, job.job_id, job.intent)
        return original_write(job, revision)
    job_id = uuid4()
    with patch.object(jobs, "_write", side_effect=competing_write):
        assert jobs.create(sid, job_id, QuestionIntent.FEES).job_id == job_id
    assert sessions._metadata(sid)["question_job_count"] == 1
    assert table.get_item(Key=daily_counter_key(clock[0]))["Item"]["admitted_jobs"] == 1


def test_pause_between_read_and_write_rolls_back_all_slots(setup):
    clock, sessions, sid, jobs, _, _, _, table = setup
    original_write = jobs._write
    def pause_then_write(job, revision):
        table.put_item(Item={**control_key(), "schema_version": "1", "enabled": False})
        return original_write(job, revision)
    job_id = uuid4()
    with patch.object(jobs, "_write", side_effect=pause_then_write):
        with pytest.raises(DemoAdmissionsPaused):
            jobs.create(sid, job_id, QuestionIntent.FEES)
    assert sessions._metadata(sid)["question_job_count"] == 0
    assert "Item" not in table.get_item(Key=daily_counter_key(clock[0]))
    assert "Item" not in table.get_item(Key=jobs._key(sid, job_id))


@pytest.mark.parametrize("control", [None, {}, {"enabled": "true", "schema_version": "1"},
    {"enabled": True, "schema_version": "2"}])
def test_missing_or_malformed_control_fails_closed_without_enqueue(setup, control):
    clock, sessions, sid, _, _, queue, service, table = setup
    table.delete_item(Key=control_key())
    if control is not None:
        table.put_item(Item={**control_key(), **control})
    with pytest.raises(SessionStoreError):
        service.submit(sid, SubmitQuestion(request_id=uuid4(), question="Explain fees"))
    queue.enqueue.assert_not_called()
    assert sessions._metadata(sid)["question_job_count"] == 0
    assert "Item" not in table.get_item(Key=daily_counter_key(clock[0]))


@pytest.mark.parametrize("counter", [{}, {"admitted_jobs": -1}, {"admitted_jobs": "bad"},
    {"admitted_jobs": 0, "expires_at": 1}])
def test_invalid_daily_record_never_resets_quota(setup, counter):
    clock, sessions, sid, jobs, _, _, _, table = setup
    table.put_item(Item={**daily_counter_key(clock[0]), **counter})
    with pytest.raises(SessionStoreError):
        jobs.create(sid, uuid4(), QuestionIntent.FEES)
    assert sessions._metadata(sid)["question_job_count"] == 0


def test_failed_session_admission_does_not_spend_global_slot(setup):
    clock, sessions, sid, jobs, _, _, _, table = setup
    for _ in range(MAX_JOBS_PER_SESSION):
        jobs.create(sid, uuid4(), QuestionIntent.UNSUPPORTED)
    with pytest.raises(JobLimitExceeded):
        jobs.create(sid, uuid4(), QuestionIntent.FEES)
    assert table.get_item(Key=daily_counter_key(clock[0]))["Item"]["admitted_jobs"] == MAX_JOBS_PER_SESSION


def test_commit_then_transport_failure_is_recoverable_without_double_charge(setup):
    from botocore.exceptions import EndpointConnectionError
    clock, sessions, sid, jobs, _, queue, service, table = setup
    client = sessions._table().meta.client
    original = client.transact_write_items
    def commit_then_timeout(**kwargs):
        original(**kwargs)
        raise EndpointConnectionError(endpoint_url="https://synthetic.invalid")
    request = SubmitQuestion(request_id=uuid4(), question="Tell me a joke")
    with patch.object(client, "transact_write_items", side_effect=commit_then_timeout):
        with pytest.raises(SessionStoreError):
            service.submit(sid, request)
    queue.enqueue.assert_not_called()
    table.put_item(Item={**control_key(), "schema_version": "1", "enabled": False})
    assert service.submit(sid, request).job_id == request.request_id
    queue.enqueue.assert_called_once()
    assert sessions._metadata(sid)["question_job_count"] == 1
    assert table.get_item(Key=daily_counter_key(clock[0]))["Item"]["admitted_jobs"] == 1
