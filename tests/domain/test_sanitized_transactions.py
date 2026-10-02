from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from phineas.domain.enums import (
    AccountType,
    AnalysisFlag,
    ClassificationSource,
    Currency,
    Direction,
    SpendingCategory,
    TransactionKind,
)
from phineas.domain.transactions import SanitizedTransaction


def valid_sanitized_data() -> dict[str, object]:
    return {
        "transaction_id": "txn_01",
        "posted_date": date(2026, 1, 2),
        "amount": Decimal("4.75"),
        "direction": Direction.OUTFLOW,
        "account_type": AccountType.CREDIT_CARD,
        "currency": Currency.USD,
        "transaction_kind": TransactionKind.PURCHASE,
        "kind_source": ClassificationSource.RULE,
        "kind_score": None,
        "merchant_id": "merchant_01",
        "normalized_merchant": "Sample Coffee Shop",
        "spending_category": SpendingCategory.DINING,
        "category_source": ClassificationSource.RULE,
        "category_score": None,
        "analysis_flags": (),
    }


def test_accepts_sanitized_transaction() -> None:
    transaction = SanitizedTransaction.model_validate(
        valid_sanitized_data()
    )

    assert transaction.amount == Decimal("4.75")
    assert transaction.analysis_flags == ()


def test_accepts_laya_score_in_valid_range() -> None:
    data = valid_sanitized_data()
    data["kind_source"] = ClassificationSource.LAYA
    data["kind_score"] = 0.92

    transaction = SanitizedTransaction.model_validate(data)

    assert transaction.kind_score == 0.92


def test_rejects_score_for_rule_classification() -> None:
    data = valid_sanitized_data()
    data["kind_score"] = 0.92

    with pytest.raises(
        ValidationError,
        match="kind_score requires kind_source=laya",
    ):
        SanitizedTransaction.model_validate(data)


def test_rejects_score_outside_valid_range() -> None:
    data = valid_sanitized_data()
    data["kind_source"] = ClassificationSource.LAYA
    data["kind_score"] = 1.1

    with pytest.raises(ValidationError):
        SanitizedTransaction.model_validate(data)


@pytest.mark.parametrize(
    "forbidden_field",
    [
        "original_description",
        "source_transaction_type",
        "account_number",
        "filename",
    ],
)
def test_rejects_fields_that_must_not_cross_privacy_boundary(
    forbidden_field: str,
) -> None:
    data = valid_sanitized_data()
    data[forbidden_field] = "sensitive value"

    with pytest.raises(ValidationError):
        SanitizedTransaction.model_validate(data)


def test_normalized_merchant_is_hidden_from_repr() -> None:
    transaction = SanitizedTransaction.model_validate(
        valid_sanitized_data()
    )

    representation = repr(transaction)

    assert "normalized_merchant" not in representation
    assert "Sample Coffee Shop" not in representation


def test_analysis_flags_are_immutable() -> None:
    data = valid_sanitized_data()
    data["analysis_flags"] = (AnalysisFlag.RECURRING_CANDIDATE,)

    transaction = SanitizedTransaction.model_validate(data)

    assert transaction.analysis_flags == (
        AnalysisFlag.RECURRING_CANDIDATE,
    )
