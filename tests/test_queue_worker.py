from datetime import UTC, datetime, timedelta
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest

from phineas.jobs import (
    InMemoryJobStore, JobMessage, QuestionJobService, QuestionWorker,
    SubmitQuestion, WorkerRetry,
)
from phineas.narratives import NarrativeUnavailable
from phineas.questions import QuestionIntent
from phineas.queue_worker import (
    MIN_START_TIME_MS, _configured_worker, lambda_handler, process_sqs_batch,
)
from phineas.samples import ingest_sample
from phineas.sessions import InMemorySessionStore, SessionStoreError


def record(message, message_id="delivery-1"):
    return {"messageId": message_id, "eventSource": "aws:sqs", "body": message.model_dump_json()}


@pytest.fixture
def context():
    value = Mock()
    value.get_remaining_time_in_millis.return_value = 120_000
    return value


@pytest.fixture
def setup():
    clock = [datetime(2026, 1, 1, tzinfo=UTC)]
    sessions = InMemorySessionStore(lambda: clock[0])
    session = sessions.create("analysis-demo", ingest_sample("analysis-demo"))
    jobs = InMemoryJobStore(sessions, lambda: clock[0])
    queue = Mock()
    provider = Mock()
    provider.select.return_value = '{"fact_ids":["fee"]}'
    service = QuestionJobService(sessions, jobs, queue)
    view = service.submit(session.session_id,
        SubmitQuestion(request_id=uuid4(), question="Explain fees"))
    message = queue.enqueue.call_args.args[0]
    return clock, sessions, jobs, provider, service, view, message, QuestionWorker(sessions, jobs, provider)


def test_handler_processes_and_acknowledges_duplicate_work(setup, context):
    _, _, _, provider, service, view, message, worker = setup
    event = {"Records": [record(message)]}
    with patch("phineas.queue_worker._configured_worker", return_value=worker):
        assert lambda_handler(event, context) == {"batchItemFailures": []}
        assert lambda_handler(event, context) == {"batchItemFailures": []}
    assert provider.select.call_count == 1
    assert service.poll(message.session_id, view.job_id).state == "succeeded"


@pytest.mark.parametrize("failure", [WorkerRetry(), SessionStoreError(), RuntimeError("SECRET")])
def test_partial_response_retries_only_failed_delivery(context, failure, caplog, capsys):
    message = JobMessage(session_id="SECRET", job_id=uuid4(), intent=QuestionIntent.FEES)
    worker = Mock()
    worker.process.side_effect = [None, failure, None]
    response = process_sqs_batch({"Records": [record(message, str(i)) for i in range(3)]}, worker, context)
    assert response == {"batchItemFailures": [{"itemIdentifier": "1"}]}
    assert worker.process.call_count == 3
    assert "SECRET" not in caplog.text
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""


def test_active_lease_retries_without_inference(setup, context):
    _, _, jobs, provider, _, view, message, worker = setup
    jobs.claim(message.session_id, view.job_id)
    assert process_sqs_batch({"Records": [record(message)]}, worker, context) == {
        "batchItemFailures": [{"itemIdentifier": "delivery-1"}]}
    provider.select.assert_not_called()


def test_model_failure_retries_until_terminal_job_then_acknowledges(setup, context):
    _, _, _, provider, service, view, message, worker = setup
    provider.select.side_effect = NarrativeUnavailable()
    event = {"Records": [record(message)]}
    for _ in range(2):
        assert process_sqs_batch(event, worker, context)["batchItemFailures"]
    assert process_sqs_batch(event, worker, context) == {"batchItemFailures": []}
    assert service.poll(message.session_id, view.job_id).state == "failed"
    assert provider.select.call_count == 3


@pytest.mark.parametrize("invalidated", ["expired", "purged", "missing"])
def test_invalidated_work_acknowledges_without_model(setup, context, invalidated):
    clock, _, _, provider, service, _, message, worker = setup
    if invalidated == "expired":
        clock[0] += timedelta(minutes=30)
    elif invalidated == "purged":
        service.purge(message.session_id)
    else:
        message = message.model_copy(update={"session_id": "nonexistent"})
    assert process_sqs_batch({"Records": [record(message)]}, worker, context) == {"batchItemFailures": []}
    provider.select.assert_not_called()


