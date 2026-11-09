"""Model-selected highlights rendered only from deterministic fact cards."""

import json
from collections.abc import Sequence
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
