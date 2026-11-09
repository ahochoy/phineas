"""Deterministic policy v1: monthly recurrence, charges, and possible duplicates."""

from collections import defaultdict
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from phineas.application import IngestionSummary, summarize_transactions
from phineas.domain.enums import Direction, TransactionKind
from phineas.domain.transactions import SanitizedTransaction


class Finding(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    # Evidence stays internal; serialization is the aggregate-only projection.
    evidence_transaction_ids: tuple[str, ...] = Field(exclude=True, repr=False)


class SubscriptionCandidate(Finding):
    merchant_id: str
    cadence: Literal["monthly"] = "monthly"
    observed_charge_count: int
    typical_amount: Decimal
    annualized_cost: Decimal
    first_observed_date: date
    last_observed_date: date


class ChargeTotal(Finding):
    charge_kind: Literal["fee", "interest"]
    transaction_count: int
    total_amount: Decimal


class PossibleDuplicate(Finding):
    merchant_id: str
    amount: Decimal
    posted_date: date
    transaction_count: int
    reason_code: Literal["same_merchant_amount_date"] = "same_merchant_amount_date"


class AnalysisResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    analysis_version: Literal["0.1.0"] = "0.1.0"
    summary: IngestionSummary
    subscription_candidates: tuple[SubscriptionCandidate, ...]
    charges: tuple[ChargeTotal, ...]
    possible_duplicates: tuple[PossibleDuplicate, ...]
    unknown_kind_count: int
    purchase_analysis_excluded_count: int


def analyze_transactions(transactions: Sequence[SanitizedTransaction]) -> AnalysisResult:
    purchases: dict[str, list[SanitizedTransaction]] = defaultdict(list)
    duplicate_groups: dict[tuple[str, date, Decimal], list[SanitizedTransaction]] = defaultdict(list)
    for transaction in transactions:
        if (transaction.transaction_kind is TransactionKind.PURCHASE
                and transaction.direction is Direction.OUTFLOW
                and transaction.amount > 0 and transaction.merchant_id is not None):
            purchases[transaction.merchant_id].append(transaction)
            duplicate_groups[(transaction.merchant_id, transaction.posted_date, transaction.amount)].append(transaction)

    subscriptions = []
    for merchant_id, rows in sorted(purchases.items()):
        rows = sorted(rows, key=lambda row: (row.posted_date, row.transaction_id))
        if len(rows) < 3 or len({row.amount for row in rows}) != 1:
            continue
        gaps = [(right.posted_date - left.posted_date).days
                for left, right in zip(rows, rows[1:])]
        if not all(28 <= gap <= 31 for gap in gaps):
            continue
        subscriptions.append(SubscriptionCandidate(
            merchant_id=merchant_id, observed_charge_count=len(rows),
            typical_amount=rows[0].amount,
            annualized_cost=rows[0].amount * Decimal(12),
            first_observed_date=rows[0].posted_date, last_observed_date=rows[-1].posted_date,
            evidence_transaction_ids=tuple(row.transaction_id for row in rows),
        ))

    charges = []
    for kind in (TransactionKind.FEE, TransactionKind.INTEREST):
        rows = [row for row in transactions if row.transaction_kind is kind
                and row.direction is Direction.OUTFLOW]
        if rows:
            charges.append(ChargeTotal(
                charge_kind="fee" if kind is TransactionKind.FEE else "interest",
                transaction_count=len(rows),
                total_amount=sum((row.amount for row in rows), Decimal("0")),
                evidence_transaction_ids=tuple(sorted(row.transaction_id for row in rows)),
            ))

    duplicates = [PossibleDuplicate(
        merchant_id=merchant_id, posted_date=posted_date, amount=amount,
        transaction_count=len(rows),
        evidence_transaction_ids=tuple(sorted(row.transaction_id for row in rows)),
    ) for (merchant_id, posted_date, amount), rows in sorted(duplicate_groups.items())
        if len(rows) > 1]

    return AnalysisResult(
        summary=summarize_transactions(transactions),
        subscription_candidates=tuple(subscriptions), charges=tuple(charges),
        possible_duplicates=tuple(duplicates),
        unknown_kind_count=sum(row.transaction_kind is TransactionKind.UNKNOWN for row in transactions),
        purchase_analysis_excluded_count=len(transactions) - sum(map(len, purchases.values())),
    )
