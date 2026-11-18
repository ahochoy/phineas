"""Exact-phrase intent baseline. User text never reaches the model."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from phineas.analysis import AnalysisResult
from phineas.narratives import (
    ExplanationResult, FactCard, NarrativeProvider, NarrativeResult, build_fact_cards, explain_facts,
)


class QuestionIntent(StrEnum):
    OVERVIEW = "overview"
    SUBSCRIPTIONS = "subscriptions"
    FEES = "fees"
    INTEREST = "interest"
    DUPLICATES = "duplicates"
    COVERAGE = "coverage"
    UNSUPPORTED = "unsupported"


SUGGESTED_QUESTIONS = {
    "Show an overview": QuestionIntent.OVERVIEW,
    "Show subscriptions": QuestionIntent.SUBSCRIPTIONS,
    "Explain fees": QuestionIntent.FEES,
    "Explain interest": QuestionIntent.INTEREST,
    "Show possible duplicates": QuestionIntent.DUPLICATES,
    "Explain classification coverage": QuestionIntent.COVERAGE,
}
_PHRASES = {text.casefold(): intent for text, intent in SUGGESTED_QUESTIONS.items()}


class QuestionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=200, repr=False)


class QuestionResponse(BaseModel):
    intent: QuestionIntent
    message: str
    narrative: NarrativeResult
    # Full relevant deterministic facts remain available even if model selection fails.
    facts: tuple[FactCard, ...] = ()
    # Additive field: older short-lived stored jobs remain readable.
    explanation: ExplanationResult | None = None


def classify_question(question: str) -> QuestionIntent:
    normalized = " ".join(question.casefold().split()).rstrip("?.!")
    return _PHRASES.get(normalized, QuestionIntent.UNSUPPORTED)


def answer_question(analysis: AnalysisResult, question: str,
                    provider: NarrativeProvider | None) -> QuestionResponse:
    return answer_intent(analysis, classify_question(question), provider)


def answer_intent(analysis: AnalysisResult, intent: QuestionIntent,
                  provider: NarrativeProvider | None) -> QuestionResponse:
    if intent is QuestionIntent.UNSUPPORTED:
        return QuestionResponse(intent=intent,
            message="I can help with the suggested analysis questions. Please select one.",
            narrative=NarrativeResult(narrative_status="skipped"),
            explanation=ExplanationResult(status="skipped"))
    all_facts = build_fact_cards(analysis)
    prefixes = {
        QuestionIntent.SUBSCRIPTIONS: "subscription_",
        QuestionIntent.DUPLICATES: "duplicate_",
    }
    if intent is QuestionIntent.OVERVIEW:
        facts = all_facts
    elif intent in prefixes:
        facts = tuple(fact for fact in all_facts if fact.fact_id.startswith(prefixes[intent]))
    else:
        fact_id = "fee" if intent is QuestionIntent.FEES else intent.value
        facts = tuple(fact for fact in all_facts if fact.fact_id == fact_id)
    if not facts:
        return QuestionResponse(intent=intent,
            message="No matching findings were detected by the current analysis policy.",
            narrative=NarrativeResult(narrative_status="skipped"),
            explanation=ExplanationResult(status="skipped"))
    explanation = explain_facts(intent.value, facts, provider)
    cited = {key for paragraph in explanation.paragraphs for key in paragraph.fact_ids}
    # Preserve the v1 narrative envelope for old readers during deployment.
    narrative = NarrativeResult(narrative_status=explanation.status,
        highlights=tuple(fact for fact in facts if fact.fact_id in cited))
    return QuestionResponse(intent=intent, message="Review the supporting findings and their limitations.",
        facts=facts, narrative=narrative, explanation=explanation)
