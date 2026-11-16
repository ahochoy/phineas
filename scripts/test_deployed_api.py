import argparse
from collections.abc import Callable
import json
from pathlib import Path
import time
from uuid import uuid4

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError


def check(condition: bool, reason: str) -> None:
    if not condition:
        raise RuntimeError(reason)


def verify_deployment(request: Callable[..., dict], *,
                      clock: Callable[[], float] = time.monotonic,
                      pause: Callable[[float], None] = time.sleep,
                      timeout: float = 180) -> None:
    created = request("POST", "/sessions", {"sample_id": "analysis-demo"})
    check(created["status"] == 201, "session_creation_failed")
    session_id = created["body"]["session_id"]
    print("Session creation: passed")
    job_id = None

    try:
        analysis = request("GET", f"/sessions/{session_id}/analysis")
        check(analysis["status"] == 200, "analysis_failed")
        check(len(analysis["body"]["subscription_candidates"]) == 1, "analysis_mismatch")
        print("DynamoDB-backed analysis: passed")

        body = {"request_id": str(uuid4()), "question": "Explain fees"}
        path = f"/sessions/{session_id}/question-jobs"
        submitted = request("POST", path, body)
        check(submitted["status"] == 202, "job_submission_failed")
        job_id = submitted["body"]["job_id"]
        print("Async job submission: passed")

        repeated = request("POST", path, body)
        check(repeated["status"] == 202 and repeated["body"]["job_id"] == job_id,
            "job_idempotency_failed")
        print("Idempotent resubmission: passed")

        deadline = clock() + timeout
        while clock() < deadline:
            response = request("GET", f"/sessions/{session_id}/jobs/{job_id}")
            check(response["status"] == 200, "job_poll_failed")
            job = response["body"]
            check(job["state"] != "failed", "async_job_failed")
            if job["state"] == "succeeded":
                result = job["result"]
                check(result["intent"] == "fees", "job_intent_mismatch")
                check(result["narrative"]["narrative_status"] == "generated", "narrative_not_generated")
                check([fact["fact_id"] for fact in result["facts"]] == ["fee"], "job_facts_mismatch")
                highlights = result["narrative"]["highlights"]
                check(bool(highlights) and all(fact["fact_id"] == "fee" for fact in highlights),
                    "job_highlights_mismatch")
                print("SQS worker and AgentCore fee result: passed")
                break
            check(job["state"] in ("pending", "running"), "invalid_job_state")
            pause(min(3, max(0, deadline - clock())))
        else:
            raise RuntimeError("async_job_timeout")
    finally:
        purged = request("DELETE", f"/sessions/{session_id}")
        check(purged["status"] == 204, "session_purge_failed")
        print("Session purge: passed")

    missing = request("GET", f"/sessions/{session_id}/summary")
    check(missing == {"status": 404, "body": {"detail": "session_unavailable"}},
        "post_purge_session_access_failed")
    if job_id is not None:
        missing_job = request("GET", f"/sessions/{session_id}/jobs/{job_id}")
        check(missing_job == {"status": 404, "body": {"detail": "session_unavailable"}},
            "post_purge_job_access_failed")
    print("Post-purge session and job rejection: passed")


def verify_admission(request: Callable[..., dict]) -> None:
    """Check the deployed lifetime allowance without requesting model output."""
    created = request("POST", "/sessions", {"sample_id": "analysis-demo"})
    check(created["status"] == 201, "session_creation_failed")
    session_id = created["body"]["session_id"]
    print("Fresh session creation: passed")
    first_job = None
    first_body = None

    try:
        # Check the question route first: older API images return a fixed scope
        # response for this unsupported question, so stop before testing the
        # narrative route if async-only protection is missing.
        question = request("POST", f"/sessions/{session_id}/questions",
            {"question": "Tell me a joke"})
        check(question == {"status": 409, "body": {"detail": "async_questions_required"}},
            "synchronous_question_bypass_open")
        narrative = request("POST", f"/sessions/{session_id}/narrative")
        check(narrative == {"status": 409, "body": {"detail": "async_questions_required"}},
            "synchronous_narrative_bypass_open")
        print("Synchronous inference routes blocked: passed")

        path = f"/sessions/{session_id}/question-jobs"
        for _ in range(10):
            body = {"request_id": str(uuid4()), "question": "Tell me a joke"}
            submitted = request("POST", path, body)
            check(submitted["status"] == 202, "admission_below_limit_failed")
            if first_job is None:
                first_job = submitted["body"]["job_id"]
                first_body = body
        print("Ten distinct jobs accepted: passed")

        replay = request("POST", path, first_body)
        check(replay["status"] == 202 and replay["body"]["job_id"] == first_job,
            "replay_at_capacity_failed")
        print("Replay at capacity: passed")

        rejected = request("POST", path,
            {"request_id": str(uuid4()), "question": "Tell me a joke"})
        check(rejected == {"status": 429, "body": {"detail": "question_job_limit_reached"}},
            "eleventh_job_not_rejected")
        print("Eleventh distinct job rejected: passed")
        check(request("GET", f"/sessions/{session_id}/analysis")["status"] == 200,
            "analysis_unavailable_at_capacity")
        check(request("GET", f"/sessions/{session_id}/jobs/{first_job}")["status"] == 200,
            "job_unavailable_at_capacity")
        print("Analysis and existing job remain accessible: passed")
    finally:
        purged = request("DELETE", f"/sessions/{session_id}")
        check(purged["status"] == 204, "session_purge_failed")
        print("Session purge: passed")

    for path in (f"/sessions/{session_id}/summary", f"/sessions/{session_id}/jobs/{first_job}"):
        check(request("GET", path) == {"status": 404, "body": {"detail": "session_unavailable"}},
            "post_purge_access_failed")
    print("Post-purge session and job rejection: passed")


