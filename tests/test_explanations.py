import json
from unittest.mock import Mock

import pytest
from pydantic import BaseModel

from phineas.analysis import analyze_transactions
from phineas.bedrock import AgentCoreNarrativeProvider
from phineas.narratives import FactCard, NarrativeResult, build_fact_cards, explain_facts
from phineas.questions import QuestionResponse, answer_question
from phineas.samples import ingest_sample


def draft(text, fact_ids=("fee",)):
    return json.dumps({"paragraphs": [{"text": text, "fact_ids": fact_ids}]})


def fee():
    return (FactCard(fact_id="fee", text="1 outflow fee transaction(s) total USD 3.00."),)


def test_one_other_thing_transition_is_not_a_financial_count():
    provider = Mock()
    provider.explain.return_value = draft(
        "One other thing: 10 transactions were excluded from recurrence and duplicate checks. "
        "They remain in the cash-movement summary.", ("coverage",))
    facts = (FactCard(fact_id="coverage", text=
        "0 transactions have unknown kinds. 10 transactions were excluded from purchase "
        "recurrence and duplicate checks by analysis policy. Exclusion does not remove "
        "transactions from the cash-movement summary."),)
    assert explain_facts("coverage", facts, provider).status == "generated"


@pytest.mark.parametrize("text", [
    "I found one fee totaling USD 9.00. Review the statement.",
    "One other thing: I found one fee totaling USD 9.00.",
    "One other fee totals USD 9.00. Review the statement.",
    "One other thing is a fee totaling USD 9.00.",
])
def test_discourse_exception_does_not_allow_unsupported_counts(text):
    provider = Mock()
    provider.explain.return_value = draft(text)
    facts = (FactCard(fact_id="fee", text="3 outflow fee transaction(s) total USD 9.00."),)
    assert explain_facts("fees", facts, provider).status == "unavailable"


# Synthetic reference answers exercise the acceptance contract for all six
# topics. These are NOT measurements of live-model quality.
@pytest.mark.parametrize("question,text,ids", [
    ("Explain fees", "Your statement includes 3 fees totaling USD 9.00. The aggregate does not establish their cause or cadence. Check the statement description for context.", ("fee",)),
    ("Explain interest", "Your statement records USD 7.50 in interest. The aggregate does not provide a rate or establish why it was charged; review the interest section of the statement for those details.", ("interest",)),
    ("Show subscriptions", "There is a possible monthly recurring charge of USD 12.99. If it continues, its estimated annualized cost is USD 155.88. This pattern is a candidate for review rather than a confirmed subscription.", ("subscription_0",)),
    ("Show possible duplicates", "You have 2 purchases of USD 20.00 with the same merchant and posting date. They are possible duplicates, but a legitimate repeat purchase could explain the match; review the corresponding receipts before drawing a conclusion.", ("duplicate_0",)),
    ("Explain classification coverage", "There are 0 unknown transaction kinds, but that does not mean every transaction was suitable for every check. The 10 exclusions apply to recurrence and duplicate checks; they remain in the cash-movement summary.", ("coverage",)),
    ("Show an overview", "Start by reviewing the USD 9.00 fee total. The cause is not established by the aggregate, so the statement description is the next place to look for context.", ("fee",)),
])
def test_reference_explanations_are_distinct_and_grounded(question, text, ids):
    provider = Mock()
    provider.explain.return_value = draft(text, ids)
    result = answer_question(analyze_transactions(ingest_sample("analysis-demo")), question, provider)
    assert result.explanation is not None
    assert result.explanation.status == "generated"
    assert result.explanation.paragraphs[0].text == text
    assert text not in [fact.text for fact in result.facts]
    provider.select.assert_not_called()


