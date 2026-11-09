from fastapi.testclient import TestClient

from phineas.api import create_app


def test_health_and_sample_discovery() -> None:
    with TestClient(create_app()) as client:
        assert client.get("/health").json() == {"status": "ok"}
        assert set(client.get("/samples").json()) == {"credit-card-demo", "analysis-demo"}


def test_sample_summary_returns_exact_aggregate_values() -> None:
    with TestClient(create_app()) as client:
        response = client.post("/analyses/sample-summary", json={"sample_id": "credit-card-demo"})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["transaction_count"] == 5
    assert body["total_outflow"] == "71.48"
    assert body["total_inflow"] == "105.00"
    assert body["transactions_by_kind"]["payment"] == 1
    assert body["identified_merchant_count"] == 2
    for forbidden in ("Example Streaming", "Sample Grocery", "synthetic-001", "original_description"):
        assert forbidden not in response.text


def test_rejects_unknown_sample_and_additional_input_fields() -> None:
    with TestClient(create_app()) as client:
        response = client.post("/analyses/sample-summary", json={"sample_id": "../../private"})
        assert response.status_code == 404
        assert response.json() == {"detail": "unknown_sample"}
        assert client.post("/analyses/sample-summary", json={
            "sample_id": "credit-card-demo", "csv": "arbitrary contents",
        }).status_code == 422
        assert client.post("/analyses/sample-summary", json={}).status_code == 422


def test_openapi_declares_summary_response_schema() -> None:
    with TestClient(create_app()) as client:
        schema = client.get("/openapi.json").json()
    operation = schema["paths"]["/analyses/sample-summary"]["post"]
    assert operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith("/IngestionSummary")
