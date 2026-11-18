"""Native Lambda entrypoint for the standard SQS question queue.

No HTTP server or Web Adapter is involved. Lambda's event source mapping owns
message deletion; this handler reports only deliveries that need another try.
"""

from functools import lru_cache
import json
import os
from time import monotonic
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from phineas.bedrock import AgentCoreNarrativeProvider
from phineas.dynamodb_jobs import DynamoDBJobStore
from phineas.dynamodb_sessions import DynamoDBSessionStore
from phineas.jobs import JobMessage, QuestionWorker, WorkerOutcome, WorkerRetry
from phineas.sessions import SessionStoreError


class LambdaContext(Protocol):
    def get_remaining_time_in_millis(self) -> int: ...


class _Record(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)
    messageId: str = Field(min_length=1)
    eventSource: Literal["aws:sqs"]
    body: str = Field(repr=False)


class _Batch(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)
    Records: list[_Record]


# Admission margin, not a guarantee: network retries or a hard Lambda timeout
# can still interrupt processing. Deploy with batch_size=1 and a 120s timeout.
MIN_START_TIME_MS = 110_000

DeliveryOutcome = WorkerOutcome | Literal["deferred", "retry_required", "invalid_message", "store_unavailable", "unexpected_failure"]


def _emit_outcome(outcome: DeliveryOutcome, started: float) -> None:
    # One plain JSON line: CloudWatch can filter it without parsing a logger
    # prefix. Only closed-vocabulary outcomes and an operational timing leave
    # this boundary. Never include IDs, intents, exception text, or payloads.
    print(json.dumps({"event": "question_delivery", "schema_version": 1,
        "outcome": outcome, "duration_ms": max(0, int((monotonic() - started) * 1000))}), flush=True)


def process_sqs_batch(event: object, worker: QuestionWorker,
                      context: LambdaContext) -> dict[str, list[dict[str, str]]]:
    try:
        batch = _Batch.model_validate(event)
        if len({record.messageId for record in batch.Records}) != len(batch.Records):
            raise ValueError()
    except (ValidationError, ValueError):
        # Without valid message IDs, we cannot safely acknowledge a subset.
        # Never allow validation errors (which embed inputs) into runtime logs.
        raise ValueError("invalid_sqs_envelope") from None

    failures: list[dict[str, str]] = []
    for record in batch.Records:
        started = monotonic()
        outcome: DeliveryOutcome = "unexpected_failure"
        try:
            if context.get_remaining_time_in_millis() < MIN_START_TIME_MS:
                failures.append({"itemIdentifier": record.messageId})
                outcome = "deferred"
                continue
            message = JobMessage.model_validate_json(record.body)
            outcome = worker.process(message)
        except ValidationError:
            outcome = "invalid_message"
            failures.append({"itemIdentifier": record.messageId})
        except WorkerRetry:
            outcome = "retry_required"
            failures.append({"itemIdentifier": record.messageId})
        except SessionStoreError:
            outcome = "store_unavailable"
            failures.append({"itemIdentifier": record.messageId})
        except Exception:
            # Transport boundary: transient failures and malformed bodies must
            # retry, eventually reaching the DLQ if they cannot be handled.
            # Do not log the exception: SDK/validation errors may embed data.
            failures.append({"itemIdentifier": record.messageId})
        finally:
            _emit_outcome(outcome, started)
    return {"batchItemFailures": failures}


@lru_cache(maxsize=1)
def _configured_worker() -> QuestionWorker:
    table_name = os.environ.get("PHINEAS_SESSIONS_TABLE")
    harness_arn = os.environ.get("PHINEAS_HARNESS_ARN")
    if not table_name or not harness_arn:
        raise ValueError("question_worker_not_configured")
    region = os.environ.get("AWS_REGION", "us-east-2")
    sessions = DynamoDBSessionStore(table_name, region)
    return QuestionWorker(sessions, DynamoDBJobStore(sessions),
        AgentCoreNarrativeProvider(harness_arn, region))


def lambda_handler(event: object, context: LambdaContext) -> dict[str, list[dict[str, str]]]:
    return process_sqs_batch(event, _configured_worker(), context)
