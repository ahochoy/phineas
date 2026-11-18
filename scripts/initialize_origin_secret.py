"""One-time origin credential bootstrap. Never prints or writes the value locally."""

import secrets
import sys
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError


ACCOUNT = "927161114143"
REGION = "us-east-2"
SECRET_NAME = "phineas/origin-auth"


def initialize(client: Any) -> bool:
    metadata = client.describe_secret(SecretId=SECRET_NAME)
    if metadata["ARN"].split(":")[4] != ACCOUNT:
        raise ValueError("wrong_account")
    if metadata.get("DeletedDate"):
        raise ValueError("secret_scheduled_for_deletion")
    # Do not fetch the existing secret or rotate it accidentally. Run this
    # bootstrap once, from one terminal; this check is not a concurrent lock.
    if metadata.get("VersionIdsToStages"):
        return False
    client.put_secret_value(SecretId=metadata["ARN"], SecretString=secrets.token_urlsafe(48))
    return True


def main() -> int:
    try:
        config = Config(connect_timeout=5, read_timeout=15,
                        retries={"total_max_attempts": 1, "mode": "standard"})
        session = boto3.Session(region_name=REGION)
        if session.client("sts", config=config).get_caller_identity()["Account"] != ACCOUNT:
            print("Wrong AWS account; nothing changed.")
            return 1
        created = initialize(session.client("secretsmanager", config=config))
    except (BotoCoreError, ClientError, ValueError):
        print("Bootstrap unavailable; no credential or exception details printed. "
              "A write may have succeeded; inspect secret version metadata before retrying.")
        return 1
    print("Origin credential initialized; value not displayed." if created else
          "Secret already has a version; left unchanged.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
