"""Transfer the existing origin credential to Wrangler without displaying it."""

import os
from pathlib import Path
import re
import subprocess
import sys

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError


ROOT = Path(__file__).resolve().parents[1]


def install(secret: str) -> None:
    if not isinstance(secret, str) or re.fullmatch(r"[A-Za-z0-9_-]{64}", secret) is None:
        raise ValueError("invalid_credential_format")
    cli = ROOT / "node_modules/wrangler/bin/wrangler.js"
    if not cli.is_file():
        raise ValueError("run_npm_ci_first")
    environment = {
        **os.environ,
        "WRANGLER_LOG": "error",
        "WRANGLER_LOG_PATH": os.devnull,
        "WRANGLER_SEND_METRICS": "false",
    }
    result = subprocess.run(
        ["node", str(cli), "secret", "put", "ORIGIN_TOKEN", "--name", "phineas-finance",
         "--config", str(ROOT / "wrangler.jsonc")],
        cwd=ROOT, env=environment, input=secret + "\n", text=True,
        capture_output=True, timeout=90, check=False,
    )
    if result.returncode != 0:
        raise ValueError("transfer_unconfirmed")


def main() -> int:
    try:
        if not (ROOT / "node_modules/wrangler/bin/wrangler.js").is_file():
            print("Run npm ci first; no credential was read.")
            return 1
        config = Config(connect_timeout=5, read_timeout=15,
                        retries={"total_max_attempts": 1, "mode": "standard"})
        session = boto3.Session(region_name="us-east-2")
        if session.client("sts", config=config).get_caller_identity()["Account"] != "927161114143":
            print("Wrong AWS account; no credential transferred.")
            return 1
        secret = session.client("secretsmanager", config=config).get_secret_value(
            SecretId="phineas/origin-auth", VersionStage="AWSCURRENT")["SecretString"]
        install(secret)
    except (BotoCoreError, ClientError, ValueError, KeyError, OSError, subprocess.SubprocessError):
        print("Credential transfer unconfirmed; values and CLI/provider details withheld. "
              "A remote update may have succeeded. Demo enablement is unchanged.")
        return 1
    print("Cloudflare ORIGIN_TOKEN installed; credential not displayed. Demo enablement is unchanged.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
