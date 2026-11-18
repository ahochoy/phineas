import importlib.util
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from botocore.exceptions import ClientError


spec = importlib.util.spec_from_file_location("bootstrap",
    Path(__file__).resolve().parents[1] / "scripts/initialize_origin_secret.py")
assert spec is not None and spec.loader is not None
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)
ARN = "arn:aws:secretsmanager:us-east-2:927161114143:secret:phineas/origin-auth-example"


def test_initializes_empty_secret_without_printing_or_reading_value(capsys):
    client = Mock()
    client.describe_secret.return_value = {"ARN": ARN}
    with patch.object(bootstrap.secrets, "token_urlsafe", return_value="PRIVATE") as generate:
        assert bootstrap.initialize(client) is True
    generate.assert_called_once_with(48)
    client.put_secret_value.assert_called_once_with(SecretId=ARN, SecretString="PRIVATE")
    client.get_secret_value.assert_not_called()
    assert capsys.readouterr().out == ""


def test_existing_version_is_not_changed_or_read():
    client = Mock()
    client.describe_secret.return_value = {"ARN": ARN, "VersionIdsToStages": {"v1": ["AWSCURRENT"]}}
    assert bootstrap.initialize(client) is False
    client.put_secret_value.assert_not_called()
    client.get_secret_value.assert_not_called()


@pytest.mark.parametrize("metadata", [
    {"ARN": ARN.replace("927161114143", "111111111111")},
    {"ARN": ARN, "DeletedDate": "scheduled"},
])
def test_wrong_account_or_pending_deletion_refused(metadata):
    client = Mock()
    client.describe_secret.return_value = metadata
    with pytest.raises(ValueError):
        bootstrap.initialize(client)
    client.put_secret_value.assert_not_called()


def test_main_never_echoes_sdk_error_payload(capsys):
    with patch.object(bootstrap.boto3, "Session") as session:
        session.return_value.client.side_effect = ClientError(
            {"Error": {"Code": "AccessDeniedException", "Message": "PRIVATE"}}, "DescribeSecret")
        assert bootstrap.main() == 1
    captured = capsys.readouterr()
    assert "PRIVATE" not in captured.out + captured.err
