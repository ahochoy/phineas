from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from phineas.api import create_app
from phineas.sessions import InMemorySessionStore


class Clock:
    now = datetime(2026, 1, 1, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


def test_create_access_and_purge_session() -> None:
    with TestClient(create_app()) as client:
        response = client.post("/sessions", json={"sample_id": "credit-card-demo"})
        assert response.status_code == 201
        key = response.json()["session_id"]
        assert len(key) >= 43
        summary = client.get(f"/sessions/{key}/summary")
        assert summary.status_code == 200
        assert summary.json()["transaction_count"] == 5
        assert key not in summary.text
        assert client.delete(f"/sessions/{key}").status_code == 204
        missing = client.get(f"/sessions/{key}/summary")
        assert missing.status_code == 404
        assert missing.json() == {"detail": "session_unavailable"}
        assert missing.headers["cache-control"] == "no-store"
        assert client.delete(f"/sessions/{key}").status_code == 404


def test_idle_expiration_refresh_and_absolute_cap() -> None:
    clock = Clock()
    store = InMemorySessionStore(clock)
    record = store.create("synthetic", ())
    clock.now += timedelta(minutes=29)
    accessed = store.access(record.session_id)
    assert accessed.idle_expires_at == clock.now + timedelta(minutes=30)
    assert accessed.absolute_expires_at == record.absolute_expires_at
    # Keep active until 3h52, then the idle deadline is capped at four hours.
    for _ in range(7):
        clock.now += timedelta(minutes=29)
        accessed = store.access(record.session_id)
    assert accessed.idle_expires_at == record.absolute_expires_at
    clock.now = record.absolute_expires_at
    with TestClient(create_app(store)) as client:
        assert client.get(f"/sessions/{record.session_id}/summary").status_code == 404


def test_exact_idle_deadline_is_unavailable_like_unknown_or_malformed_id() -> None:
    clock = Clock()
    store = InMemorySessionStore(clock)
    record = store.create("synthetic", ())
    clock.now += timedelta(minutes=30)
    with TestClient(create_app(store)) as client:
        responses = [client.get(f"/sessions/{key}/summary")
            for key in (record.session_id, "unknown", "!!!")]
        assert all(response.status_code == 404 for response in responses)
        assert all(response.json() == {"detail": "session_unavailable"} for response in responses)


def test_apps_are_isolated_and_invalid_creation_is_rejected() -> None:
    with TestClient(create_app()) as first, TestClient(create_app()) as second:
        key = first.post("/sessions", json={"sample_id": "credit-card-demo"}).json()["session_id"]
        assert second.get(f"/sessions/{key}/summary").status_code == 404
        assert first.post("/sessions", json={"sample_id": "invalid"}).status_code == 404
        assert first.post("/sessions", json={"sample_id": "credit-card-demo", "csv": "raw"}).status_code == 422