def verify_paused(request: Callable[..., dict]) -> None:
    """Check disabled admission without freezing deterministic session operations."""
    created = request("POST", "/sessions", {"sample_id": "analysis-demo"})
    check(created["status"] == 201, "session_creation_failed")
    session_id = created["body"]["session_id"]
    print("Fresh session creation: passed")
    try:
        paused = request("POST", f"/sessions/{session_id}/question-jobs",
            {"request_id": str(uuid4()), "question": "Tell me a joke"})
        check(paused == {"status": 503, "body": {"detail": "demo_admissions_paused"}},
            "expected_admission_pause_missing")
        print("New job rejected by admission pause: passed")
        check(request("GET", f"/sessions/{session_id}/analysis")["status"] == 200,
            "analysis_unavailable_while_paused")
        print("Deterministic analysis while paused: passed")
    finally:
        purged = request("DELETE", f"/sessions/{session_id}")
        check(purged["status"] == 204, "session_purge_failed")
        print("Session purge while paused: passed")
    missing = request("GET", f"/sessions/{session_id}/summary")
    check(missing == {"status": 404, "body": {"detail": "session_unavailable"}},
        "post_purge_access_failed")
    print("Post-purge access rejection: passed")


def main() -> int:
    parser = argparse.ArgumentParser(description="Private synthetic async deployment smoke test")
    parser.add_argument("function_name")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--admission-only", action="store_true",
        help="Check admission limits using unsupported questions instead of model generation")
    modes.add_argument("--paused-only", action="store_true",
        help="Check disabled admission, analysis, and purge without admitting jobs")
    args = parser.parse_args()
    template = json.loads((Path(__file__).resolve().parents[1] / "events/health.json").read_text())
    # One attempt: never silently repeat a mutating HTTP operation after an
    # ambiguous Lambda transport timeout. An orphaned synthetic session has TTL.
    client = None

    def request(method: str, path: str, body: dict | None = None) -> dict:
        nonlocal client
        if client is None:
            client = boto3.client("lambda", region_name="us-east-2",
                config=Config(connect_timeout=5, read_timeout=130,
                    retries={"total_max_attempts": 1, "mode": "standard"}))
        event = {
            **template,
            "rawPath": path,
            "headers": {
                "host": "localhost",
                "content-type": "application/json",
            },
            "requestContext": {
                **template["requestContext"],
                "http": {
                    **template["requestContext"]["http"],
                    "method": method,
                    "path": path,
                },
            },
        }

        if body is not None:
            event["body"] = json.dumps(body)

        response = client.invoke(
            FunctionName=args.function_name,
            InvocationType="RequestResponse",
            Payload=json.dumps(event).encode(),
        )
        stream = response["Payload"]
        try:
            check(not response.get("FunctionError"), "lambda_function_error")
            payload = json.loads(stream.read())
        finally:
            stream.close()

        return {
            "status": payload["statusCode"],
            "body": json.loads(payload.get("body") or "null"),
        }

    try:
        if args.paused_only:
            verify_paused(request)
        elif args.admission_only:
            verify_admission(request)
        else:
            verify_deployment(request)
        return 0
    except RuntimeError as error:
        print(f"Deployment check failed: {error}")
    except (BotoCoreError, ClientError):
        print("Deployment check failed: aws_invocation_error")
    except (KeyError, TypeError, ValueError):
        print("Deployment check failed: unexpected_response")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
