import argparse
import sys
from uuid import uuid4

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError


def invoke_harness(client, harness_arn: str, prompt: str) -> None:
    session_id = str(uuid4())
    print(f"Runtime session: {session_id}", file=sys.stderr)

    response = client.invoke_harness(
        harnessArn=harness_arn,
        runtimeSessionId=session_id,
        messages=[
            {
                "role": "user",
                "content": [{"text": prompt}],
            }
        ],
    )

    error_event_names = (
        "runtimeClientError",
        "validationException",
        "internalServerException",
    )

    for event in response["stream"]:
        if content_delta := event.get("contentBlockDelta"):
            delta = content_delta.get("delta", {})
            if text := delta.get("text"):
                print(text, end="", flush=True)

        for error_name in error_event_names:
            if error := event.get(error_name):
                message = error.get("message", "Unknown streaming error")
                raise RuntimeError(f"{error_name}: {message}")

    print()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Invoke the Phineas AgentCore Harness."
    )
    parser.add_argument("harness_arn")
    parser.add_argument(
        "prompt",
        nargs="?",
        default="In one sentence, describe your current capabilities.",
    )
    parser.add_argument("--region", default="us-east-2")
    args = parser.parse_args()

    config = Config(
        retries={"total_max_attempts": 3, "mode": "standard"},
        connect_timeout=5,
        read_timeout=90,
    )

    client = boto3.client(
        "bedrock-agentcore",
        region_name=args.region,
        config=config,
    )

    try:
        invoke_harness(client, args.harness_arn, args.prompt)
        return 0
    except (ClientError, RuntimeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
