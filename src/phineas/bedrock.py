"""AgentCore transport. All request fields are server-owned."""

from collections.abc import Sequence
from typing import Any
from uuid import uuid4

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from phineas.narratives import FactCard, NarrativeUnavailable, encode_facts


class AgentCoreNarrativeProvider:
    def __init__(self, harness_arn: str, region: str = "us-east-2", *, client: Any = None) -> None:
        self._arn = harness_arn
        self._region = region
        self._client = client

    def select(self, facts: Sequence[FactCard]) -> str:
        try:
            # Lazy construction lets the API start without AWS credentials and
            # lets credential failures follow the normal unavailable fallback.
            if self._client is None:
                self._client = boto3.client("bedrock-agentcore", region_name=self._region,
                    config=Config(connect_timeout=5, read_timeout=90,
                        retries={"total_max_attempts": 1, "mode": "standard"}))
            payload = encode_facts(facts)
            if len(payload.encode("utf-8")) > 32000:
                raise NarrativeUnavailable()
            response = self._client.invoke_harness(
                harnessArn=self._arn,
                runtimeSessionId=str(uuid4()),
                messages=[{"role": "user", "content": [{"text": payload}]}],
                maxIterations=1, maxTokens=512, timeoutSeconds=60,
                # A nonmatching server-owned allowlist prevents built-in tools
                # from being exposed. No external request can override this.
                allowedTools=["phineas_no_tools"],
            )
            stream = response["stream"]
            fragments: list[str] = []
            size = 0
            completed = False
            try:
                for event in stream:
                    if any(key in event for key in (
                        "runtimeClientError", "validationException", "internalServerException",
                    )):
                        raise NarrativeUnavailable()
                    if "contentBlockStart" in event:
                        if event["contentBlockStart"].get("start", {}).get("toolUse"):
                            raise NarrativeUnavailable()
                    if "contentBlockDelta" in event:
                        delta = event["contentBlockDelta"].get("delta", {})
                        if "toolUse" in delta:
                            raise NarrativeUnavailable()
                        text = delta.get("text", "")
                        size += len(text)
                        if size > 8192:
                            raise NarrativeUnavailable()
                        fragments.append(text)
                    if "messageStop" in event:
                        if event["messageStop"].get("stopReason") != "end_turn":
                            raise NarrativeUnavailable()
                        completed = True
            finally:
                stream.close()
            if not completed:
                raise NarrativeUnavailable()
            return "".join(fragments)
        except (BotoCoreError, ClientError):
            raise NarrativeUnavailable() from None
