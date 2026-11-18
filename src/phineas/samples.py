"""Approved synthetic fixtures; identifiers never become filesystem paths."""

from io import StringIO
import csv

from pydantic import BaseModel, ConfigDict

from phineas.application import IngestionSummary, ingest_canonical_statement, summarize_transactions
from phineas.domain.transactions import SanitizedTransaction


_SAMPLES = {
    "analysis-demo": (
        "posted_date,description,amount,direction,account_type,currency,transaction_type\n"
        "2026-01-02,MERCHANT: Example Streaming,12.99,outflow,credit_card,USD,purchase\n"
        "2026-01-02,MERCHANT: Corner Coffee,5.25,outflow,credit_card,USD,purchase\n"
        "2026-01-04,MERCHANT: Harbor Grocery,62.40,outflow,credit_card,USD,purchase\n"
        "2026-01-06,MERCHANT: Metro Transit,25.00,outflow,credit_card,USD,purchase\n"
        "2026-01-08,MERCHANT: Neighborhood Pharmacy,14.80,outflow,credit_card,USD,purchase\n"
        "2026-01-11,MERCHANT: City Books,28.50,outflow,credit_card,USD,purchase\n"
        "2026-01-14,MERCHANT: Local Diner,32.60,outflow,credit_card,USD,purchase\n"
        "2026-01-16,MERCHANT: Harbor Grocery,87.15,outflow,credit_card,USD,purchase\n"
        "2026-01-18,MERCHANT: Example Mobile,45.00,outflow,credit_card,USD,purchase\n"
        "2026-01-20,MERCHANT: Fuel Stop,41.30,outflow,credit_card,USD,purchase\n"
        "2026-01-22,MERCHANT: City Utilities,85.10,outflow,credit_card,USD,purchase\n"
        "2026-01-24,MERCHANT: Home Supply,56.90,outflow,credit_card,USD,purchase\n"
        "2026-01-30,MERCHANT: Harbor Grocery,48.35,outflow,credit_card,USD,purchase\n"
        "2026-01-31,Card payment,650.00,inflow,credit_card,USD,payment\n"
        "2026-01-31,Monthly fee,3.00,outflow,credit_card,USD,fee\n"
        "2026-01-31,Interest charge,2.85,outflow,credit_card,USD,interest\n"
        "2026-02-02,MERCHANT: Example Streaming,12.99,outflow,credit_card,USD,purchase\n"
        "2026-02-03,MERCHANT: Metro Transit,30.00,outflow,credit_card,USD,purchase\n"
        "2026-02-05,MERCHANT: Harbor Grocery,73.60,outflow,credit_card,USD,purchase\n"
        "2026-02-08,MERCHANT: Local Diner,39.20,outflow,credit_card,USD,purchase\n"
        "2026-02-10,MERCHANT: Neighborhood Pharmacy,22.45,outflow,credit_card,USD,purchase\n"
        "2026-02-12,MERCHANT: Trail Outdoor,118.00,outflow,credit_card,USD,purchase\n"
        "2026-02-14,MERCHANT: City Books,16.95,outflow,credit_card,USD,purchase\n"
        "2026-02-17,MERCHANT: Harbor Grocery,94.30,outflow,credit_card,USD,purchase\n"
        "2026-02-18,MERCHANT: Example Mobile,47.00,outflow,credit_card,USD,purchase\n"
        "2026-02-20,MERCHANT: Fuel Stop,44.70,outflow,credit_card,USD,purchase\n"
        "2026-02-22,MERCHANT: City Utilities,92.40,outflow,credit_card,USD,purchase\n"
        "2026-02-27,MERCHANT: Home Supply,36.80,outflow,credit_card,USD,purchase\n"
        "2026-02-28,Card payment,850.00,inflow,credit_card,USD,payment\n"
        "2026-02-28,Monthly fee,3.00,outflow,credit_card,USD,fee\n"
        "2026-02-28,Interest charge,3.40,outflow,credit_card,USD,interest\n"
        "2026-03-02,MERCHANT: Example Streaming,12.99,outflow,credit_card,USD,purchase\n"
        "2026-03-03,MERCHANT: Harbor Grocery,81.25,outflow,credit_card,USD,purchase\n"
        "2026-03-03,MERCHANT: Corner Coffee,5.40,outflow,credit_card,USD,purchase\n"
        "2026-03-05,MERCHANT: Sample Shop,20.00,outflow,credit_card,USD,purchase\n"
        "2026-03-05,MERCHANT: Sample Shop,20.00,outflow,credit_card,USD,purchase\n"
        "2026-03-07,Card payment,100.00,inflow,credit_card,USD,payment\n"
        "2026-03-08,MERCHANT: Metro Transit,25.00,outflow,credit_card,USD,purchase\n"
        "2026-03-10,MERCHANT: Local Diner,27.80,outflow,credit_card,USD,purchase\n"
        "2026-03-12,MERCHANT: Neighborhood Pharmacy,18.65,outflow,credit_card,USD,purchase\n"
        "2026-03-14,MERCHANT: City Books,34.00,outflow,credit_card,USD,purchase\n"
        "2026-03-16,MERCHANT: Harbor Grocery,67.90,outflow,credit_card,USD,purchase\n"
        "2026-03-18,MERCHANT: Example Mobile,46.00,outflow,credit_card,USD,purchase\n"
        "2026-03-20,MERCHANT: Fuel Stop,39.50,outflow,credit_card,USD,purchase\n"
        "2026-03-22,MERCHANT: City Utilities,88.70,outflow,credit_card,USD,purchase\n"
        "2026-03-24,MERCHANT: Trail Outdoor,42.00,inflow,credit_card,USD,refund\n"
        "2026-03-27,MERCHANT: Corner Coffee,6.35,outflow,credit_card,USD,purchase\n"
        "2026-03-31,MERCHANT: Home Supply,52.40,outflow,credit_card,USD,purchase\n"
        "2026-03-31,Monthly fee,3.00,outflow,credit_card,USD,fee\n"
        "2026-03-31,Interest charge,1.25,outflow,credit_card,USD,interest\n"
    ),
    "credit-card-demo": (
        "posted_date,description,amount,direction,account_type,currency,transaction_type\n"
        "2026-01-02,MERCHANT: Example Streaming | REF: synthetic-001,12.99,outflow,credit_card,USD,purchase\n"
        "2026-02-02,MERCHANT: Example Streaming | REF: synthetic-002,12.99,outflow,credit_card,USD,purchase\n"
        "2026-02-05,MERCHANT: Sample Grocery,45.50,outflow,credit_card,USD,purchase\n"
        "2026-02-05,MERCHANT: Corner Coffee,5.25,outflow,credit_card,USD,purchase\n"
        "2026-02-06,Card payment,100.00,inflow,credit_card,USD,payment\n"
        "2026-02-07,Refund,5.00,inflow,credit_card,USD,refund\n"
        "2026-02-08,MERCHANT: Metro Transit,18.00,outflow,credit_card,USD,purchase\n"
        "2026-02-09,MERCHANT: City Books,24.95,outflow,credit_card,USD,purchase\n"
        "2026-02-10,MERCHANT: Neighborhood Pharmacy,11.80,outflow,credit_card,USD,purchase\n"
        "2026-02-12,MERCHANT: Sample Grocery,34.20,outflow,credit_card,USD,purchase\n"
    ),
}


def list_sample_ids() -> tuple[str, ...]:
    return tuple(_SAMPLES)


class SamplePreview(BaseModel):
    """Public view of approved synthetic source fixtures only, never sessions."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    sample_id: str
    synthetic: bool = True
    columns: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]


def preview_sample(sample_id: str) -> SamplePreview:
    # Lookup is the security boundary: no paths, arbitrary CSV, uploads, or
    # stored session records can reach this public fixture-only endpoint.
    try:
        contents = _SAMPLES[sample_id]
    except KeyError:
        raise ValueError("unknown_sample") from None
    records = list(csv.reader(StringIO(contents)))
    return SamplePreview(sample_id=sample_id, columns=tuple(records[0]),
                         rows=tuple(tuple(row) for row in records[1:]))


def summarize_sample(sample_id: str) -> IngestionSummary:
    return summarize_transactions(ingest_sample(sample_id))


def ingest_sample(sample_id: str) -> tuple[SanitizedTransaction, ...]:
    try:
        contents = _SAMPLES[sample_id]
    except KeyError:
        raise ValueError("unknown_sample") from None
    return ingest_canonical_statement(StringIO(contents))
