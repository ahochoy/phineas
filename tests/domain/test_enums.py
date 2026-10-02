import pytest

from phineas.domain.enums import Currency, Direction, TransactionKind


def test_direction_values_match_the_data_contract() -> None:
    assert Direction.INFLOW == "inflow"
    assert Direction.OUTFLOW == "outflow"


def test_currency_is_usd_only() -> None:
    assert list(Currency) == [Currency.USD]
    assert Currency.USD == "USD"


def test_unknown_is_an_explicit_transaction_kind() -> None:
    assert TransactionKind.UNKNOWN == "unknown"


def test_unsupported_transaction_kind_is_rejected() -> None:
    with pytest.raises(ValueError):
        TransactionKind("crypto_purchase")
