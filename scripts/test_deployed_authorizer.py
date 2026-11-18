"""Private authorizer smoke test. Never print credentials or request payloads."""

import json
import sys
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError


def invoke(client: Any, headers: dict[str, str], expected: bool) -> None:
    response = client.invoke(
        FunctionName="phineas-origin-authorizer",
        InvocationType="RequestResponse",
        Payload=json.dumps({"version": "2.0", "type": "REQUEST", "headers": headers}).encode(),
    )
    stream = response["Payload"]
    try:
        raw = stream.read(4097)
    finally:
        stream.close()
    if response.get("FunctionError") or response.get("StatusCode") != 200 or len(raw) > 4096:
        raise ValueError("authorizer_invocation_failed")
    result = json.loads(raw)
    if result != {"isAuthorized": expected}:
        raise ValueError("unexpected_authorization_result")


def check(lambda_client: Any, secrets_client: Any) -> None:
    invoke(lambda_client, {}, False)
    print("Missing credential rejected: passed")
    secret = secrets_client.get_secret_value(
        SecretId="phineas/origin-auth", VersionStage="AWSCURRENT")["SecretString"]
    if not isinstance(secret, str) or len(secret) != 64:
        raise ValueError("unexpected_secret_format")
    # Ensure the deliberately wrong token differs even in the unlikely case
    # of an all-identical generated secret.
    incorrect = ("b" if secret[0] == "a" else "a") + secret[1:]
    invoke(lambda_client, {"x-phineas-origin-token": incorrect}, False)
    print("Incorrect credential rejected: passed")
    invoke(lambda_client, {"x-phineas-origin-token": secret}, True)
    print("Valid credential accepted: passed")


def main() -> int:
    try:
        config = Config(connect_timeout=5, read_timeout=20,
                        retries={"total_max_attempts": 1, "mode": "standard"})
        session = boto3.Session(region_name="us-east-2")
        if session.client("sts", config=config).get_caller_identity()["Account"] != "927161114143":
            print("Wrong AWS account; checks not run.")
            return 1
        check(session.client("lambda", config=config), session.client("secretsmanager", config=config))
    except (BotoCoreError, ClientError, ValueError, KeyError, TypeError):
        print("Authorizer check failed; credential, payload, and provider details withheld.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
