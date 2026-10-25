import pytest

from phineas.ingestion.merchant_registry import MerchantRegistry
from phineas.ingestion.merchant_normalization import normalize_merchant_name


@pytest.mark.parametrize(
    "input_string, expected",
    [
        ("  SAMPLE COFFEE  ","sample coffee"),     
        ("Sample   Coffee","sample coffee"),     
        ("Sample\tCoffee","sample coffee"),     
        ("Studio 54","studio 54"),     
        ("Sample-Mart","sample-mart"),     
        ("Sample Mart","sample mart"),
        ("Straße Market", "strasse market"),     
    ]
)
def test_parameterized_normalized_merchant_names(
    input_string: str, 
    expected: str,
) -> None:
    assert normalize_merchant_name(input_string) == expected
  
def test_empty_input_throws_error() -> None:
    with pytest.raises(ValueError):
        normalize_merchant_name("")

def test_whitespace_input_throws_error() -> None:
    with pytest.raises(ValueError):
        normalize_merchant_name("\n\n")

def test_returns_same_value_when_repeated() -> None:
    merchant_name = "ACME Incorporated"
    first_normal = normalize_merchant_name(merchant_name)
    assert normalize_merchant_name(first_normal) == first_normal

def test_preserve_difference_with_hyphenation() -> None:
    with_hyphen = normalize_merchant_name("Sample-Mart")
    without_hyphen = normalize_merchant_name("Sample Mart")

    assert with_hyphen != without_hyphen

def test_merchant_registry_normalize_integration() -> None:
    registry = MerchantRegistry()

    first_id = registry.get_or_create(
        normalize_merchant_name("  Sample   Coffee ")
    )
    second_id = registry.get_or_create(
        normalize_merchant_name("SAMPLE COFFEE")
    )

    assert first_id == second_id
