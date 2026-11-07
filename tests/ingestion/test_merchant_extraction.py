import pytest

from phineas.ingestion.merchant_extraction import extract_canonical_merchant

@pytest.mark.parametrize(
    "description",
    [
        "TRANSFER TO: Jane Doe | MERCHANT: Sample Coffee",
        "NOT_MERCHANT: Sample Coffee",
        "merchant: Sample Coffee",
    ],
)
def test_rejects_descriptions_without_exact_prefix(description: str) -> None:
    assert extract_canonical_merchant(description) is None

def test_extract_recognized_merchant() -> None:
    recognized_merchant = "MERCHANT: Sample Coffee"
    assert extract_canonical_merchant(recognized_merchant) == "Sample Coffee"

def test_reference_text_excluded() -> None:
    with_reference_text = "MERCHANT: Sample Coffee | REF: 847291"
    assert extract_canonical_merchant(with_reference_text) == "Sample Coffee"

def test_location_text_excluded() -> None:
    with_location_text = "MERCHANT: Sample Coffee | LOCATION: Boston"
    assert extract_canonical_merchant(with_location_text) == "Sample Coffee" 

def test_merchant_name_with_numbers_preserved() -> None:
    with_numbers = "MERCHANT: Studio 54 | REF: 847291"
    assert extract_canonical_merchant(with_numbers) == "Studio 54"

def test_person_transfer_tx_stripped() -> None:
    person_tx = "TRANSFER TO: Jane Doe | REF: 847291"
    assert extract_canonical_merchant(person_tx) is None

def test_unsupported_description_stripped() -> None:
    unsupported_description = "CARD PURCHASE SAMPLE COFFEE"
    assert extract_canonical_merchant(unsupported_description) is None

def test_blank_description_stripped() -> None:
    blank_description = " "
    assert extract_canonical_merchant(blank_description) is None

def test_trims_surrounding_whitespace() -> None:
    assert (
        extract_canonical_merchant("  MERCHANT: Sample Coffee  ")
        == "Sample Coffee"
    )

def test_empty_merchant_section() -> None:
    empty_merchant = "MERCHANT: | REF: 847291"
    assert extract_canonical_merchant(empty_merchant) is None
