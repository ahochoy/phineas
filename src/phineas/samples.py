"""Approved synthetic fixtures; identifiers never become filesystem paths."""

from io import StringIO

from phineas.application import IngestionSummary, ingest_canonical_statement, summarize_transactions
from phineas.domain.transactions import SanitizedTransaction


_SAMPLES = {
    "credit-card-demo": (
        "posted_date,description,amount,direction,account_type,currency,transaction_type\n"
        "2026-01-02,MERCHANT: Example Streaming | REF: synthetic-001,12.99,outflow,credit_card,USD,purchase\n"
        "2026-02-02,MERCHANT: Example Streaming | REF: synthetic-002,12.99,outflow,credit_card,USD,purchase\n"
        "2026-02-05,MERCHANT: Sample Grocery,45.50,outflow,credit_card,USD,purchase\n"
        "2026-02-06,Card payment,100.00,inflow,credit_card,USD,payment\n"
        "2026-02-07,Refund,5.00,inflow,credit_card,USD,refund\n"
    ),
}


def list_sample_ids() -> tuple[str, ...]:
    return tuple(_SAMPLES)


def summarize_sample(sample_id: str) -> IngestionSummary:
    return summarize_transactions(ingest_sample(sample_id))


def ingest_sample(sample_id: str) -> tuple[SanitizedTransaction, ...]:
    try:
        contents = _SAMPLES[sample_id]
    except KeyError:
        raise ValueError("unknown_sample") from None
    return ingest_canonical_statement(StringIO(contents))
