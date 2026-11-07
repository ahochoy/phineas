from io import StringIO

import pytest
from pydantic import ValidationError

from phineas.classification.transaction_kinds import (
    KindClassification,
    RuleBasedTransactionKindClassifier,
)
from phineas.domain.enums import ClassificationSource, SpendingCategory, TransactionKind
from phineas.domain.transactions import ParsedTransaction, SanitizedTransaction
from phineas.ingestion.canonical_csv import parse_canonical_csv
from phineas.ingestion.merchant_registry import MerchantRegistry
from phineas.ingestion.sanitization import TransactionSanitizer


def rows() -> list[ParsedTransaction]:
    return parse_canonical_csv(StringIO(
        "posted_date,description,amount,direction,account_type,currency,transaction_type\n"
        "2026-01-02,MERCHANT: Sample Coffee | REF: 847291,4.75,outflow,credit_card,USD,purchase\n"
        "2026-01-03,MERCHANT: SAMPLE   COFFEE,4.75,outflow,credit_card,USD,purchase\n"
        "2026-01-04,TRANSFER TO: Jane Doe,10.00,outflow,checking,USD,transfer\n"
    ))


def sanitizer() -> TransactionSanitizer:
    return TransactionSanitizer(RuleBasedTransactionKindClassifier(), MerchantRegistry())


def test_csv_to_sanitized_records_preserves_all_valid_transactions() -> None:
    service = sanitizer()
    sources = rows()
    results = [service.sanitize(row) for row in sources]
    assert len(results) == 3
    for source, result in zip(sources, results, strict=True):
        assert result.amount == source.amount
        assert result.posted_date == source.posted_date
        assert result.direction is source.direction
        assert result.currency is source.currency
        assert result.account_type is source.account_type
        assert result.spending_category is SpendingCategory.UNKNOWN
        assert result.category_source is ClassificationSource.UNKNOWN
        assert result.category_score is None
        assert result.analysis_flags == ()
    assert results[0].normalized_merchant == "sample coffee"
    assert results[0].merchant_id is not None
    assert results[0].merchant_id == results[1].merchant_id
    assert results[0].transaction_id != results[1].transaction_id
    assert results[0].transaction_kind is TransactionKind.PURCHASE
    assert results[0].kind_source is ClassificationSource.SOURCE
    assert results[0].kind_score is None
    assert results[2].transaction_kind is TransactionKind.TRANSFER
    assert results[2].merchant_id is None
    assert results[2].normalized_merchant is None


def test_output_excludes_source_only_fields_and_reference_text() -> None:
    for source in rows():
        result = sanitizer().sanitize(source)
        assert {"original_description", "source_transaction_type", "input_row_number"}.isdisjoint(result.model_dump())
        encoded = result.model_dump_json()
        assert "847291" not in encoded
        assert "Jane Doe" not in encoded
        assert "MERCHANT:" not in encoded


def test_merchant_identity_is_isolated_between_sessions() -> None:
    source = rows()[0]
    assert sanitizer().sanitize(source).merchant_id != sanitizer().sanitize(source).merchant_id


def test_uses_injected_classifier() -> None:
    class FakeClassifier:
        def classify(self, transaction: ParsedTransaction) -> KindClassification:
            return KindClassification(TransactionKind.UNKNOWN, ClassificationSource.LAYA, 0.4)

    result = TransactionSanitizer(FakeClassifier(), MerchantRegistry()).sanitize(rows()[0])
    assert result.transaction_kind is TransactionKind.UNKNOWN
    assert result.kind_source is ClassificationSource.LAYA
    assert result.kind_score == 0.4


@pytest.mark.parametrize("field", ["merchant_id", "normalized_merchant"])
def test_model_rejects_partial_merchant_identity(field: str) -> None:
    data = sanitizer().sanitize(rows()[0]).model_dump()
    data[field] = None
    with pytest.raises(ValidationError, match="must be provided together"):
        SanitizedTransaction.model_validate(data)
