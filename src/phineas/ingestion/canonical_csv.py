import csv
from collections.abc import Sequence
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import TextIO

from pydantic import ValidationError

from phineas.domain.enums import AccountType, Currency, Direction
from phineas.domain.transactions import ParsedTransaction
from phineas.ingestion.errors import (
    IngestionErrorCode,
    IngestionIssue,
    StatementValidationError,
    UnsupportedCsvSchemaError,
)

CANONICAL_HEADERS = frozenset(
    {
        "posted_date",
        "description",
        "amount",
        "direction",
        "account_type",
        "currency",
        "transaction_type",
    }
)


def matches_canonical_headers(headers: Sequence[str] | None) -> bool:
    if headers is None:
        return False

    if len(headers) != len(CANONICAL_HEADERS):
        return False

    return frozenset(headers) == CANONICAL_HEADERS


def parse_canonical_csv(stream: TextIO) -> list[ParsedTransaction]:
    reader = csv.DictReader(stream)

    if not matches_canonical_headers(reader.fieldnames):
        raise UnsupportedCsvSchemaError

    transactions: list[ParsedTransaction] = []
    issues: list[IngestionIssue] = []

    for row_number, row in enumerate(reader, start=2):
        transaction, row_issues = _parse_row(row, row_number)

        if row_issues:
            issues.extend(row_issues)
        elif transaction is not None:
            transactions.append(transaction)

    if issues:
        raise StatementValidationError(issues)

    return transactions


def _parse_row(
    row: dict[str | None, str | list[str] | None],
    row_number: int,
) -> tuple[ParsedTransaction | None, list[IngestionIssue]]:
    if None in row or any(value is None for value in row.values()):
        return None, [
            IngestionIssue(
                row_number=row_number,
                field="row",
                code=IngestionErrorCode.MALFORMED_ROW,
            )
        ]

    values = {key: str(value).strip() for key, value in row.items()}
    issues: list[IngestionIssue] = []

    try:
        posted_date = date.fromisoformat(values["posted_date"])
    except ValueError:
        posted_date = None
        issues.append(
            IngestionIssue(
                row_number,
                "posted_date",
                IngestionErrorCode.INVALID_DATE,
            )
        )

    try:
        amount = Decimal(values["amount"])
    except InvalidOperation:
        amount = None
        issues.append(
            IngestionIssue(
                row_number,
                "amount",
                IngestionErrorCode.INVALID_AMOUNT,
            )
        )

    try:
        direction = Direction(values["direction"])
    except ValueError:
        direction = None
        issues.append(
            IngestionIssue(
                row_number,
                "direction",
                IngestionErrorCode.INVALID_DIRECTION,
            )
        )

    try:
        account_type = AccountType(values["account_type"])
    except ValueError:
        account_type = None
        issues.append(
            IngestionIssue(
                row_number,
                "account_type",
                IngestionErrorCode.INVALID_ACCOUNT_TYPE,
            )
        )

    try:
        currency = Currency(values["currency"])
    except ValueError:
        currency = None
        issues.append(
            IngestionIssue(
                row_number,
                "currency",
                IngestionErrorCode.UNSUPPORTED_CURRENCY,
            )
        )

    if issues:
        return None, issues

    assert posted_date is not None
    assert amount is not None
    assert direction is not None
    assert account_type is not None
    assert currency is not None

    transaction_type = values["transaction_type"] or None

    try:
        transaction = ParsedTransaction(
            posted_date=posted_date,
            original_description=values["description"],
            amount=amount,
            direction=direction,
            account_type=account_type,
            currency=currency,
            source_transaction_type=transaction_type,
            input_row_number=row_number,
        )
    except ValidationError as error:
        return None, _translate_validation_errors(error, row_number)

    return transaction, []


def _translate_validation_errors(
    error: ValidationError,
    row_number: int,
) -> list[IngestionIssue]:
    field_names = {
        "original_description": "description",
        "source_transaction_type": "transaction_type",
    }

    issues = []

    for detail in error.errors(include_input=False):
        domain_field = str(detail["loc"][0])
        source_field = field_names.get(domain_field, domain_field)

        if domain_field == "amount":
            code = IngestionErrorCode.INVALID_AMOUNT
        elif detail["type"] == "string_too_short":
            code = IngestionErrorCode.BLANK_REQUIRED_VALUE
        else:
            code = IngestionErrorCode.INVALID_VALUE

        issues.append(IngestionIssue(row_number, source_field, code))

    return issues
