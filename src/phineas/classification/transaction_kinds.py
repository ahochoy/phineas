from dataclasses import dataclass
from typing import Protocol

from phineas.domain.enums import (
    ClassificationSource,
    Direction,
    TransactionKind,
)
from phineas.domain.transactions import ParsedTransaction


@dataclass(frozen=True, slots=True)
class KindClassification:
    kind: TransactionKind
    source: ClassificationSource
    score: float | None = None


class TransactionKindClassifier(Protocol):
    def classify(
        self,
        transaction: ParsedTransaction,
    ) -> KindClassification: ...


_SOURCE_TYPE_TO_KIND = {
    kind.value: kind
    for kind in TransactionKind
    if kind is not TransactionKind.UNKNOWN
}

_REQUIRED_DIRECTIONS = {
    TransactionKind.PURCHASE: Direction.OUTFLOW,
    TransactionKind.REFUND: Direction.INFLOW,
    TransactionKind.INCOME: Direction.INFLOW,
    TransactionKind.FEE: Direction.OUTFLOW,
    TransactionKind.CASH_WITHDRAWAL: Direction.OUTFLOW,
}


class RuleBasedTransactionKindClassifier:
    def classify(
        self,
        transaction: ParsedTransaction,
    ) -> KindClassification:
        source_type = transaction.source_transaction_type

        if source_type is None:
            return self._unknown()

        normalized_source_type = "_".join(
            source_type.casefold().replace("-", " ").split()
        )

        kind = _SOURCE_TYPE_TO_KIND.get(normalized_source_type)

        if kind is None:
            return self._unknown()

        required_direction = _REQUIRED_DIRECTIONS.get(kind)

        if (
            required_direction is not None
            and transaction.direction is not required_direction
        ):
            return self._unknown()

        return KindClassification(
            kind=kind,
            source=ClassificationSource.SOURCE,
        )

    @staticmethod
    def _unknown() -> KindClassification:
        return KindClassification(
            kind=TransactionKind.UNKNOWN,
            source=ClassificationSource.UNKNOWN,
        )
