import importlib.util
import io
import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from botocore.exceptions import ClientError


spec = importlib.util.spec_from_file_location("authorizer_check",
    Path(__file__).resolve().parents[1] / "scripts/test_deployed_authorizer.py")
assert spec is not None and spec.loader is not None
script = importlib.util.module_from_spec(spec)
spec.loader.exec_module(script)


def test_checks_missing_incorrect_and_valid_without_printing_credentials(capsys):
    secret = "a" * 64
    secrets_client = Mock()
    secrets_client.get_secret_value.return_value = {"SecretString": secret}
    client = Mock()
    streams = []

    def invoke(**kwargs):
        supplied = json.loads(kwargs["Payload"])["headers"].get("x-phineas-origin-token")
        stream = io.BytesIO(json.dumps({"isAuthorized": supplied == secret}).encode())
        streams.append(stream)
        return {"StatusCode": 200, "Payload": stream}

    client.invoke.side_effect = invoke
    script.check(client, secrets_client)
    assert client.invoke.call_count == 3
    assert all(stream.closed for stream in streams)
    captured = capsys.readouterr()
    assert secret not in captured.out + captured.err
    assert captured.out.count("passed") == 3
    secrets_client.get_secret_value.assert_called_once_with(
        SecretId="phineas/origin-auth", VersionStage="AWSCURRENT")


@pytest.mark.parametrize("response", [
    {"StatusCode": 200, "Payload": io.BytesIO(b'{"isAuthorized": true}')},
    {"StatusCode": 200, "Payload": io.BytesIO(b'not JSON')},
    {"StatusCode": 200, "FunctionError": "Unhandled", "Payload": io.BytesIO(b'PRIVATE')},
])
def test_unexpected_response_fails_without_echo(response, capsys):
    client = Mock()
    client.invoke.return_value = response
    with pytest.raises(ValueError):
        script.invoke(client, {}, False)
    assert response["Payload"].closed
    assert capsys.readouterr().out == ""


def test_main_never_prints_provider_error(capsys):
    with patch.object(script.boto3, "Session") as session:
        session.return_value.client.side_effect = ClientError(
            {"Error": {"Code": "AccessDeniedException", "Message": "PRIVATE"}}, "Invoke")
        assert script.main() == 1
    captured = capsys.readouterr()
    assert "PRIVATE" not in captured.out + captured.err
