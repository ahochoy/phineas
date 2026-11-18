"""Deterministic fact cards, legacy highlight selection, and bounded explanations."""

import json
import re
from collections.abc import Sequence
from decimal import Decimal
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from phineas.analysis import AnalysisResult


class FactCard(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    fact_id: str
    merchant_id: str | None = None
    text: str


class HighlightSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    fact_ids: list[str] = Field(min_length=1, max_length=5)


class NarrativeResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    narrative_status: Literal["generated", "unavailable", "skipped"]
    mode: Literal["selected_facts_v1"] = "selected_facts_v1"
    highlights: tuple[FactCard, ...] = ()


class NarrativeUnavailable(Exception):
    """Safe failure marker; never carries provider output or financial input."""


class NarrativeProvider(Protocol):
    def select(self, facts: Sequence[FactCard]) -> str: ...

    def explain(self, intent: str, facts: Sequence[FactCard]) -> str: ...


class ExplanationParagraph(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, str_strip_whitespace=True)
    text: str = Field(min_length=20, max_length=900, repr=False)
    fact_ids: tuple[str, ...] = Field(min_length=1, max_length=5)


class ExplanationDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    paragraphs: tuple[ExplanationParagraph, ...] = Field(min_length=1, max_length=3)


class ExplanationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    status: Literal["generated", "unavailable", "skipped"]
    mode: Literal["grounded_explanation_v1"] = "grounded_explanation_v1"
    paragraphs: tuple[ExplanationParagraph, ...] = ()


_NUMBER = re.compile(r"[+-]?\d+(?:,\d{3})*(?:\.\d+)?")
_MONEY = re.compile(r"(?:\bUSD\s*|\$\s*)([+-]?\d+(?:,\d{3})*(?:\.\d+)?)", re.I)
_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_NUMBER_WORDS = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4,
                 "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
                 "ten": 10, "eleven": 11, "twelve": 12}


def _numbers(text: str) -> set[Decimal]:
    # Dates are checked as complete dates, not reusable year/month/day numbers.
    text = _DATE.sub("", text)
    return {Decimal(value.replace(",", "")) for value in _NUMBER.findall(text)}


def _money(text: str) -> set[Decimal]:
    return {Decimal(value.replace(",", "")) for value in _MONEY.findall(text)}


class ExplanationRejected(NarrativeUnavailable):
    """Carries only a server-owned rejection code, never model output."""

    def __init__(self, reason: str) -> None:
        super().__init__()
        self.reason = reason


def validate_explanation(raw: str, facts: Sequence[FactCard]) -> ExplanationDraft:
    """Shared checks for application acceptance and developer diagnostics."""
    try:
        draft = ExplanationDraft.model_validate_json(raw)
    except ValidationError:
        raise ExplanationRejected("json_or_schema") from None
    lookup = {fact.fact_id: fact.text for fact in facts}
    for paragraph in draft.paragraphs:
        if len(set(paragraph.fact_ids)) != len(paragraph.fact_ids):
            raise ExplanationRejected("duplicate_citation")
        if any(key not in lookup for key in paragraph.fact_ids):
            raise ExplanationRejected("unknown_citation")
        source = " ".join(lookup[key] for key in paragraph.fact_ids)
        text = paragraph.text
        if text in (lookup[key] for key in paragraph.fact_ids):
            raise ExplanationRejected("copied_finding")
        if not _numbers(text).issubset(_numbers(source)):
            raise ExplanationRejected("unsupported_number")
        if not _money(text).issubset(_money(source)):
            raise ExplanationRejected("unsupported_money")
        source_counts = _numbers(_MONEY.sub("", source))
        if not _numbers(_MONEY.sub("", text)).issubset(source_counts):
            raise ExplanationRejected("unsupported_count")
        if not set(_DATE.findall(text)).issubset(_DATE.findall(source)):
            raise ExplanationRejected("unsupported_date")
        # A sentence-opening discourse marker is not a financial count. Keep
        # this exception narrow; other occurrences of "one" remain checked.
        count_text = re.sub(r"(^|[.!?]\s+)one other thing\s*:",
                            r"\1Another point:", text, flags=re.I)
        for word in re.findall(r"\b[a-z]+\b", count_text.casefold()):
            if word in _NUMBER_WORDS and Decimal(_NUMBER_WORDS[word]) not in source_counts:
                raise ExplanationRejected("unsupported_number_word")
        if re.search(r"\b\d+(?:\.\d+)?e[+-]?\d+\b|\bdollars?\b", text, re.I):
            # Require USD/$ prefixes and reject scientific notation.
            raise ExplanationRejected("ambiguous_money_format")
        if re.search(r"https?://|www\.|\b\S+@\S+|merchant_|<[^>]+>|[€£¥%]|\b(?:EUR|GBP|CAD|AUD|JPY|CHF|CNY|INR)\b", text, re.I):
            raise ExplanationRejected("privacy_or_format")
        # Conservative rejection, not a comprehensive semantic classifier.
        for claim in re.findall(r"\b(?:overdraft|late payment|insufficient funds|fraud|buy|sell|invest|investment|tax|legal|guaranteed)\b", text, re.I):
            if claim.casefold() not in source.casefold():
                raise ExplanationRejected("unsupported_claim_term")
        if any(key.startswith(("subscription_", "duplicate_")) for key in paragraph.fact_ids):
            if not re.search(r"\b(possible|candidate|may|might|could|uncertain)\b|not confirmed", text, re.I):
                raise ExplanationRejected("missing_uncertainty")
        if "if it continues" in source and re.search(r"\bannual\w*\b", text, re.I):
            if not re.search(r"\b(if|assuming|continues|continue|conditional|estimate|estimated)\b", text, re.I):
                raise ExplanationRejected("missing_annual_condition")
    return draft


