import pytest

from phineas.ingestion.merchant_registry import MerchantRegistry


def test_repeated_lookup_returns_same_id() -> None:
    registry = MerchantRegistry()

    test_merchant = "NORMALIZED MERCHANT"

    merchant_id_create = registry.get_or_create(test_merchant)
    merchant_id_get = registry.get_or_create(test_merchant)

    assert merchant_id_create == merchant_id_get
    assert merchant_id_create.startswith("merchant_")
    assert test_merchant not in merchant_id_create


def test_different_names_receive_different_ids() -> None:
    registry = MerchantRegistry()

    merchant_a = "MERCHANT NAME A"
    merchant_b = "MERCHANT NAME B"

    merchant_a_id = registry.get_or_create(merchant_a)
    merchant_b_id = registry.get_or_create(merchant_b)

    assert merchant_a_id != merchant_b_id


def test_separate_registries_assign_different_ids_to_same_name() -> None:
    registry_a = MerchantRegistry()
    registry_b = MerchantRegistry()

    merchant = "NORMALIZED MERCHANT"

    id_from_registry_a = registry_a.get_or_create(merchant)
    id_from_registry_b = registry_b.get_or_create(merchant)

    assert id_from_registry_a != id_from_registry_b

@pytest.mark.parametrize("merchant", ["", "   ", "\t"])
def test_blank_whitespace_names_raise_error(merchant: str) -> None:
    registry = MerchantRegistry()

    with pytest.raises(ValueError):
        registry.get_or_create(merchant)

