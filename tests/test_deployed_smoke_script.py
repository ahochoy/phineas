import importlib.util
from pathlib import Path
from unittest.mock import Mock

import pytest


spec = importlib.util.spec_from_file_location("deployed_smoke",
    Path(__file__).resolve().parents[1] / "scripts/test_deployed_api.py")
assert spec is not None and spec.loader is not None
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


def responses(state="succeeded"):
    result = {"intent": "fees", "facts": [{"fact_id": "fee"}],
        "narrative": {"narrative_status": "generated", "highlights": [{"fact_id": "fee"}]}}
    return [
        {"status": 201, "body": {"session_id": "PRIVATE_SESSION"}},
        {"status": 200, "body": {"subscription_candidates": [{}]}},
        {"status": 202, "body": {"job_id": "PRIVATE_JOB"}},
        {"status": 202, "body": {"job_id": "PRIVATE_JOB"}},
        {"status": 200, "body": {"state": state, "result": result}},
        {"status": 204, "body": None},
        {"status": 404, "body": {"detail": "session_unavailable"}},
        {"status": 404, "body": {"detail": "session_unavailable"}},
    ]


def test_async_deployment_check_and_safe_output(capsys):
    request = Mock(side_effect=responses())
    smoke.verify_deployment(request)
    calls = request.call_args_list
    assert calls[2].args[2] == calls[3].args[2]
    assert calls[4].args[1].endswith("/jobs/PRIVATE_JOB")
    assert calls[5].args[0] == "DELETE"
    output = capsys.readouterr().out
    assert "SQS worker and AgentCore fee result: passed" in output
    assert "PRIVATE" not in output


def test_explanation_deployment_gate_does_not_accept_legacy_only_result():
    data = responses()
    request = Mock(side_effect=data[:5] + [data[5]])
    with pytest.raises(RuntimeError, match="^explanation_not_generated$"):
        smoke.verify_deployment(request, require_explanation=True)
    assert request.call_args.args[0] == "DELETE"


def test_explanation_deployment_gate_with_new_result(capsys):
    data = responses()
    data[4]["body"]["result"]["explanation"] = {"status": "generated", "paragraphs": [
        {"text": "Your fee deserves review; its cause is not established.", "fact_ids": ["fee"]},
    ]}
    smoke.verify_deployment(Mock(side_effect=data), require_explanation=True)
    assert "Grounded conversational explanation: passed" in capsys.readouterr().out


def test_polling_pending_then_success():
    data = responses()
    data.insert(4, {"status": 200, "body": {"state": "pending"}})
    pause = Mock()
    smoke.verify_deployment(Mock(side_effect=data), pause=pause)
    pause.assert_called_once()


def test_terminal_failure_still_purges(capsys):
    request = Mock(side_effect=responses("failed"))
    with pytest.raises(RuntimeError, match="^async_job_failed$"):
        smoke.verify_deployment(request)
    assert request.call_args.args[0] == "DELETE"
    assert "PRIVATE" not in capsys.readouterr().out


def test_timeout_still_purges():
    data = responses()
    del data[4]
    request = Mock(side_effect=data)
    with pytest.raises(RuntimeError, match="^async_job_timeout$"):
        smoke.verify_deployment(request, timeout=0)
    assert request.call_args.args[0] == "DELETE"


def test_failed_submission_still_purges():
    data = responses()
    data[2] = {"status": 503, "body": {"detail": "job_queue_unavailable"}}
    request = Mock(side_effect=data[:3] + [data[5]])
    with pytest.raises(RuntimeError, match="^job_submission_failed$"):
        smoke.verify_deployment(request)
    assert request.call_args.args[0] == "DELETE"


def admission_responses():
    blocked = {"status": 409, "body": {"detail": "async_questions_required"}}
    return [
        {"status": 201, "body": {"session_id": "PRIVATE_SESSION"}},
        blocked, blocked,
        *[{"status": 202, "body": {"job_id": f"PRIVATE_JOB_{i}"}} for i in range(10)],
        {"status": 202, "body": {"job_id": "PRIVATE_JOB_0"}},
        {"status": 429, "body": {"detail": "question_job_limit_reached"}},
        {"status": 200, "body": {}},
        {"status": 200, "body": {}},
        {"status": 204, "body": None},
        {"status": 404, "body": {"detail": "session_unavailable"}},
        {"status": 404, "body": {"detail": "session_unavailable"}},
    ]


def test_admission_checker_preserves_replay_id_and_safe_output(capsys):
    request = Mock(side_effect=admission_responses())
    smoke.verify_admission(request)
    calls = request.call_args_list
    assert calls[3].args[2] == calls[13].args[2]
    ids = [calls[i].args[2]["request_id"] for i in range(3, 13)]
    assert len(set(ids)) == 10
    assert calls[14].args[2]["request_id"] not in ids
    assert all(calls[i].args[2]["question"] == "Tell me a joke" for i in range(3, 15))
    assert calls[17].args[0] == "DELETE"
    output = capsys.readouterr().out
    assert "Eleventh distinct job rejected: passed" in output
    assert "PRIVATE" not in output


