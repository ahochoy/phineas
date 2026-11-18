import importlib.util
from pathlib import Path
from unittest.mock import Mock

import pytest


spec = importlib.util.spec_from_file_location("origin_check",
    Path(__file__).resolve().parents[1] / "scripts/test_public_origin.py")
assert spec is not None and spec.loader is not None
script = importlib.util.module_from_spec(spec)
spec.loader.exec_module(script)
ORIGIN = "https://51b01wb0w6.execute-api.us-east-2.amazonaws.com/public"
SID = "private-session-" + "a" * 32


@pytest.mark.parametrize("url", [
    "http://51b01wb0w6.execute-api.us-east-2.amazonaws.com/public",
    "https://evil.example/public", ORIGIN + "?token=private", ORIGIN + "#fragment",
    "https://51b01wb0w6.execute-api.us-east-2.amazonaws.com.evil.example/public",
])
def test_secret_cannot_be_sent_to_arbitrary_url(url):
    with pytest.raises(ValueError):
        script.validate_origin(url)


def responses():
    return [
        (401, {}, {}), (403, {}, {}),
        (200, {"status": "ok"}, {"cache-control": "no-store"}),
        (200, {"synthetic": True, "rows": [[]] * 50}, {}),
        (404, {}, {}), (404, {}, {}), (201, {"session_id": SID}, {}),
        (200, {"analysis": {}, "facts": []}, {"cache-control": "no-store"}),
        (204, None, {}), (404, {"detail": "session_unavailable"}, {}),
    ]


def test_happy_path_cleans_up_without_model_calls_or_capability_output(capsys):
    client = Mock()
    client.request.side_effect = responses()
    script.check(client)
    calls = client.request.call_args_list
    assert any(c.kwargs.get("method") == "DELETE" for c in calls)
    assert all("question-jobs" not in c.args[0] for c in calls)
    assert SID not in capsys.readouterr().out


def test_cleanup_attempted_if_report_check_fails():
    client = Mock()
    values = responses()
    values[7] = (502, {}, {})
    client.request.side_effect = values
    with pytest.raises(ValueError):
        script.check(client)
    assert client.request.call_args.kwargs["method"] == "DELETE"


def test_redirect_handler_refuses_to_forward_credentials():
    assert script.NoRedirects().redirect_request(None, None, 302, "redirect", {}, "https://evil.example") is None


def test_health_only_never_creates_session():
    client = Mock()
    client.request.side_effect = responses()[:3]
    script.check(client, health_only=True)
    assert client.request.call_count == 3


def test_health_failure_diagnostics_do_not_echo_response_body(capsys):
    client = Mock()
    client.request.side_effect = [*responses()[:2], (404, {"detail": "PRIVATE"}, {"cache-control": "no-store"})]
    with pytest.raises(ValueError):
        script.check(client, health_only=True)
    output = capsys.readouterr().out
    assert '"status": 404' in output
    assert '"body_matches": false' in output
    assert "PRIVATE" not in output
