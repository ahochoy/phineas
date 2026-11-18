import importlib.util
import io
import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from botocore.exceptions import ClientError, EventStreamError

spec = importlib.util.spec_from_file_location("comparison",
    Path(__file__).resolve().parents[1] / "scripts/compare_narrative_models.py")
assert spec is not None and spec.loader is not None
comparison = importlib.util.module_from_spec(spec)
spec.loader.exec_module(comparison)


def test_model_settings_match_caps_and_temperature_without_extra_parameters():
    nova, sonnet = map(comparison.model_config, comparison.MODELS)
    assert comparison.MODELS[1] == "us.anthropic.claude-sonnet-4-6"
    assert nova["temperature"] == sonnet["temperature"] == 0.1
    assert nova["maxTokens"] == sonnet["maxTokens"] == 1024
    assert "additionalParams" not in sonnet


def test_overrides_and_usage_are_isolated_to_evaluation_client():
    client = Mock()
    stream = Mock()
    stream.__iter__ = Mock(return_value=iter([{"metadata": {"usage": {"inputTokens": 10}}}]))
    client.invoke_harness.return_value = {"stream": stream}
    measured = comparison.EvaluationClient(client, comparison.MODELS[1], "test prompt")
    response = measured.invoke_harness(harnessArn="test", allowedTools=["phineas_no_tools"])
    list(response["stream"])
    response["stream"].close()
    request = client.invoke_harness.call_args.kwargs
    assert request["systemPrompt"] == [{"text": "test prompt"}]
    assert request["allowedTools"] == ["phineas_no_tools"]
    assert measured.usage == {"inputTokens": 10}
    stream.close.assert_called_once()


def test_failed_generation_stops_without_retries_or_financial_stdout(capsys):
    client = Mock()
    # An empty completed stream fails closed in the existing production parser.
    client.invoke_harness.return_value = {"stream": Mock()}
    client.invoke_harness.return_value["stream"].__iter__ = Mock(return_value=iter([]))
    output = io.StringIO()
    assert comparison.run_comparison(client, "test", "test", output) == 1
    client.invoke_harness.assert_called_once()
    record = json.loads(output.getvalue())
    assert record["synthetic_only"] is True
    assert record["explanation"]["status"] == "unavailable"
    assert record["human_review"] is None
    assert "USD" not in capsys.readouterr().out


def test_probe_calls_only_candidate_once_and_reports_safe_stream_error(capsys):
    client = Mock()
    stream = Mock()
    stream.__iter__ = Mock(return_value=iter([
        {"runtimeClientError": {"message": "PRIVATE PROVIDER PAYLOAD"}},
    ]))
    client.invoke_harness.return_value = {"stream": stream}
    output = io.StringIO()
    assert comparison.run_comparison(client, "test", "test", output, probe=True) == 1
    client.invoke_harness.assert_called_once()
    record = json.loads(output.getvalue())
    assert record["model"] == comparison.MODELS[1]
    assert record["diagnostics"]["stream_error"] == "runtimeClientError"
    assert record["diagnostics"]["stream_opened"] is True
    assert "PRIVATE" not in output.getvalue() + capsys.readouterr().out
    stream.close.assert_called_once()


def test_api_error_diagnostics_never_include_provider_message():
    client = Mock()
    client.invoke_harness.side_effect = ClientError(
        {"Error": {"Code": "AccessDeniedException", "Message": "PRIVATE"}}, "InvokeHarness")
    measured = comparison.EvaluationClient(client, comparison.MODELS[1], "test")
    with pytest.raises(ClientError):
        measured.invoke_harness(harnessArn="test")
    assert measured.diagnostics["api_error"] == "AccessDeniedException"
    assert "PRIVATE" not in json.dumps(measured.diagnostics)


def test_error_raised_during_iteration_is_visible_without_payload(capsys):
    def events():
        raise EventStreamError({"Error": {"Code": "ValidationException",
            "Message": "PRIVATE temperature unsupported"}}, "InvokeHarness")
        yield  # Make a generator whose failure occurs on iteration.

    client = Mock()
    stream = Mock()
    stream.__iter__ = Mock(side_effect=events)
    client.invoke_harness.return_value = {"stream": stream}
    output = io.StringIO()
    assert comparison.run_comparison(client, "test", "test", output, probe=True) == 1
    diagnostics = json.loads(output.getvalue())["diagnostics"]
    assert diagnostics["sdk_error"] == "EventStreamError"
    assert diagnostics["api_error"] == "ValidationException"
    assert diagnostics["error_hints"] == ["sampling_parameter"]
    assert "PRIVATE" not in output.getvalue() + capsys.readouterr().out
    stream.close.assert_called_once()


@pytest.mark.parametrize("raw,reason", [
    ("PRIVATE invalid json", "json_or_schema"),
    (json.dumps({"paragraphs": [{"text": "I found USD 999.00 in fees to review.",
                                  "fact_ids": ["fee"]}]}), "unsupported_number"),
])
def test_completed_but_rejected_output_has_safe_reason(raw, reason, capsys):
    client = Mock()
    stream = Mock()
    stream.__iter__ = Mock(return_value=iter([
        {"contentBlockDelta": {"delta": {"text": raw}}},
        {"messageStop": {"stopReason": "end_turn"}},
    ]))
    client.invoke_harness.return_value = {"stream": stream}
    output = io.StringIO()
    assert comparison.run_comparison(client, "test", "test", output, probe=True) == 1
    record = json.loads(output.getvalue())
    assert record["diagnostics"]["transport_completed"] is True
    assert record["diagnostics"]["validation_rejection"] == reason
    assert record["explanation"]["paragraphs"] == []
    console = capsys.readouterr().out
    assert "PRIVATE" not in console
    assert "999" not in console
    if reason == "json_or_schema":
        assert record["rejected_synthetic_draft"] is None
        assert "PRIVATE" not in output.getvalue()
    else:
        assert record["rejected_synthetic_draft"] == json.loads(raw)


def test_full_comparison_records_quality_failures_without_stopping(capsys):
    def response(**kwargs):
        stream = Mock()
        stream.__iter__ = Mock(return_value=iter([
            {"contentBlockDelta": {"delta": {"text": "invalid JSON"}}},
            {"messageStop": {"stopReason": "end_turn"}},
        ]))
        return {"stream": stream}

    client = Mock()
    client.invoke_harness.side_effect = response
    output = io.StringIO()
    assert comparison.run_comparison(client, "test", "test", output) == 1
    assert client.invoke_harness.call_count == 36
    records = [json.loads(line) for line in output.getvalue().splitlines()]
    assert len(records) == 36
    assert {r["model"] for r in records} == set(comparison.MODELS)
    assert {r["repeat"] for r in records} == {1, 2, 3}
    assert len({r["intent"] for r in records}) == 6
    assert all(r["diagnostics"]["validation_rejection"] == "json_or_schema" for r in records)
    assert "Evaluation completed; validation rejections: 36" in capsys.readouterr().out
