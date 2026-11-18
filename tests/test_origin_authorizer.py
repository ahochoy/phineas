import importlib.util
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest
from botocore.exceptions import ClientError


spec = importlib.util.spec_from_file_location("origin_authorizer",
    Path(__file__).resolve().parents[1] / "lambdas/origin_authorizer.py")
assert spec is not None and spec.loader is not None
auth = importlib.util.module_from_spec(spec)
spec.loader.exec_module(auth)
SECRET = "a" * 64


def event(token: Any = SECRET):
    return {"version": "2.0", "type": "REQUEST", "headers": {auth.HEADER: token}}


def test_correct_token_allowed_and_wrong_token_denied():
    reader = Mock(return_value=SECRET)
    authorizer = auth.OriginAuthorizer(reader)
    assert authorizer.authorize(event()) == {"isAuthorized": True}
    assert authorizer.authorize(event("b" * 64)) == {"isAuthorized": False}
    reader.assert_called_once()


@pytest.mark.parametrize("payload", [
    None, [], {}, {"version": "1.0"}, {"version": "2.0", "type": "REQUEST"},
    {"version": "2.0", "type": "REQUEST", "headers": []},
    event(None), event(42), event(""), event("a" * 63), event("a" * 65),
    event(SECRET + "," + SECRET), event(" " + SECRET), event("é" * 64),
])
def test_malformed_or_missing_token_denied_without_secret_read(payload):
    reader = Mock()
    assert auth.OriginAuthorizer(reader).authorize(payload) == {"isAuthorized": False}
    reader.assert_not_called()


@pytest.mark.parametrize("stored", [None, "", "short", b"a" * 64, "é" * 64])
def test_invalid_stored_secret_fails_closed(stored):
    assert auth.OriginAuthorizer(Mock(return_value=stored)).authorize(event()) == {"isAuthorized": False}


def test_rotation_and_refresh_failure_never_use_expired_secret(capsys, caplog):
    clock = Mock(return_value=0)
    error = ClientError({"Error": {"Code": "AccessDeniedException", "Message": "PRIVATE"}}, "GetSecretValue")
    reader = Mock(side_effect=[SECRET, error, "b" * 64])
    authorizer = auth.OriginAuthorizer(reader, clock=clock)
    assert authorizer.authorize(event())["isAuthorized"] is True
    clock.return_value = 59
    assert authorizer.authorize(event())["isAuthorized"] is True
    clock.return_value = 60
    assert authorizer.authorize(event())["isAuthorized"] is False
    assert authorizer.authorize(event("b" * 64))["isAuthorized"] is True
    assert authorizer.authorize(event())["isAuthorized"] is False
    assert caplog.text == ""
    assert capsys.readouterr().out == ""


def test_handler_reads_only_configured_current_secret(monkeypatch):
    client = Mock()
    client.get_secret_value.return_value = {"SecretString": SECRET}
    monkeypatch.setattr(auth, "_client", client)
    monkeypatch.setattr(auth, "_authorizer", None)
    monkeypatch.setenv("PHINEAS_ORIGIN_SECRET_ARN", "test-secret-arn")
    assert auth.lambda_handler(event(), None) == {"isAuthorized": True}
    client.get_secret_value.assert_called_once_with(SecretId="test-secret-arn", VersionStage="AWSCURRENT")


def test_missing_configuration_fails_closed(monkeypatch):
    monkeypatch.delenv("PHINEAS_ORIGIN_SECRET_ARN", raising=False)
    monkeypatch.setattr(auth, "_authorizer", None)
    assert auth.lambda_handler(event(), None) == {"isAuthorized": False}
