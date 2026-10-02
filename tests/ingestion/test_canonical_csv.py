from phineas.ingestion.canonical_csv import matches_canonical_headers
from io import StringIO
from decimal import Decimal

import pytest

from phineas.domain.enums import Direction
from phineas.ingestion.canonical_csv import parse_canonical_csv
from phineas.ingestion.errors import (
    IngestionIssue,
    IngestionErrorCode,
    StatementValidationError,
    UnsupportedCsvSchemaError,
)

def canonical_headers() -> list[str]:
    return [
        "posted_date",
        "description",
        "amount",
        "direction",
        "account_type",
        "currency",
        "transaction_type",
    ]


def test_matches_complete_canonical_headers() -> None:
    assert matches_canonical_headers(canonical_headers())


def test_header_order_does_not_matter() -> None:
    assert matches_canonical_headers(list(reversed(canonical_headers())))


def test_missing_header_does_not_match() -> None:
    headers = canonical_headers()
    headers.remove("direction")

    assert not matches_canonical_headers(headers)


def test_unexpected_header_does_not_match() -> None:
    headers = [*canonical_headers(), "account_number"]

    assert not matches_canonical_headers(headers)


def test_duplicate_header_does_not_match() -> None:
    headers = canonical_headers()
    headers[-1] = "currency"

    assert not matches_canonical_headers(headers)


def test_missing_header_row_does_not_match() -> None:
    assert not matches_canonical_headers(None)


def test_parses_valid_rows_into_domain_transactions() -> None:
    stream = StringIO(
        "posted_date,description,amount,direction,account_type,currency,"
        "transaction_type\n"
        "2026-01-02,Coffee Shop,4.75,outflow,credit_card,USD,purchase\n"
        "2026-01-03,Payroll,1000.00,inflow,checking,USD,\n"
    )

    transactions = parse_canonical_csv(stream)

    assert len(transactions) == 2
    assert transactions[0].amount == Decimal("4.75")
    assert transactions[0].direction is Direction.OUTFLOW
    assert transactions[1].source_transaction_type is None
    assert transactions[1].input_row_number == 3


def test_collects_errors_and_rejects_the_whole_statement() -> None:
    stream = StringIO(
        "posted_date,description,amount,direction,account_type,currency,"
        "transaction_type\n"
        "not-a-date,Coffee Shop,4.75,outflow,credit_card,USD,purchase\n"
        "2026-01-03,Payroll,1000.00,sideways,checking,USD,income\n"
    )

    with pytest.raises(StatementValidationError) as captured:
        parse_canonical_csv(stream)

        assert captured.value.issues == (
        IngestionIssue(
            2,
            "posted_date",
            IngestionErrorCode.INVALID_DATE,
        ),
        IngestionIssue(
            3,
            "direction",
            IngestionErrorCode.INVALID_DIRECTION,
        ),
    )


def test_errors_do_not_expose_source_values() -> None:
    secret_description = "PRIVATE MEDICAL MERCHANT"
    stream = StringIO(
        "posted_date,description,amount,direction,account_type,currency,"
        "transaction_type\n"
        f"not-a-date,{secret_description},4.75,outflow,credit_card,USD,purchase\n"
    )

    with pytest.raises(StatementValidationError) as captured:
        parse_canonical_csv(stream)

    assert secret_description not in str(captured.value)
    assert secret_description not in repr(captured.value.issues)


def test_parser_rejects_unsupported_schema() -> None:
    stream = StringIO("date,merchant,total\n2026-01-02,Coffee Shop,4.75\n")

    with pytest.raises(
        UnsupportedCsvSchemaError,
        match="unsupported_csv_schema",
    ):
        parse_canonical_csv(stream)
