"""Developer-only, bounded synthetic evaluation; never used by the public API."""

import argparse
import hashlib
import json
from pathlib import Path
import sys
from time import perf_counter
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from phineas.analysis import analyze_transactions
from phineas.bedrock import AgentCoreNarrativeProvider
from phineas.narratives import (
    ExplanationDraft, ExplanationRejected, NarrativeUnavailable, validate_explanation,
)
from phineas.questions import SUGGESTED_QUESTIONS, answer_question
from phineas.samples import ingest_sample


ROOT = Path(__file__).resolve().parents[1]
MODELS = ("us.amazon.nova-micro-v1:0", "us.anthropic.claude-sonnet-4-6")


def record_sdk_error(owner: "EvaluationClient", error: Exception) -> None:
    # EventStreamError can be raised while iterating, not just opening a call.
    # Keep only allowlisted categories; never retain the exception message.
    known_types = {"EventStreamError", "ParamValidationError", "ReadTimeoutError",
                   "ConnectTimeoutError", "EndpointConnectionError", "NoCredentialsError",
                   "TokenRetrievalError", "CredentialRetrievalError"}
    name = type(error).__name__
    owner.diagnostics["sdk_error"] = name if name in known_types else "other"
    if isinstance(error, ClientError):
        code = error.response.get("Error", {}).get("Code")
        known = {"AccessDeniedException", "ValidationException", "ThrottlingException",
                 "ResourceNotFoundException", "InternalServerException",
                 "ServiceUnavailableException", "ExpiredTokenException", "ModelErrorException"}
        owner.diagnostics["api_error"] = code if code in known else "other"
        message = error.response.get("Error", {}).get("Message", "").casefold()
        owner.diagnostics["error_hints"] = [
            label for label, markers in {
                "sampling_parameter": ("temperature", "top_p", "topp"),
                "thinking_parameter": ("thinking",),
                "request_field": ("additionalmodelrequestfields", "unknown parameter", "extraneous key"),
                "authorization": ("accessdenied", "not authorized", "access denied"),
                "model_subscription": ("marketplace", "subscription", "use case"),
            }.items() if any(marker in message for marker in markers)
        ]


def model_config(model: str) -> dict[str, Any]:
    config: dict[str, Any] = {
        "modelId": model, "maxTokens": 1024, "apiFormat": "converse_stream",
        "temperature": 0.1,
    }
    # Sonnet 4.6 thinking is off by default; no provider-specific override.
    return config


class MeasuredStream:
    def __init__(self, stream: Any, owner: "EvaluationClient") -> None:
        self.stream = stream
        self.owner = owner

    def __iter__(self):
        try:
            yield from self._events()
        except (BotoCoreError, ClientError) as error:
            record_sdk_error(self.owner, error)
            raise

    def _events(self):
        for event in self.stream:
            self.owner.diagnostics["stream_events_seen"] = True
            for key in ("runtimeClientError", "validationException", "internalServerException"):
                if key in event:
                    self.owner.diagnostics["stream_error"] = key
            if "messageStop" in event:
                reason = event["messageStop"].get("stopReason")
                known = {"end_turn", "tool_use", "max_tokens", "max_iterations_exceeded",
                         "max_output_tokens_exceeded", "timeout_exceeded", "stop_sequence"}
                self.owner.diagnostics["stop_reason"] = reason if reason in known else "other"
            if "metadata" in event:
                self.owner.usage = event["metadata"].get("usage", {})
            yield event

    def close(self) -> None:
        self.stream.close()


class EvaluationClient:
    """Inject trusted overrides while reusing production stream validation."""

    def __init__(self, client: Any, model: str, prompt: str) -> None:
        self.client = client
        self.model = model
        self.prompt = prompt
        self.usage: dict[str, Any] = {}
        self.diagnostics: dict[str, Any] = {}
        self.rejected_draft: dict[str, Any] | None = None

    def invoke_harness(self, **kwargs: Any) -> dict[str, Any]:
        self.usage = {}
        self.diagnostics = {}
        self.rejected_draft = None
        try:
            response = self.client.invoke_harness(
                **kwargs,
                model={"bedrockModelConfig": model_config(self.model)},
                systemPrompt=[{"text": self.prompt}],
            )
        except (BotoCoreError, ClientError) as error:
            record_sdk_error(self, error)
            raise
        self.diagnostics["stream_opened"] = True
        response["stream"] = MeasuredStream(response["stream"], self)
        return response