@pytest.mark.parametrize("raw", [
    "not JSON",
    '{"fact_ids":["fee"]}',
    '{"paragraphs":[]}',
    draft("The fee is USD 999.00. Check the statement.") ,
    draft("The fee is USD999.00. Check the statement."),
    draft("The fee is 999. Check the statement."),
    draft("Your fee was charged on 2026-03-06. Check the statement."),
    draft("Your statement includes two fees to review."),
    draft("Your statement includes 3 fees to review."),
    draft("Your statement includes three fees to review."),
    draft("Your fee totals USD 1.00. Check the description."),
    draft("Your fee totals 1 dollar. Check the description."),
    draft("Your fee totals USD 3e1. Check the description."),
    draft("Your fee totals EUR 3.00. Check the statement."),
    draft("Your fee is an overdraft charge. Check the statement."),
    draft("You should buy an investment to cover the fee."),
    draft("Read https://example.com for fee details."),
    draft("Contact reader@example.com for the fee details."),
    draft("Review merchant_private for the fee details."),
    draft("<b>Your statement includes a fee.</b>"),
    draft("Your statement includes a fee to review.", ("invented",)),
    draft("Your statement includes a fee to review.", ("fee", "fee")),
    draft("1 outflow fee transaction(s) total USD 3.00."),
    draft("Too short"),
    draft("x" * 901),
    json.dumps({"paragraphs": [{"text": "Your statement includes a fee to review.", "fact_ids": ["fee"], "extra": "SECRET"}]}),
])
def test_invalid_explanations_fail_closed_without_echoing_output(raw, caplog, capsys):
    provider = Mock()
    provider.explain.return_value = raw
    result = explain_facts("fees", fee(), provider)
    assert result.status == "unavailable"
    assert result.paragraphs == ()
    assert caplog.text == ""
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""


def test_claim_must_be_supported_by_its_own_paragraph_citations():
    facts = (*fee(), FactCard(fact_id="interest", text="1 interest charge totals USD 1.25."))
    provider = Mock()
    provider.explain.return_value = draft("Your fee was USD 1.25. Review its description.")
    assert explain_facts("overview", facts, provider).status == "unavailable"


def test_candidates_cannot_lose_uncertainty_or_conditional_annualization():
    facts = tuple(f for f in build_fact_cards(analyze_transactions(ingest_sample("analysis-demo")))
                  if f.fact_id == "subscription_0")
    provider = Mock()
    provider.explain.return_value = draft("You have a subscription costing USD 12.99. Review it.", ("subscription_0",))
    assert explain_facts("subscriptions", facts, provider).status == "unavailable"
    provider.explain.return_value = draft("Your possible subscription has an annual cost of USD 155.88.", ("subscription_0",))
    assert explain_facts("subscriptions", facts, provider).status == "unavailable"


def test_old_question_records_remain_readable():
    result = QuestionResponse.model_validate({"intent": "fees", "message": "Legacy result",
        "narrative": {"narrative_status": "generated", "highlights": []}, "facts": []})
    assert result.explanation is None


def test_new_result_retains_valid_envelope_for_old_api_readers():
    class OldReader(BaseModel):
        intent: str
        message: str
        narrative: NarrativeResult
        facts: tuple[FactCard, ...]

    provider = Mock()
    provider.explain.return_value = draft("Your fees total USD 9.00, but their cause is not established.")
    result = answer_question(analyze_transactions(ingest_sample("analysis-demo")), "Explain fees", provider)
    old = OldReader.model_validate_json(result.model_dump_json())
    assert old.narrative.narrative_status == "generated"
    assert old.narrative.highlights == old.facts


def test_explanation_transport_contains_only_server_intent_and_safe_facts():
    client = Mock()
    stream = Mock()
    stream.__iter__ = Mock(return_value=iter([
        {"contentBlockDelta": {"delta": {"text": draft("Your fee totals USD 3.00, but its cause is not established.")}}},
        {"messageStop": {"stopReason": "end_turn"}},
    ]))
    client.invoke_harness.return_value = {"stream": stream}
    provider = AgentCoreNarrativeProvider("test-arn", client=client)
    assert explain_facts("fees", fee(), provider).status == "generated"
    request = client.invoke_harness.call_args.kwargs
    payload = json.loads(request["messages"][0]["content"][0]["text"])
    assert set(payload) == {"task", "intent", "facts"}
    assert payload["intent"] == "fees"
    assert payload["task"] == "explain"
    assert request["maxTokens"] == 1024
    assert request["allowedTools"] == ["phineas_no_tools"]
    stream.close.assert_called_once()
