from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from phineas.domain.enums import AccountType, Currency, Direction
from phineas.domain.transactions import ParsedTransaction


def valid_transaction_data() -> dict[str, object]:
    return {
        "posted_date": date(2026, 2, 14),
        "original_description": "  SAMPLE COFFEE SHOP  ",
        "amount": Decimal("19.99"),
        "direction": Direction.OUTFLOW,
        "account_type": AccountType.CREDIT_CARD,
        "currency": Currency.USD,
        "source_transaction_type": "purchase",
        "input_row_number": 2,
    }


def test_accepts_normalized_transaction() -> None:
    transaction = ParsedTransaction.model_validate(valid_transaction_data())

    assert transaction.amount == Decimal("19.99")
    assert transaction.original_description == "SAMPLE COFFEE SHOP"


def test_rejects_negative_amount() -> None:
    data = valid_transaction_data()
    data["amount"] = Decimal("-19.99")

    with pytest.raises(ValidationError):
        ParsedTransaction.model_validate(data)


def test_rejects_float_amount_in_strict_mode() -> None:
    data = valid_transaction_data()
    data["amount"] = 19.99

    with pytest.raises(ValidationError):
        ParsedTransaction.model_validate(data)


def test_rejects_blank_required_description() -> None:
    data = valid_transaction_data()
    data["original_description"] = "   "

    with pytest.raises(ValidationError):
        ParsedTransaction.model_validate(data)


def test_rejects_unexpected_fields() -> None:
    data = valid_transaction_data()
    data["account_number"] = "123456789"

    with pytest.raises(ValidationError):
        ParsedTransaction.model_validate(data)


def test_sensitive_text_is_hidden_from_repr() -> None:
    transaction = ParsedTransaction.model_validate(valid_transaction_data())

    representation = repr(transaction)

    assert "original_description" not in representation
    assert "source_transaction_type" not in representation
    assert "SAMPLE COFFEE SHOP" not in representation
    assert "purchase" not in representation
