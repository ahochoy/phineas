from uuid import uuid4

from phineas.classification.transaction_kinds import TransactionKindClassifier
from phineas.domain.enums import ClassificationSource, SpendingCategory
from phineas.domain.transactions import ParsedTransaction, SanitizedTransaction
from phineas.ingestion.merchant_extraction import extract_canonical_merchant
from phineas.ingestion.merchant_normalization import normalize_merchant_name
from phineas.ingestion.merchant_registry import MerchantRegistry


class TransactionSanitizer:
    """Convert canonical synthetic transactions into session analytical records."""

    def __init__(
        self,
        kind_classifier: TransactionKindClassifier,
        merchant_registry: MerchantRegistry,
    ) -> None:
        self.kind_classifier = kind_classifier
        self.merchant_registry = merchant_registry

    def sanitize(self, transaction: ParsedTransaction) -> SanitizedTransaction:
        classification = self.kind_classifier.classify(transaction)
        extracted = extract_canonical_merchant(transaction.original_description)
        normalized_merchant = None
        merchant_id = None
        if extracted is not None:
            normalized_merchant = normalize_merchant_name(extracted)
            merchant_id = self.merchant_registry.get_or_create(normalized_merchant)

        return SanitizedTransaction(
            transaction_id=f"txn_{uuid4().hex}",
            posted_date=transaction.posted_date,
            amount=transaction.amount,
            direction=transaction.direction,
            account_type=transaction.account_type,
            currency=transaction.currency,
            transaction_kind=classification.kind,
            kind_source=classification.source,
            kind_score=classification.score,
            merchant_id=merchant_id,
            normalized_merchant=normalized_merchant,
            spending_category=SpendingCategory.UNKNOWN,
            category_source=ClassificationSource.UNKNOWN,
            category_score=None,
            analysis_flags=(),
        )
