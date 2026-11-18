"""Private HTTP-origin smoke test; no model calls or credential output."""

import argparse
import json
import re
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError


def validate_origin(value: str) -> str:
    # Do not forward the production credential to an arbitrary CLI-supplied URL.
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or parsed.netloc != "51b01wb0w6.execute-api.us-east-2.amazonaws.com"
            or parsed.path.rstrip("/") != "/public" or parsed.query or parsed.fragment):
        raise ValueError("invalid_origin")
    return value.rstrip("/")


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class OriginClient:
    def __init__(self, origin: str, secret: str) -> None:
        self.origin = validate_origin(origin)
        self.secret = secret
        self.opener = build_opener(NoRedirects())

    def request(self, path: str, *, method: str = "GET", body: Any = None,
                credential: str | None = "valid") -> tuple[int, Any, Any]:
        headers = {"Accept": "application/json", "Cache-Control": "no-store"}
        if credential is not None:
            headers["x-phineas-origin-token"] = self.secret if credential == "valid" else "invalid"
        data = None if body is None else json.dumps(body).encode()
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = Request(self.origin + path, data=data, headers=headers, method=method)
        try:
            response = self.opener.open(request, timeout=20)
        except HTTPError as error:
            response = error
        with response:
            raw = response.read(131073)
            if len(raw) > 131072:
                raise ValueError("response_too_large")
            payload = json.loads(raw) if raw else None
            return response.code, payload, response.headers


def require(condition: bool) -> None:
    if not condition:
        raise ValueError("unexpected_origin_response")


def check(client: Any, *, health_only: bool = False) -> None:
    status, _, _ = client.request("/health", credential=None)
    require(status in (401, 403))
    print("Missing origin credential rejected: passed", flush=True)
    status, _, _ = client.request("/health", credential="invalid")
    require(status in (401, 403))
    print("Incorrect origin credential rejected: passed", flush=True)
    status, body, headers = client.request("/health")
    print("Authenticated health diagnostics: " + json.dumps({
        "status": status,
        "body_matches": body == {"status": "ok"},
        "no_store": headers.get("cache-control") == "no-store",
    }), flush=True)
    require(status == 200 and body == {"status": "ok"} and headers.get("cache-control") == "no-store")
    print("Authenticated health and no-store response: passed", flush=True)
    if health_only:
        return
    status, body, _ = client.request("/samples/analysis-demo/preview")
    require(status == 200 and body["synthetic"] is True and len(body["rows"]) == 50)
    print("Synthetic sample preview: passed", flush=True)
    for path in ("/docs", "/openapi.json"):
        status, _, _ = client.request(path)
        require(status == 404)
    print("Unexposed documentation routes rejected: passed", flush=True)
    session_id = None
    try:
        status, body, _ = client.request("/sessions", method="POST", body={"sample_id": "analysis-demo"})
        require(status == 201)
        # Only a bounded server-issued capability may be inserted into a URL.
        session_id = body["session_id"]
        require(isinstance(session_id, str) and re.fullmatch(r"[A-Za-z0-9_-]{20,200}", session_id) is not None)
        print("Session creation through gateway: passed", flush=True)
        status, body, headers = client.request(f"/sessions/{session_id}/report")
        require(status == 200 and "analysis" in body and "facts" in body
                and headers.get("cache-control") == "no-store")
        print("Report through gateway: passed", flush=True)
    finally:
        if session_id is not None and re.fullmatch(r"[A-Za-z0-9_-]{20,200}", session_id):
            status, _, _ = client.request(f"/sessions/{session_id}", method="DELETE")
            require(status == 204)
            print("Session purge through gateway: passed", flush=True)
    status, body, _ = client.request(f"/sessions/{session_id}/report")
    require(status == 404 and body == {"detail": "session_unavailable"})
    print("Post-purge report access rejected: passed", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("origin")
    parser.add_argument("--health-only", action="store_true",
                        help="Check authentication and health only; never create a session.")
    args = parser.parse_args()
    try:
        origin = validate_origin(args.origin)
        config = Config(connect_timeout=5, read_timeout=15,
                        retries={"total_max_attempts": 1, "mode": "standard"})
        session = boto3.Session(region_name="us-east-2")
        if session.client("sts", config=config).get_caller_identity()["Account"] != "927161114143":
            print("Wrong AWS account; checks not run.")
            return 1
        secret = session.client("secretsmanager", config=config).get_secret_value(
            SecretId="phineas/origin-auth", VersionStage="AWSCURRENT")["SecretString"]
        require(isinstance(secret, str) and re.fullmatch(r"[A-Za-z0-9_-]{64}", secret) is not None)
        check(OriginClient(origin, secret), health_only=args.health_only)
    except (BotoCoreError, ClientError, URLError, TimeoutError, ValueError, KeyError, TypeError):
        print("Origin check failed; payloads, credentials, session IDs, and provider details withheld. "
              "If creation was attempted without a purge checkpoint, cleanup is unconfirmed.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
