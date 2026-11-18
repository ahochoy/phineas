"""Set the shared demo password and rotate its signing key using hidden prompts."""

from getpass import getpass
import os
from pathlib import Path
import secrets
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def install(name: str, value: str) -> None:
    cli = ROOT / "node_modules/wrangler/bin/wrangler.js"
    result = subprocess.run(
        ["node", str(cli), "secret", "put", name, "--name", "phineas-finance",
         "--config", str(ROOT / "wrangler.jsonc")],
        cwd=ROOT, input=value + "\n", text=True, capture_output=True, timeout=90,
        env={**os.environ, "WRANGLER_LOG": "error", "WRANGLER_LOG_PATH": os.devnull,
             "WRANGLER_SEND_METRICS": "false"}, check=False,
    )
    if result.returncode != 0:
        raise ValueError("secret_install_unconfirmed")


def main() -> int:
    if not sys.stdin.isatty() or not sys.stderr.isatty():
        print("Run this script in an interactive terminal; passwords must not be piped or echoed.")
        return 1
    if not (ROOT / "node_modules/wrangler/bin/wrangler.js").is_file():
        print("Run npm ci first.")
        return 1
    try:
        password = getpass("Choose a demo passphrase (12–128 characters): ")
        if not 12 <= len(password) <= 128 or "\n" in password or "\r" in password:
            print("Use a passphrase of 12–128 characters on one line.")
            return 1
        if password != getpass("Confirm demo passphrase: "):
            print("Passphrases did not match; nothing changed.")
            return 1
        install("DEMO_PASSWORD", password)
        install("DEMO_AUTH_KEY", secrets.token_urlsafe(48))
    except (EOFError, KeyboardInterrupt, OSError, ValueError, subprocess.SubprocessError):
        print("Setup unconfirmed; values and provider details withheld. Remote updates may be partial. "
              "Keep the demo paused until both secrets are installed successfully.")
        return 1
    print("Demo password and signing key installed; values not displayed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
