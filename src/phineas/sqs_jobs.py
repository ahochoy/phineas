"""Minimal SQS sender; messages never contain question text or financial data."""

from threading import Lock
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from phineas.jobs import JobMessage, QueueUnavailable


class SqsJobQueue:
    def __init__(self, queue_url: str, region: str = "us-east-2") -> None:
        self._url, self._region = queue_url, region
        self._client: Any = None
        self._lock = Lock()

    def enqueue(self, message: JobMessage) -> None:
        try:
            with self._lock:
                if self._client is None:
                    self._client = boto3.Session().client("sqs", region_name=self._region,
                        config=Config(connect_timeout=5, read_timeout=10,
                            retries={"total_max_attempts": 2, "mode": "standard"}))
            self._client.send_message(QueueUrl=self._url, MessageBody=message.model_dump_json())
        except (BotoCoreError, ClientError):
            # Caller retries with the same request ID: duplicate sends are safe.
            raise QueueUnavailable() from None
