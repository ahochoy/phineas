from dataclasses import dataclass
from enum import StrEnum
from collections.abc import Sequence


class IngestionErrorCode(StrEnum):
    INVALID_DATE = "invalid_date"
    INVALID_AMOUNT = "invalid_amount"
    INVALID_DIRECTION = "invalid_direction"
    INVALID_ACCOUNT_TYPE = "invalid_account_type"
    UNSUPPORTED_CURRENCY = "unsupported_currency"
    BLANK_REQUIRED_VALUE = "blank_required_value"
    MALFORMED_ROW = "malformed_row"
    INVALID_VALUE = "invalid_value"


@dataclass(frozen=True, slots=True)
class IngestionIssue:
    row_number: int
    field: str
    code: IngestionErrorCode


class UnsupportedCsvSchemaError(ValueError):
    def __init__(self) -> None:
        super().__init__("unsupported_csv_schema")


class StatementValidationError(ValueError):
    def __init__(self, issues: Sequence[IngestionIssue]) -> None:
        self.issues = tuple(issues)
        super().__init__(
            f"statement_validation_failed: {len(self.issues)} issue(s)"
        )
