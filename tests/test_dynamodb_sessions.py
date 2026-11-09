from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from typing import Any

import boto3
import pytest
from fastapi.testclient import TestClient
from moto import mock_aws

from phineas.api import create_app
from phineas.dynamodb_sessions import DynamoDBSessionStore
from phineas.samples import ingest_sample
from phineas.sessions import SessionCapacityExceeded, SessionUnavailable, SessionStoreError


@pytest.fixture
def database(monkeypatch):
    # Ensure emulator tests never resolve developer credentials or real endpoints.
    for key in ("AWS_PROFILE", "AWS_DEFAULT_PROFILE"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    with mock_aws():
        resource: Any = boto3.resource("dynamodb", region_name="us-east-2")
        table = resource.create_table(
            TableName="test-sessions", BillingMode="PAY_PER_REQUEST",
            KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}, {"AttributeName": "sk", "KeyType": "RANGE"}],
            AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}, {"AttributeName": "sk", "AttributeType": "S"}])
        yield table


def test_round_trip_across_store_instances_and_atomic_purge(database) -> None:
    store = DynamoDBSessionStore("test-sessions")
    rows = ingest_sample("analysis-demo")
    record = store.create("analysis-demo", rows)
    other_process = DynamoDBSessionStore("test-sessions")
    restored = other_process.access(record.session_id)
    assert sorted(restored.transactions, key=lambda row: row.transaction_id) == sorted(rows, key=lambda row: row.transaction_id)
    items = database.scan()["Items"]
    assert len(items) == len(rows) + 1
    assert all(isinstance(int(item["expires_at"]), int) for item in items)
    encoded = str(items)
    assert "original_description" not in encoded
    assert "synthetic-001" not in encoded
    other_process.purge(record.session_id)
    assert database.scan()["Items"] == []
    with pytest.raises(SessionUnavailable):
        store.access(record.session_id)


def test_idle_expiration_works_without_ttl_deletion(database) -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    store = DynamoDBSessionStore("test-sessions", clock=lambda: now)
    record = store.create("sample", ())
    now += timedelta(minutes=30)
    with pytest.raises(SessionUnavailable):
        store.access(record.session_id)
    assert database.scan()["Count"] == 1
    with pytest.raises(SessionUnavailable):
        store.purge(record.session_id)


def test_refresh_does_not_extend_absolute_deadline(database) -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    store = DynamoDBSessionStore("test-sessions", clock=lambda: now)
    record = store.create("sample", ())
    refreshed = record
    for _ in range(8):
        now += timedelta(minutes=29)
        refreshed = store.access(record.session_id)
    assert refreshed.absolute_expires_at == record.absolute_expires_at
    assert refreshed.idle_expires_at == record.absolute_expires_at
    now = record.absolute_expires_at
    with pytest.raises(SessionUnavailable):
        store.access(record.session_id)


def test_oversized_statement_is_rejected_before_writes(database) -> None:
    store = DynamoDBSessionStore("test-sessions")
    row = ingest_sample("analysis-demo")[0]
    rows = tuple(row.model_copy(update={"transaction_id": f"txn_{i}"}) for i in range(100))
    with pytest.raises(SessionCapacityExceeded):
        store.create("sample", rows)
    assert database.scan()["Count"] == 0


def test_missing_and_malformed_ids_are_indistinguishable(database) -> None:
    with TestClient(create_app(DynamoDBSessionStore("test-sessions"))) as client:
        for key in ("unknown", "!!!"):
            response = client.get(f"/sessions/{key}/summary")
            assert response.status_code == 404
            assert response.json() == {"detail": "session_unavailable"}


def test_access_cannot_resurrect_metadata_deleted_during_read(database) -> None:
    store = DynamoDBSessionStore("test-sessions")
    record = store.create("sample", ())
    original = store._rows

    def interrupted(session_id):
        rows = original(session_id)
        database.delete_item(Key=store._key(session_id))
        return rows

    with patch.object(store, "_rows", side_effect=interrupted):
        with pytest.raises(SessionUnavailable):
            store.access(record.session_id)
    assert database.scan()["Count"] == 0


def test_http_session_can_be_read_by_another_app(database) -> None:
    with TestClient(create_app(DynamoDBSessionStore("test-sessions"))) as first:
        response = first.post("/sessions", json={"sample_id": "analysis-demo"})
        assert response.status_code == 201
        key = response.json()["session_id"]
    with TestClient(create_app(DynamoDBSessionStore("test-sessions"))) as second:
        assert second.get(f"/sessions/{key}/analysis").status_code == 200
        assert second.delete(f"/sessions/{key}").status_code == 204


def test_failed_atomic_creation_does_not_publish_partial_rows(database) -> None:
    store = DynamoDBSessionStore("test-sessions")
    rows = ingest_sample("analysis-demo")
    with patch("phineas.dynamodb_sessions.token_urlsafe", return_value="same-session-id"):
        record = store.create("first", rows)
        different = (rows[0].model_copy(update={"transaction_id": "different"}),)
        with pytest.raises(SessionStoreError):
            store.create("second", different)
    restored = store.access(record.session_id)
    assert restored.sample_id == "first"
    assert len(restored.transactions) == len(rows)
    assert database.scan()["Count"] == len(rows) + 1


def test_query_pagination_reads_all_records(database) -> None:
    store = DynamoDBSessionStore("test-sessions")
    record = store.create("analysis-demo", ingest_sample("analysis-demo"))
    real = store._table().meta.client.get_paginator("query")

    class SmallPages:
        def paginate(self, **kwargs):
            return real.paginate(**kwargs, PaginationConfig={"PageSize": 2})

    with patch.object(store._table().meta.client, "get_paginator", return_value=SmallPages()):
        restored = store.access(record.session_id)
        assert len(restored.transactions) == 8
        store.purge(record.session_id)
    assert database.scan()["Count"] == 0
