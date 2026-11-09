from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from phineas.analysis import analyze_transactions
from phineas.api import create_app
from phineas.domain.enums import Direction, TransactionKind
from phineas.domain.transactions import SanitizedTransaction
from phineas.samples import ingest_sample
from phineas.sessions import InMemorySessionStore


def test_planted_findings_and_private_evidence() -> None:
    rows = ingest_sample("analysis-demo")
    result = analyze_transactions(rows)
    subscription, = result.subscription_candidates
    assert subscription.observed_charge_count == 3
    assert subscription.annualized_cost == Decimal("155.88")
    assert len(subscription.evidence_transaction_ids) == 3
    duplicate, = result.possible_duplicates
    assert duplicate.amount == Decimal("20.00")
    assert duplicate.transaction_count == 2
    assert [(charge.charge_kind, charge.total_amount) for charge in result.charges] == [
        ("fee", Decimal("3.00")), ("interest", Decimal("1.25"))]
    assert result.purchase_analysis_excluded_count == 3
    encoded = result.model_dump_json()
    for value in ("Example Streaming", "Sample Shop", "evidence_transaction_ids", "txn_", "original_description"):
        assert value not in encoded


def test_clean_controls_and_empty_statement() -> None:
    for rows in ((), ingest_sample("credit-card-demo")):
        result = analyze_transactions(rows)
        assert result.subscription_candidates == ()
        assert result.possible_duplicates == ()
        assert result.charges == ()


@pytest.mark.parametrize("changes", [
    {"amount": Decimal("13.99")},
    {"posted_date": date(2026, 3, 20)},
    {"transaction_kind": TransactionKind.REFUND, "direction": Direction.INFLOW},
    {"merchant_id": None, "normalized_merchant": None},
])
def test_incomplete_or_inconsistent_monthly_evidence_is_not_recurring(changes: dict[str, object]) -> None:
    rows = list(ingest_sample("analysis-demo")[:3])
    data = rows[2].model_dump()
    data.update(changes)
    rows[2] = SanitizedTransaction.model_validate(data)
    assert analyze_transactions(rows).subscription_candidates == ()


def test_income_interest_and_unidentified_purchases_do_not_create_false_findings() -> None:
    rows = ingest_sample("analysis-demo")
    earned = rows[6].model_copy(update={"direction": Direction.INFLOW})
    unidentified = rows[3].model_copy(update={"merchant_id": None, "normalized_merchant": None})
    result = analyze_transactions((earned, unidentified, unidentified))
    assert result.charges == ()
    assert result.possible_duplicates == ()


def test_analysis_is_independent_of_input_order() -> None:
    rows = ingest_sample("analysis-demo")
    assert analyze_transactions(rows) == analyze_transactions(tuple(reversed(rows)))


def test_analysis_endpoint_lifecycle_and_projection() -> None:
    store = InMemorySessionStore()
    with TestClient(create_app(store)) as client:
        created = client.post("/sessions", json={"sample_id": "analysis-demo"})
        key = created.json()["session_id"]
        response = client.get(f"/sessions/{key}/analysis")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert len(response.json()["subscription_candidates"]) == 1
        assert "evidence_transaction_ids" not in response.text
        assert key not in response.text
        client.delete(f"/sessions/{key}")
        assert client.get(f"/sessions/{key}/analysis").json() == {"detail": "session_unavailable"}
