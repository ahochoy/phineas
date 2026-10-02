from datetime import date
from decimal import Decimal

from phineas.classification.transaction_kinds import (
    RuleBasedTransactionKindClassifier,
    TransactionKindClassifier,
)
from phineas.domain.enums import (
    AccountType,
    ClassificationSource,
    Currency,
    Direction,
    TransactionKind,
)
from phineas.domain.transactions import ParsedTransaction


def parsed_transaction(
    *,
    direction: Direction = Direction.OUTFLOW,
    source_type: str | None = "purchase",
) -> ParsedTransaction:
    return ParsedTransaction(
        posted_date=date(2026, 1, 2),
        original_description="Synthetic Merchant",
        amount=Decimal("10.00"),
        direction=direction,
        account_type=AccountType.CREDIT_CARD,
        currency=Currency.USD,
        source_transaction_type=source_type,
        input_row_number=2,
    )


def test_classifies_known_source_transaction_type() -> None:
    classifier = RuleBasedTransactionKindClassifier()

    result = classifier.classify(parsed_transaction())

    assert result.kind is TransactionKind.PURCHASE
    assert result.source is ClassificationSource.SOURCE
    assert result.score is None


def test_normalizes_source_type_formatting() -> None:
    classifier = RuleBasedTransactionKindClassifier()

    result = classifier.classify(
        parsed_transaction(source_type="  CASH-WITHDRAWAL  ")
    )

    assert result.kind is TransactionKind.CASH_WITHDRAWAL


def test_missing_source_type_remains_unknown() -> None:
    classifier = RuleBasedTransactionKindClassifier()

    result = classifier.classify(
        parsed_transaction(source_type=None)
    )

    assert result.kind is TransactionKind.UNKNOWN
    assert result.source is ClassificationSource.UNKNOWN


def test_unrecognized_source_type_remains_unknown() -> None:
    classifier = RuleBasedTransactionKindClassifier()

    result = classifier.classify(
        parsed_transaction(source_type="bank_specific_code")
    )

    assert result.kind is TransactionKind.UNKNOWN
    assert result.source is ClassificationSource.UNKNOWN


def test_contradictory_direction_remains_unknown() -> None:
    classifier = RuleBasedTransactionKindClassifier()

    result = classifier.classify(
        parsed_transaction(
            direction=Direction.OUTFLOW,
            source_type="income",
        )
    )

    assert result.kind is TransactionKind.UNKNOWN
    assert result.source is ClassificationSource.UNKNOWN


def test_rule_classifier_satisfies_protocol() -> None:
    classifier: TransactionKindClassifier = (
        RuleBasedTransactionKindClassifier()
    )

    result = classifier.classify(parsed_transaction())

    assert result.kind is TransactionKind.PURCHASE