class EvaluationProvider(AgentCoreNarrativeProvider):
    def __init__(self, arn: str, measured: EvaluationClient) -> None:
        super().__init__(arn, client=measured)
        self.measured = measured

    def explain(self, intent, facts):
        text = super().explain(intent, facts)
        self.measured.diagnostics["transport_completed"] = True
        try:
            validate_explanation(text, facts)
        except ExplanationRejected as error:
            self.measured.diagnostics["validation_rejection"] = error.reason
            if error.reason != "json_or_schema":
                # This runner only ingests the bundled synthetic sample. Retain
                # schema-bounded rejected prose for private human evaluation,
                # never console logs or application responses.
                self.measured.rejected_draft = ExplanationDraft.model_validate_json(text).model_dump()
            raise
        return text


def run_comparison(client: Any, arn: str, prompt: str, output: Any, *, probe: bool = False) -> int:
    # Freeze once: both models see identical aggregate cards and merchant IDs.
    analysis = analyze_transactions(ingest_sample("analysis-demo"))
    providers = {
        model: EvaluationClient(client, model, prompt) for model in (MODELS[1:] if probe else MODELS)
    }
    rejected = 0
    for repeat in range(1, 2 if probe else 4):
        for question in (list(SUGGESTED_QUESTIONS)[:1] if probe else SUGGESTED_QUESTIONS):
            for model, measured in providers.items():
                started = perf_counter()
                result = answer_question(analysis, question,
                    EvaluationProvider(arn, measured))
                record = {
                    "schema_version": 1, "synthetic_only": True,
                    "sample_id": "analysis-demo", "model": model,
                    "model_config": model_config(model),
                    "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                    "repeat": repeat, "intent": result.intent.value,
                    "duration_ms": round((perf_counter() - started) * 1000),
                    "usage": measured.usage,
                    "diagnostics": measured.diagnostics,
                    "rejected_synthetic_draft": measured.rejected_draft,
                    "facts": [fact.model_dump() for fact in result.facts],
                    "explanation": result.explanation.model_dump() if result.explanation else None,
                    "human_review": None,
                }
                # This explicit synthetic review artifact is not application logging.
                output.write(json.dumps(record) + "\n")
                output.flush()
                status = result.explanation.status if result.explanation else "missing"
                print(f"{model} / {result.intent.value} / {repeat}: {status}", flush=True)
                print("Diagnostics: " + json.dumps(measured.diagnostics), flush=True)
                if status != "generated":
                    if measured.diagnostics.get("validation_rejection"):
                        rejected += 1
                        # Quality failures are evaluation observations, not a
                        # reason to hide the remaining questions/repetitions.
                        continue
                    print("Stopped on transport/access failure; inspect diagnostics before retrying.")
                    return 1
    print(f"Evaluation completed; validation rejections: {rejected}. Human review still required.")
    return 1 if rejected else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--harness-arn")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--probe-candidate", action="store_true",
                        help="Run only one Sonnet overview call to diagnose compatibility.")
    parser.add_argument("--output", type=Path, default=ROOT / "evaluations/results/nova-sonnet-comparison.jsonl")
    args = parser.parse_args()
    if not args.execute:
        print("Dry run: at most 1 paid Sonnet invocation." if args.probe_candidate else
              "Dry run: 6 questions x 3 repetitions x 2 models = at most 36 paid Harness invocations.")
        print("Bundled analysis-demo only; no sessions, queue jobs, deployment changes, or quota resets.")
        return 0
    if not args.harness_arn:
        parser.error("--harness-arn is required with --execute")
    prompt = (ROOT / "prompts/narrative.txt").read_text()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    try:
        # Exclusive creation prevents accidental loss of a previous evaluation.
        with args.output.open("x") as output:
            client = boto3.client("bedrock-agentcore", region_name="us-east-2",
                config=Config(connect_timeout=5, read_timeout=90,
                    retries={"total_max_attempts": 1, "mode": "standard"}))
            return run_comparison(client, args.harness_arn, prompt, output, probe=args.probe_candidate)
    except FileExistsError:
        print("Output already exists; select a new --output path.")
        return 1
    except (BotoCoreError, ClientError, NarrativeUnavailable):
        print("Evaluation unavailable; no provider payload or exception details logged.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
