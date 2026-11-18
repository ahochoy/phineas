import csv
import json
from collections import Counter
from datetime import date
from calendar import monthrange
from decimal import Decimal
from io import StringIO
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from phineas.api import create_app
from phineas.narratives import FactCard, explain_facts
from phineas.analysis import analyze_transactions
from phineas.questions import classify_question
from phineas.samples import _SAMPLES, ingest_sample, list_sample_ids, preview_sample
from phineas.sessions import SessionStore


@pytest.mark.parametrize("sample_id", list_sample_ids())
def test_preview_contains_every_original_csv_cell_in_order(sample_id):
    expected = list(csv.reader(StringIO(_SAMPLES[sample_id])))
    preview = preview_sample(sample_id)
    assert list(preview.columns) == expected[0]
    assert [list(row) for row in preview.rows] == expected[1:]
    assert preview.synthetic is True
    assert preview.sample_id == sample_id


def test_preview_is_fixture_only_and_creates_no_session_or_model_call():
    store = Mock(spec=SessionStore)
    provider = Mock()
    with TestClient(create_app(store=store, narrative_provider=provider)) as client:
        response = client.get("/samples/analysis-demo/preview")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert len(response.json()["rows"]) == 50
        assert response.json()["rows"][0][1] == "MERCHANT: Example Streaming"
        assert client.get("/samples/private-session/preview").status_code == 404
        assert client.get("/samples/terraform.tfvars/preview").status_code == 404
        assert client.get("/sessions/analysis-demo/preview").status_code == 404
    store.assert_not_called()
    assert store.mock_calls == []
    assert provider.mock_calls == []


def test_unknown_preview_identifier_is_not_a_path_or_file_read():
    with pytest.raises(ValueError, match="^unknown_sample$"):
        preview_sample("../../terraform.tfvars")


def test_everyday_sample_has_fifty_chronological_records_across_three_months():
    preview = preview_sample("analysis-demo")
    dates = [date.fromisoformat(row[0]) for row in preview.rows]
    assert len(dates) == 50
    assert dates == sorted(dates)
    assert {value.month for value in dates} == {1, 2, 3}
    assert dates[0] == date(2026, 1, 2)
    assert dates[-1] == date(2026, 3, 31)
    assert sum(count > 1 for count in Counter(dates).values()) >= 3
    result = analyze_transactions(ingest_sample("analysis-demo"))
    assert result.summary.transaction_count == len(preview.rows)
    assert result.summary.total_outflow == Decimal("1736.17")
    assert result.summary.total_inflow == Decimal("1642.00")
    assert len(result.subscription_candidates) == 1
    assert len(result.possible_duplicates) == 1
    assert {charge.charge_kind for charge in result.charges} == {"fee", "interest"}


def test_everyday_has_monthly_payments_fees_and_month_end_interest():
    preview = preview_sample("analysis-demo")
    for kind in ("payment", "fee", "interest"):
        rows = [row for row in preview.rows if row[-1] == kind]
        assert len(rows) == 3
        assert Counter(date.fromisoformat(row[0]).month for row in rows) == {1: 1, 2: 1, 3: 1}
        assert all(row[3] == ("inflow" if kind == "payment" else "outflow") for row in rows)
    for row in preview.rows:
        if row[-1] == "interest":
            posted = date.fromisoformat(row[0])
            assert posted.day == monthrange(posted.year, posted.month)[1]
    fees = [row for row in preview.rows if row[-1] == "fee"]
    assert {row[2] for row in fees} == {"3.00"}


def test_simpler_sample_has_ten_records_without_planted_charge_findings():
    preview = preview_sample("credit-card-demo")
    assert len(preview.rows) == 10
    dates = [date.fromisoformat(row[0]) for row in preview.rows]
    assert dates == sorted(dates)
    result = analyze_transactions(ingest_sample("credit-card-demo"))
    assert result.summary.transaction_count == 10
    assert result.summary.total_outflow == Decimal("165.68")
    assert result.summary.total_inflow == Decimal("105.00")
    assert result.charges == result.subscription_candidates == result.possible_duplicates == ()


def test_readable_synthetic_merchants_remain_out_of_analysis_projection():
    for sample_id in list_sample_ids():
        encoded = analyze_transactions(ingest_sample(sample_id)).model_dump_json()
        preview = preview_sample(sample_id)
        for row in preview.rows:
            if row[1].startswith("MERCHANT: "):
                name = row[1].removeprefix("MERCHANT: ").split(" | ")[0]
                assert name not in encoded


def test_review_regressions_have_valid_corrected_examples():
    # These are human-review regressions, not an automatic semantic judge.
    path = Path(__file__).resolve().parents[1] / "evaluations/explanation-regressions.json"
    for case in json.loads(path.read_text()):
        assert case["expected_review"] == "reject"
        assert case["failure_reasons"]
        # Keep observed response regressions tied to their original evidence,
        # even when the current product samples gain transactions or fees.
        facts = tuple(FactCard.model_validate(fact) for fact in case["source_facts"])
        assert len(facts) == len(case["fact_ids"])
        provider = Mock()
        provider.explain.return_value = json.dumps({"paragraphs": [{
            "text": case["acceptable_example"], "fact_ids": case["fact_ids"],
        }]})
        result = explain_facts(classify_question(case["question"]).value, facts, provider)
        assert result.status == "generated"


def test_same_origin_preview_route_matches_direct_api():
    from phineas.web import create_web_app
    with TestClient(create_web_app(create_app())) as client:
        response = client.get("/api/samples/credit-card-demo/preview")
        assert response.status_code == 200
        assert len(response.json()["rows"]) == 10
        assert response.headers["cache-control"] == "no-store"
        assert client.get("/").status_code == 200
