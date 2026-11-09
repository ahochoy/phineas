from unittest.mock import Mock
from uuid import UUID

import pytest
from botocore.exceptions import ClientError
from fastapi.testclient import TestClient

from phineas.analysis import analyze_transactions
from phineas.api import create_app
from phineas.bedrock import AgentCoreNarrativeProvider
from phineas.narratives import (
    NarrativeUnavailable, build_fact_cards, encode_facts, generate_highlights,
)
from phineas.samples import ingest_sample


def report():
    return analyze_transactions(ingest_sample("analysis-demo"))


def test_fact_projection_excludes_private_fields_and_preserves_candidates() -> None:
    payload = encode_facts(build_fact_cards(report()))
    for private in ("Example Streaming", "Sample Shop", "txn_", "session_id", "evidence_transaction_ids", "original_description"):
        assert private not in payload
    assert "155.88" in payload
    assert "possible duplicates" in payload
    assert "not a confirmed subscription" in payload


@pytest.mark.parametrize("raw", [
    '{"fact_ids":["invented"]}', '{"fact_ids":["fee","fee"]}',
    '{"fact_ids":[]}', '{"fact_ids":["fee"],"text":"invented financial advice"}',
    'not json', '{"fact_ids":["fee", "interest", "coverage", "duplicate_0", "subscription_0", "extra"]}',
])
def test_invalid_model_output_fails_closed(raw: str) -> None:
    provider = Mock()
    provider.select.return_value = raw
    assert generate_highlights(report(), provider).narrative_status == "unavailable"


def test_valid_selection_is_rendered_from_original_facts() -> None:
    provider = Mock()
    provider.select.return_value = '{"fact_ids":["fee","subscription_0"]}'
    result = generate_highlights(report(), provider)
    assert result.narrative_status == "generated"
    assert [fact.fact_id for fact in result.highlights] == ["fee", "subscription_0"]
    assert "155.88" in result.highlights[1].text
    assert generate_highlights(report(), None).narrative_status == "skipped"
    provider.select.side_effect = NarrativeUnavailable()
    assert generate_highlights(report(), provider).narrative_status == "unavailable"


class Stream:
    def __init__(self, events: list[dict]) -> None:
        self.events = events
        self.closed = False

    def __iter__(self):
        return iter(self.events)

    def close(self) -> None:
        self.closed = True


def test_harness_stream_request_is_bounded_and_isolated() -> None:
    stream = Stream([
        {"contentBlockDelta": {"delta": {"text": '{"fact_ids":'}}},
        {"contentBlockDelta": {"delta": {"text": '["fee"]}'}}},
        {"messageStop": {"stopReason": "end_turn"}},
    ])
    client = Mock()
    client.invoke_harness.return_value = {"stream": stream}
    provider = AgentCoreNarrativeProvider("test-arn", client=client)
    assert generate_highlights(report(), provider).narrative_status == "generated"
    first = client.invoke_harness.call_args.kwargs
    UUID(first["runtimeSessionId"])
    assert first["maxTokens"] == 512
    assert first["maxIterations"] == 1
    assert first["allowedTools"] == ["phineas_no_tools"]
    assert set(first) == {"harnessArn", "runtimeSessionId", "messages", "maxIterations", "maxTokens", "timeoutSeconds", "allowedTools"}
    provider.select(build_fact_cards(report()))
    assert client.invoke_harness.call_args.kwargs["runtimeSessionId"] != first["runtimeSessionId"]
    assert stream.closed


@pytest.mark.parametrize("events", [
    [{"runtimeClientError": {}}],
    [{"validationException": {}}],
    [{"internalServerException": {}}],
    [{"messageStop": {"stopReason": "max_tokens"}}],
    [{"contentBlockDelta": {"delta": {"text": '{"fact_ids":["fee"]}'}}}],
    [{"contentBlockStart": {"start": {"toolUse": {"name": "shell"}}}}],
    [{"contentBlockDelta": {"delta": {"text": "x" * 8193}}}],
])
def test_stream_errors_truncation_and_tools_fail_closed(events: list[dict]) -> None:
    stream = Stream(events)
    client = Mock()
    client.invoke_harness.return_value = {"stream": stream}
    result = generate_highlights(report(), AgentCoreNarrativeProvider("test", client=client))
    assert result.narrative_status == "unavailable"
    assert result.highlights == ()
    assert stream.closed


def test_aws_error_does_not_expose_provider_details() -> None:
    client = Mock()
    client.invoke_harness.side_effect = ClientError(
        {"Error": {"Code": "AccessDeniedException", "Message": "private details"}}, "InvokeHarness")
    provider = AgentCoreNarrativeProvider("test", client=client)
    assert "private details" not in generate_highlights(report(), provider).model_dump_json()


def test_api_narrative_fallback_preserves_analysis_and_purge_boundary() -> None:
    provider = Mock()
    provider.select.side_effect = NarrativeUnavailable()
    with TestClient(create_app(narrative_provider=provider)) as client:
        key = client.post("/sessions", json={"sample_id": "analysis-demo"}).json()["session_id"]
        response = client.post(f"/sessions/{key}/narrative")
        assert response.status_code == 200
        assert response.json()["narrative_status"] == "unavailable"
        assert client.get(f"/sessions/{key}/analysis").status_code == 200
        client.delete(f"/sessions/{key}")
        assert client.post(f"/sessions/{key}/narrative").status_code == 404
        assert provider.select.call_count == 1


def test_unconfigured_api_skips_aws() -> None:
    with TestClient(create_app()) as client:
        key = client.post("/sessions", json={"sample_id": "analysis-demo"}).json()["session_id"]
        assert client.post(f"/sessions/{key}/narrative").json()["narrative_status"] == "skipped"