@pytest.mark.parametrize("index,reason", [
    (1, "synchronous_question_bypass_open"),
    (2, "synchronous_narrative_bypass_open"),
    (3, "admission_below_limit_failed"),
    (13, "replay_at_capacity_failed"),
    (14, "eleventh_job_not_rejected"),
])
def test_admission_checker_purges_on_failed_gate(index, reason):
    data = admission_responses()
    data[index] = {"status": 200, "body": {}}
    request = Mock(side_effect=data[:index + 1] + [{"status": 204, "body": None}])
    with pytest.raises(RuntimeError, match=f"^{reason}$"):
        smoke.verify_admission(request)
    assert request.call_args.args[0] == "DELETE"


def test_admission_checker_against_real_local_api():
    from fastapi.testclient import TestClient
    from phineas.api import create_app
    from phineas.jobs import InMemoryJobStore, QuestionJobService
    from phineas.sessions import InMemorySessionStore

    sessions = InMemorySessionStore()
    queue = Mock()
    provider = Mock()
    service = QuestionJobService(sessions, InMemoryJobStore(sessions), queue)
    with TestClient(create_app(sessions, narrative_provider=provider, job_service=service)) as client:
        def request(method, path, body=None):
            response = client.request(method, path, json=body) if body is not None else client.request(method, path)
            return {"status": response.status_code, "body": response.json() if response.content else None}
        smoke.verify_admission(request)
    provider.select.assert_not_called()
    assert queue.enqueue.call_count == 11  # Ten jobs plus one pending replay.


def test_admission_flag_selects_checker_without_aws_calls(monkeypatch):
    monkeypatch.setattr("sys.argv", ["test_deployed_api.py", "phineas-api", "--admission-only"])
    from unittest.mock import patch
    with patch.object(smoke, "verify_admission") as admission, \
            patch.object(smoke, "verify_deployment") as deployment, \
            patch.object(smoke.boto3, "client") as client:
        assert smoke.main() == 0
        admission.assert_called_once()
        deployment.assert_not_called()
        client.assert_not_called()


def paused_responses():
    return [
        {"status": 201, "body": {"session_id": "PRIVATE_SESSION"}},
        {"status": 503, "body": {"detail": "demo_admissions_paused"}},
        {"status": 200, "body": {}},
        {"status": 204, "body": None},
        {"status": 404, "body": {"detail": "session_unavailable"}},
    ]


def test_pause_checker_and_safe_output(capsys):
    request = Mock(side_effect=paused_responses())
    smoke.verify_paused(request)
    assert request.call_args_list[1].args[2]["question"] == "Tell me a joke"
    assert request.call_args_list[3].args[0] == "DELETE"
    output = capsys.readouterr().out
    assert "New job rejected by admission pause: passed" in output
    assert "PRIVATE" not in output


@pytest.mark.parametrize("response", [
    {"status": 202, "body": {"job_id": "PRIVATE_JOB"}},
    {"status": 503, "body": {"detail": "session_store_unavailable"}},
    {"status": 429, "body": {"detail": "demo_daily_job_limit_reached"}},
])
def test_pause_checker_requires_exact_control_response_and_cleans_up(response):
    data = paused_responses()
    request = Mock(side_effect=[data[0], response, data[3]])
    with pytest.raises(RuntimeError, match="^expected_admission_pause_missing$"):
        smoke.verify_paused(request)
    assert request.call_args.args[0] == "DELETE"


def test_pause_checker_cleans_up_if_analysis_fails():
    data = paused_responses()
    data[2] = {"status": 503, "body": {"detail": "session_store_unavailable"}}
    request = Mock(side_effect=data)
    with pytest.raises(RuntimeError, match="^analysis_unavailable_while_paused$"):
        smoke.verify_paused(request)
    assert request.call_args.args[0] == "DELETE"


def test_pause_checker_against_local_api_spends_no_slots():
    from fastapi.testclient import TestClient
    from phineas.api import create_app
    from phineas.jobs import InMemoryJobStore, QuestionJobService
    from phineas.sessions import InMemorySessionStore

    sessions = InMemorySessionStore()
    jobs = InMemoryJobStore(sessions)
    jobs.set_admissions_enabled(False)
    queue, provider = Mock(), Mock()
    service = QuestionJobService(sessions, jobs, queue)
    with TestClient(create_app(sessions, narrative_provider=provider, job_service=service)) as client:
        def request(method, path, body=None):
            response = client.request(method, path, json=body) if body is not None else client.request(method, path)
            return {"status": response.status_code, "body": response.json() if response.content else None}
        smoke.verify_paused(request)
    queue.enqueue.assert_not_called()
    provider.select.assert_not_called()
    assert jobs._daily_counts == {}
    assert jobs._jobs == {}


def test_paused_flag_selects_checker_without_aws_calls(monkeypatch):
    monkeypatch.setattr("sys.argv", ["test_deployed_api.py", "phineas-api", "--paused-only"])
    from unittest.mock import patch
    with patch.object(smoke, "verify_paused") as paused, \
            patch.object(smoke, "verify_deployment") as deployment, \
            patch.object(smoke, "verify_admission") as admission, \
            patch.object(smoke.boto3, "client") as client:
        assert smoke.main() == 0
        paused.assert_called_once()
        deployment.assert_not_called()
        admission.assert_not_called()
        client.assert_not_called()


def test_smoke_modes_are_mutually_exclusive(monkeypatch):
    monkeypatch.setattr("sys.argv", ["test_deployed_api.py", "phineas-api", "--paused-only", "--admission-only"])
    with pytest.raises(SystemExit) as error:
        smoke.main()
    assert error.value.code == 2
