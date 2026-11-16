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