@pytest.mark.parametrize("body", ["not JSON SECRET", '{"question":"SECRET"}',
    '{"session_id":"SECRET","job_id":"bad","intent":"fees"}'])
def test_malformed_body_retries_without_logging_or_processing(context, body, caplog, capsys):
    worker = Mock()
    event = {"Records": [{"messageId": "bad", "eventSource": "aws:sqs", "body": body}]}
    assert process_sqs_batch(event, worker, context) == {"batchItemFailures": [{"itemIdentifier": "bad"}]}
    worker.process.assert_not_called()
    assert caplog.text == ""
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""


@pytest.mark.parametrize("event", [{}, {"Records": "SECRET"},
    {"Records": [{"messageId": "", "body": "SECRET", "eventSource": "aws:sqs"}]},
    {"Records": [{"messageId": "id", "body": "SECRET", "eventSource": "aws:sns"}]}])
def test_invalid_envelope_fails_whole_batch_with_safe_reason(context, event):
    with pytest.raises(ValueError, match="^invalid_sqs_envelope$") as error:
        process_sqs_batch(event, Mock(), context)
    assert error.value.__suppress_context__


def test_time_budget_defers_work_without_claiming(setup, context):
    _, _, jobs, provider, _, view, message, worker = setup
    context.get_remaining_time_in_millis.return_value = MIN_START_TIME_MS - 1
    assert process_sqs_batch({"Records": [record(message)]}, worker, context) == {
        "batchItemFailures": [{"itemIdentifier": "delivery-1"}]}
    assert jobs.get(message.session_id, view.job_id).attempts == 0
    provider.select.assert_not_called()


def test_time_budget_is_rechecked_between_messages(context):
    message = JobMessage(session_id="opaque", job_id=uuid4(), intent=QuestionIntent.FEES)
    context.get_remaining_time_in_millis.side_effect = [120_000, 10_000]
    worker = Mock()
    response = process_sqs_batch({"Records": [record(message, "first"), record(message, "second")]}, worker, context)
    assert response == {"batchItemFailures": [{"itemIdentifier": "second"}]}
    assert worker.process.call_count == 1


def test_empty_batch_is_success(context):
    assert process_sqs_batch({"Records": []}, Mock(), context) == {"batchItemFailures": []}


def test_duplicate_delivery_ids_fail_before_any_work(context):
    message = JobMessage(session_id="opaque", job_id=uuid4(), intent=QuestionIntent.FEES)
    worker = Mock()
    with pytest.raises(ValueError, match="^invalid_sqs_envelope$"):
        process_sqs_batch({"Records": [record(message), record(message)]}, worker, context)
    worker.process.assert_not_called()


def test_configuration_requires_table_and_harness(monkeypatch):
    _configured_worker.cache_clear()
    monkeypatch.delenv("PHINEAS_SESSIONS_TABLE", raising=False)
    monkeypatch.delenv("PHINEAS_HARNESS_ARN", raising=False)
    with pytest.raises(ValueError, match="^question_worker_not_configured$"):
        _configured_worker()


def test_configured_worker_reuses_dependencies_without_aws_calls(monkeypatch):
    _configured_worker.cache_clear()
    monkeypatch.setenv("PHINEAS_SESSIONS_TABLE", "sessions")
    monkeypatch.setenv("PHINEAS_HARNESS_ARN", "arn:synthetic")
    monkeypatch.setenv("AWS_REGION", "us-east-2")
    try:
        with patch("phineas.queue_worker.DynamoDBSessionStore") as sessions, \
                patch("phineas.queue_worker.DynamoDBJobStore") as jobs, \
                patch("phineas.queue_worker.AgentCoreNarrativeProvider") as provider:
            first = _configured_worker()
            assert _configured_worker() is first
            sessions.assert_called_once_with("sessions", "us-east-2")
            jobs.assert_called_once_with(sessions.return_value)
            provider.assert_called_once_with("arn:synthetic", "us-east-2")
    finally:
        _configured_worker.cache_clear()
