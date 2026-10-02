from datetime import date
from decimal import Decimal
from typing import Annotated, Self

from pydantic import (
  BaseModel,
  ConfigDict,
  Field,
  StringConstraints,
  model_validator,
)

from phineas.domain.enums import (
    AccountType,
    AnalysisFlag,
    ClassificationSource,
    Currency,
    Direction,
    SpendingCategory,
    TransactionKind,
)


NonBlankText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]

NonNegativeMoney = Annotated[
    Decimal,
    Field(ge=Decimal("0"), allow_inf_nan=False),
]

PositiveRowNumber = Annotated[
    int,
    Field(ge=1),
]

ClassificationScore = Annotated[
    float,
    Field(ge=0.0, le=1.0, allow_inf_nan=False),
]


class ParsedTransaction(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
    )

    posted_date: date
    original_description: Annotated[NonBlankText, Field(repr=False)]
    amount: NonNegativeMoney
    direction: Direction
    account_type: AccountType
    currency: Currency
    source_transaction_type: NonBlankText | None = Field(
        default=None,
        repr=False,
    )
    input_row_number: PositiveRowNumber


class SanitizedTransaction(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
    )

    transaction_id: NonBlankText
    posted_date: date
    amount: NonNegativeMoney
    direction: Direction
    account_type: AccountType
    currency: Currency

    transaction_kind: TransactionKind
    kind_source: ClassificationSource
    kind_score: ClassificationScore | None = None

    merchant_id: NonBlankText
    normalized_merchant: NonBlankText = Field(repr=False)

    spending_category: SpendingCategory
    category_source: ClassificationSource
    category_score: ClassificationScore | None = None

    analysis_flags: tuple[AnalysisFlag, ...]

    @model_validator(mode="after")
    def validate_classification_scores(self) -> Self:
        if (
            self.kind_score is not None
            and self.kind_source is not ClassificationSource.LAYA
        ):
            raise ValueError("kind_score requires kind_source=laya")

        if (
            self.category_score is not None
            and self.category_source is not ClassificationSource.LAYA
        ):
            raise ValueError(
                "category_score requires category_source=laya"
            )

        return self
