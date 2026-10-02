from datetime import date
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from phineas.domain.enums import AccountType, Currency, Direction


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
