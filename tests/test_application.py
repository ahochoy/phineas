from io import StringIO

import pytest

from phineas.application import summarize_canonical_statement
from phineas.domain.enums import TransactionKind
from phineas.ingestion.errors import StatementValidationError


HEADER = "posted_date,description,amount,direction,account_type,currency,transaction_type\n"
ROWS = (
    "2026-01-02,MERCHANT: Sample Coffee | REF: secret-ref,0.10,outflow,checking,USD,purchase\n"
    "2026-01-03,MERCHANT: SAMPLE COFFEE,0.20,outflow,checking,USD,purchase\n"
    "2026-01-04,TRANSFER TO: Jane Doe,10.00,inflow,checking,USD,transfer\n"
)


def test_summary_uses_decimal_totals_and_aggregate_only_output() -> None:
    result = summarize_canonical_statement(StringIO(HEADER + ROWS))
    assert str(result.total_outflow) == "0.30"
    assert str(result.total_inflow) == "10.00"
    assert result.transaction_count == 3
    assert result.identified_merchant_count == 1
    assert result.unidentified_merchant_transaction_count == 1
    assert result.transactions_by_kind[TransactionKind.PURCHASE] == 2
    assert result.transactions_by_kind[TransactionKind.TRANSFER] == 1
    encoded = result.model_dump_json()
    for sensitive in ("Sample", "Jane Doe", "secret-ref", "merchant_id", "txn_"):
        assert sensitive not in encoded


def test_invalid_statement_never_returns_partial_summary() -> None:
    with pytest.raises(StatementValidationError):
        summarize_canonical_statement(StringIO(HEADER + ROWS +
            "invalid,MERCHANT: Coffee,1,outflow,checking,USD,purchase\n"))


def test_cli_returns_json_and_safe_errors(monkeypatch, capsys) -> None:
    from phineas.__main__ import main

    monkeypatch.setattr("sys.argv", ["phineas"])
    monkeypatch.setattr("sys.stdin", StringIO(HEADER + ROWS))
    assert main() == 0
    assert '"transaction_count": 3' in capsys.readouterr().out
    monkeypatch.setattr("sys.stdin", StringIO(HEADER +
        "bad,PRIVATE NAME,1,outflow,checking,USD,purchase\n"))
    assert main() == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "invalid_date" in captured.err
    assert "PRIVATE NAME" not in captured.err