def explain_facts(intent: str, facts: Sequence[FactCard],
                  provider: NarrativeProvider | None) -> ExplanationResult:
    if not facts or provider is None:
        return ExplanationResult(status="skipped")
    if len(facts) > 100:
        return ExplanationResult(status="unavailable")
    try:
        draft = validate_explanation(provider.explain(intent, facts), facts)
        return ExplanationResult(status="generated", paragraphs=draft.paragraphs)
    except (NarrativeUnavailable, ValidationError):
        # These checks are bounded safeguards, NOT semantic entailment proof.
        # No rejected model output, validation payload, or SDK detail is logged.
        return ExplanationResult(status="unavailable")


def build_fact_cards(analysis: AnalysisResult) -> tuple[FactCard, ...]:
    """Explicit model-input allowlist, independent of report serialization."""
    facts = []
    for index, finding in enumerate(analysis.subscription_candidates):
        facts.append(FactCard(
            fact_id=f"subscription_{index}", merchant_id=finding.merchant_id,
            text=(f"A possible monthly recurring charge of USD {finding.typical_amount} "
                  f"was observed {finding.observed_charge_count} times. Its estimated "
                  f"annualized cost is USD {finding.annualized_cost} if it continues. "
                  "This is a candidate, not a confirmed subscription."),
        ))
    for finding in analysis.charges:
        facts.append(FactCard(
            fact_id=finding.charge_kind,
            text=(f"{finding.transaction_count} outflow {finding.charge_kind} "
                  f"transaction(s) total USD {finding.total_amount}."),
        ))
    for index, finding in enumerate(analysis.possible_duplicates):
        facts.append(FactCard(
            fact_id=f"duplicate_{index}", merchant_id=finding.merchant_id,
            text=(f"{finding.transaction_count} purchases of USD {finding.amount} "
                  f"share a merchant and posting date ({finding.posted_date}). "
                  "These are possible duplicates; legitimate repeat purchases are possible."),
        ))
    facts.append(FactCard(
        fact_id="coverage",
        text=(f"{analysis.unknown_kind_count} transactions have unknown kinds. "
              f"{analysis.purchase_analysis_excluded_count} transactions were excluded "
              "from purchase recurrence and duplicate checks by analysis policy. "
              "Exclusion does not remove transactions from the cash-movement summary."),
    ))
    return tuple(facts)


def generate_highlights(analysis: AnalysisResult, provider: NarrativeProvider | None) -> NarrativeResult:
    return select_highlights(build_fact_cards(analysis), provider)


def select_highlights(facts: Sequence[FactCard], provider: NarrativeProvider | None) -> NarrativeResult:
    if provider is None:
        return NarrativeResult(narrative_status="skipped")
    # Fail before dispatch if a statement would exceed this first bounded slice.
    if len(facts) > 100:
        return NarrativeResult(narrative_status="unavailable")
    try:
        raw = provider.select(facts)
        selection = HighlightSelection.model_validate_json(raw)
        lookup = {fact.fact_id: fact for fact in facts}
        if len(selection.fact_ids) != len(set(selection.fact_ids)):
            raise NarrativeUnavailable()
        if any(key not in lookup for key in selection.fact_ids):
            raise NarrativeUnavailable()
        return NarrativeResult(narrative_status="generated",
            highlights=tuple(lookup[key] for key in selection.fact_ids))
    except (NarrativeUnavailable, ValidationError):
        return NarrativeResult(narrative_status="unavailable")


def encode_facts(facts: Sequence[FactCard]) -> str:
    return json.dumps({"facts": [fact.model_dump() for fact in facts]}, ensure_ascii=True)
