"""Atomic, bounded DynamoDB implementation of the session-store interface."""

from collections.abc import Callable
from datetime import datetime, timedelta
from secrets import token_urlsafe
from threading import local
from typing import Any

import boto3
from boto3.dynamodb.conditions import Attr
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from pydantic import ValidationError

from phineas.domain.transactions import SanitizedTransaction
from phineas.sessions import (
    SessionCapacityExceeded, SessionRecord, SessionStoreError, SessionUnavailable, utc_now,
)


class DynamoDBSessionStore:
    MAX_TRANSACTIONS = 99  # Plus metadata: at most 100 atomic transaction actions.

    def __init__(self, table_name: str, region: str = "us-east-2", *,
                 clock: Callable[[], datetime] = utc_now) -> None:
        self._name = table_name
        self._region = region
        self._clock = clock
        # Boto3 resources are not thread-safe. FastAPI sync handlers use a thread
        # pool, so each thread owns a lazily created resource and its client.
        self._local = local()

    def _table(self) -> Any:
        if not hasattr(self._local, "table"):
            resource: Any = boto3.Session().resource("dynamodb", region_name=self._region,
                config=Config(connect_timeout=5, read_timeout=10,
                    retries={"total_max_attempts": 3, "mode": "standard"}))
            self._local.table = resource.Table(self._name)
        return self._local.table

    @staticmethod
    def _key(session_id: str) -> dict[str, str]:
        return {"pk": f"SESSION#{session_id}", "sk": "METADATA"}

    def _metadata(self, session_id: str) -> dict:
        item = self._table().get_item(Key=self._key(session_id), ConsistentRead=True).get("Item")
        now = self._clock().isoformat()
        if item is None or now >= min(item["idle_expires_at"], item["absolute_expires_at"]):
            raise SessionUnavailable()
        return item

    def _rows(self, session_id: str) -> list[dict]:
        paginator = self._table().meta.client.get_paginator("query")
        return [item for page in paginator.paginate(
            TableName=self._name,
            KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
            ExpressionAttributeValues={":pk": f"SESSION#{session_id}", ":prefix": "TRANSACTION#"},
            ConsistentRead=True,
        ) for item in page["Items"]]

    def create(self, sample_id: str, transactions: tuple[SanitizedTransaction, ...]) -> SessionRecord:
        if len(transactions) > self.MAX_TRANSACTIONS:
            raise SessionCapacityExceeded()
        if len({row.transaction_id for row in transactions}) != len(transactions):
            raise SessionCapacityExceeded()
        now = self._clock()
        absolute = now + timedelta(hours=4)
        record = SessionRecord(token_urlsafe(32), now, now, now + timedelta(minutes=30),
            absolute, sample_id, transactions)
        metadata = {**self._key(record.session_id), "schema_version": "1",
            "created_at": now.isoformat(), "last_activity_at": now.isoformat(),
            "idle_expires_at": record.idle_expires_at.isoformat(),
            "absolute_expires_at": absolute.isoformat(), "expires_at": int(absolute.timestamp()),
            "sample_id": sample_id, "transaction_count": len(transactions), "revision": 0}
        items = [metadata] + [{"pk": metadata["pk"], "sk": f"TRANSACTION#{row.transaction_id}",
            "expires_at": metadata["expires_at"], "payload": row.model_dump_json()}
            for row in transactions]
        # Keep each item comfortably below DynamoDB's 400-KB limit.
        sizes = [len(str(item).encode("utf-8")) for item in items]
        if any(size > 350000 for size in sizes) or sum(sizes) > 3500000:
            raise SessionCapacityExceeded()
        try:
            self._table().meta.client.transact_write_items(
                ClientRequestToken=record.session_id[:36],
                TransactItems=[{"Put": {"TableName": self._name, "Item": item,
                    "ConditionExpression": "attribute_not_exists(pk)"}} for item in items])
            return record
        except (BotoCoreError, ClientError):
            raise SessionStoreError() from None

    def access(self, session_id: str) -> SessionRecord:
        try:
            for _ in range(4):
                metadata = self._metadata(session_id)
                rows = self._rows(session_id)
                if len(rows) != metadata["transaction_count"] or metadata["schema_version"] != "1":
                    raise SessionStoreError()
                transactions = tuple(SanitizedTransaction.model_validate_json(row["payload"]) for row in rows)
                now = self._clock()
                absolute = datetime.fromisoformat(metadata["absolute_expires_at"])
                idle = min(now + timedelta(minutes=30), absolute)
                try:
                    self._table().update_item(Key=self._key(session_id),
                        UpdateExpression="SET last_activity_at = :now, idle_expires_at = :idle, revision = :next",
                        ExpressionAttributeValues={":now": now.isoformat(), ":idle": idle.isoformat(),
                            ":next": metadata["revision"] + 1},
                        ConditionExpression=(Attr("revision").eq(metadata["revision"])
                            & Attr("idle_expires_at").gt(now.isoformat())
                            & Attr("absolute_expires_at").gt(now.isoformat())))
                    return SessionRecord(session_id, datetime.fromisoformat(metadata["created_at"]),
                        now, idle, absolute, metadata["sample_id"], transactions)
                except self._table().meta.client.exceptions.ConditionalCheckFailedException:
                    continue
            raise SessionStoreError()
        except SessionUnavailable:
            raise
        except (BotoCoreError, ClientError, ValidationError, KeyError, ValueError):
            raise SessionStoreError() from None
            raise SessionStoreError() from None

    def purge(self, session_id: str) -> None:
        try:
            self._metadata(session_id)
            rows = self._rows(session_id)
            now = self._clock().isoformat()
            self._table().meta.client.transact_write_items(TransactItems=[
                {"Delete": {"TableName": self._name, "Key": self._key(session_id),
                    "ConditionExpression": "idle_expires_at > :now AND absolute_expires_at > :now",
                    "ExpressionAttributeValues": {":now": now}}},
                *[{"Delete": {"TableName": self._name,
                    "Key": {"pk": row["pk"], "sk": row["sk"]}}} for row in rows],
            ])
        except self._table().meta.client.exceptions.TransactionCanceledException:
            # A concurrent purge or expiration may have invalidated metadata.
            self._metadata(session_id)
            raise SessionStoreError() from None
        except (BotoCoreError, ClientError):
            raise SessionStoreError() from None
