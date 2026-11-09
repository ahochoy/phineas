import argparse
import json
from pathlib import Path

import boto3


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("function_name")
    args = parser.parse_args()

    client = boto3.client("lambda", region_name="us-east-2")
    template = json.loads(Path("events/health.json").read_text())

    def request(method: str, path: str, body: dict | None = None) -> dict:
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
        payload = json.loads(response["Payload"].read())

        if response.get("FunctionError"):
            raise RuntimeError("Lambda invocation failed")

        return {
            "status": payload["statusCode"],
            "body": json.loads(payload.get("body") or "null"),
        }

    created = request(
        "POST", "/sessions", {"sample_id": "analysis-demo"}
    )
    assert created["status"] == 201
    session_id = created["body"]["session_id"]
    print("Session creation: passed")

    try:
        analysis = request(
            "GET", f"/sessions/{session_id}/analysis"
        )
        assert analysis["status"] == 200
        assert len(analysis["body"]["subscription_candidates"]) == 1
        print("DynamoDB-backed analysis: passed")

        question = request(
            "POST",
            f"/sessions/{session_id}/questions",
            {"question": "Explain fees"},
        )
        assert question["status"] == 200
        assert question["body"]["intent"] == "fees"
        assert (
            question["body"]["narrative"]["narrative_status"]
            == "generated"
        )
        print("AgentCore fee question: passed")
    finally:
        purged = request("DELETE", f"/sessions/{session_id}")
        assert purged["status"] == 204
        print("Session purge: passed")

    missing = request("GET", f"/sessions/{session_id}/summary")
    assert missing["status"] == 404
    print("Post-purge access rejection: passed")


if __name__ == "__main__":
    main()
