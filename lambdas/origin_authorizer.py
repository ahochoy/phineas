"""Standalone HTTP API v2 authorizer; package this file only, not the app."""

from collections.abc import Callable
import hmac
import os
import re
from time import monotonic
from typing import Any

import boto3
from botocore.config import Config


HEADER = "x-phineas-origin-token"
TOKEN = re.compile(r"[A-Za-z0-9_-]{64}", re.ASCII)


class OriginAuthorizer:
    def __init__(self, load_secret: Callable[[], str], *, clock: Callable[[], float] = monotonic) -> None:
        self._load_secret = load_secret
        self._clock = clock
        self._secret: str | None = None
        self._expires = 0.0

    def authorize(self, event: Any) -> dict[str, bool]:
        try:
            if not isinstance(event, dict) or event.get("version") != "2.0" or event.get("type") != "REQUEST":
                return {"isAuthorized": False}
            headers = event.get("headers")
            if not isinstance(headers, dict):
                return {"isAuthorized": False}
            # HTTP API v2 lowercases headers and joins duplicate values with
            # commas. Exact shape/length validation rejects combined values.
            supplied = headers.get(HEADER)
            if not isinstance(supplied, str) or TOKEN.fullmatch(supplied) is None:
                return {"isAuthorized": False}
            if self._secret is None or self._clock() >= self._expires:
                # Expired credentials must not survive a failed refresh.
                self._secret = None
                secret = self._load_secret()
                if not isinstance(secret, str) or TOKEN.fullmatch(secret) is None:
                    return {"isAuthorized": False}
                self._secret = secret
                self._expires = self._clock() + 60
            return {"isAuthorized": hmac.compare_digest(supplied, self._secret)}
        except Exception:
            # Authorization is fail-closed even for unexpected dependency
            # failures. Never log event, headers, secret, or exception details.
            self._secret = None
            self._expires = 0.0
            return {"isAuthorized": False}


_client: Any = None
_authorizer: OriginAuthorizer | None = None


def _load_secret() -> str:
    global _client
    arn = os.environ["PHINEAS_ORIGIN_SECRET_ARN"]
    if _client is None:
        _client = boto3.client("secretsmanager", config=Config(
            connect_timeout=2, read_timeout=3,
            retries={"total_max_attempts": 1, "mode": "standard"}))
    return _client.get_secret_value(SecretId=arn, VersionStage="AWSCURRENT")["SecretString"]


def lambda_handler(event: Any, context: Any) -> dict[str, bool]:
    global _authorizer
    if _authorizer is None:
        _authorizer = OriginAuthorizer(_load_secret)
    return _authorizer.authorize(event)
