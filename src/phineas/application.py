"""Local application service shared by future CLI, REST, and MCP transports."""

from collections import Counter
from decimal import Decimal
from typing import TextIO

from pydantic import BaseModel, ConfigDict

from phineas.classification.transaction_kinds import RuleBasedTransactionKindClassifier
from phineas.domain.enums import Currency, Direction, TransactionKind
from phineas.ingestion.canonical_csv import parse_canonical_csv
from phineas.ingestion.merchant_registry import MerchantRegistry
from phineas.ingestion.sanitization import TransactionSanitizer


class IngestionSummary(BaseModel):
    """Cash-movement totals, not spending totals or financial findings."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    currency: Currency
    transaction_count: int
    identified_merchant_count: int
    unidentified_merchant_transaction_count: int
    transactions_by_kind: dict[TransactionKind, int]
    total_inflow: Decimal
    total_outflow: Decimal


def summarize_canonical_statement(stream: TextIO) -> IngestionSummary:
    # A fresh registry prevents identity linkage between application calls.
    sanitizer = TransactionSanitizer(
        RuleBasedTransactionKindClassifier(), MerchantRegistry()
    )
    transactions = [
        sanitizer.sanitize(row) for row in parse_canonical_csv(stream)
    ]
    kinds = Counter(transaction.transaction_kind for transaction in transactions)
    return IngestionSummary(
        currency=Currency.USD,
        transaction_count=len(transactions),
        identified_merchant_count=len({
            transaction.merchant_id for transaction in transactions
            if transaction.merchant_id is not None
        }),
        unidentified_merchant_transaction_count=sum(
            transaction.merchant_id is None for transaction in transactions
        ),
        transactions_by_kind={kind: kinds[kind] for kind in TransactionKind},
        total_inflow=sum(
            (transaction.amount for transaction in transactions
             if transaction.direction is Direction.INFLOW), Decimal("0")
        ),
        total_outflow=sum(
            (transaction.amount for transaction in transactions
             if transaction.direction is Direction.OUTFLOW), Decimal("0")
        ),
    )
