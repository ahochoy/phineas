# Asynchronous questions: lifecycle contract

The private Docker/Lambda deployment was verified before this slice: Web Adapter
health, DynamoDB-backed analysis, AgentCore fee selection, purge, and post-purge
404 all succeeded. The next change removes inference latency from HTTP ingress.

## Implemented application slice

- `jobs.py` defines job records, store/queue protocols, submission/polling service,
  a worker, and a thread-safe in-memory reference store.
- Submit: `POST /sessions/{session_id}/question-jobs`, body containing a client
  UUID `request_id` and an approved `question`. The response is 202 with a job ID
  and current state. The client retains and reuses the UUID on uncertain retries.
- Poll: `GET /sessions/{session_id}/jobs/{job_id}`. States are pending, running,
  succeeded, or failed. Only succeeded jobs carry a validated QuestionResponse.
- Queue messages contain session ID, job ID, and classified intent. They never
  contain question text, financial facts, or credentials beyond the session
  capability needed to locate the work. Queue bodies must not be logged.
- A repeated request with the same session/request ID and intent returns the same
  job. Reusing it for another intent returns 409. Repeated pending submissions
  re-enqueue the same job, recovering from an ambiguous send without assuming an
  atomic transaction between the store and SQS. Duplicate messages are expected.
- Queue failure returns 503; the pending job remains retriable by request ID.
- Workers claim a 150-second lease with a fresh token and bounded attempt count
  of three. Active leases cause delivery retry, not a second concurrent inference.
  Expired leases can be reclaimed; an old token cannot publish results.
- An unavailable model response releases work for retry. Exhaustion becomes a
  terminal safe failure. Unexpected worker crashes leave the lease for recovery.
  Outstanding jobs expire after 25 minutes, or earlier if the session expires.
- Background reads use `peek()` and do not refresh the user's idle deadline.
  Authorized submission/polling does refresh it. Worker reads and result writes
  recheck validity; expired/purged sessions cannot be used to obtain results.
- Unsupported questions complete with the fixed scope response without invoking
  a model. Stored intent must match the queue message before the worker claims it.

## Durable adapters

`DynamoDBJobStore` stores `JOB#<uuid>` records beside `METADATA` and
`TRANSACTION#...` records under the session partition key. Jobs store classified
intent, lease/attempt state, and validated results, never the user's question.
The `expires_at` TTL is the session's absolute expiration.

Every job write uses a DynamoDB transaction with two actions:

1. Check that session metadata exists, is unexpired, and has no purge marker.
2. Write the job only if it is new or its revision still matches the read.

The job revision fences concurrent claims and stale publishers. The session check
closes the race between a preliminary application read and a purge. Background
work never updates session activity. The metadata schema remains compatible with
existing sessions; no table migration or secondary index is needed.

Purge now marks metadata `purging = true` before deleting anything. This revokes
access and blocks transactional job writers. It then queries and batch-deletes
all records in the partition, deleting metadata last. Unlike the old atomic purge,
cleanup is multi-step, but it supports partitions larger than the 100-action
transaction limit. A cleanup failure returns a safe error; the marker remains,
access stays blocked, and retrying purge finishes cleanup. TTL remains fallback
cleanup, not immediate physical deletion. The atomic authorization boundary and
the physical deletion boundary are deliberately distinct.

`SqsJobQueue` sends only a serialized `JobMessage`. It reuses its SDK client,
bounds SDK retries/timeouts, and maps transport failures to `QueueUnavailable`.
A send can succeed remotely even if the caller sees a timeout, so clients must
retry with the same request UUID rather than inventing a new job.

Setting both `PHINEAS_SESSIONS_TABLE` and `PHINEAS_QUESTION_QUEUE_URL` enables the
durable API adapter. A queue URL without a table fails configuration instead of
silently using memory. Without a queue URL, async routes still return
`async_questions_not_configured`. No worker is started by API configuration.

## Native Lambda queue handler

`phineas.queue_worker.lambda_handler` adapts a standard SQS event to the existing
`QuestionWorker`. It is a native Lambda handler, not a FastAPI route. The API's
current Web Adapter/Uvicorn container startup must not be used for this worker.
`Dockerfile.worker` now defines that native packaging. Build and runtime smoke
verification remain developer checkpoints; see [worker-container.md](worker-container.md).

- The envelope requires SQS records with nonempty, unique message IDs. Invalid
  envelopes fail the invocation with a fixed safe reason, without exposing
  Pydantic validation inputs in exception logs.
- Each body is validated as `JobMessage`. Malformed bodies, active leases,
  backend failures, and unexpected processing exceptions are returned as failed
  message IDs. Bodies and exception details are not logged.
- The response is `{"batchItemFailures": [{"itemIdentifier": "..."}]}`. Successful
  records are omitted. Terraform must enable `ReportBatchItemFailures` for Lambda
  to honor per-message retry reporting. Lambda handles message deletion; the
  handler does not call `DeleteMessage` itself.
- Expired/purged sessions and missing jobs are acknowledged without inference.
  Completed jobs are safe to acknowledge again. A terminal model failure is a
  handled delivery with a failed job; it need not reach the DLQ. Unprocessable
  deliveries retry and may reach the DLQ through SQS's redrive policy.
- Before starting each record, the handler requires 110 seconds remaining.
  This is an admission margin for the planned 120-second Lambda, not a completion
  guarantee. Network stalls or hard timeouts still rely on redelivery and lease
  recovery. Deploy with batch size one.
- Configuration requires `PHINEAS_SESSIONS_TABLE` and `PHINEAS_HARNESS_ARN`;
  `AWS_REGION` defaults to `us-east-2`. Dependencies are created lazily and reused
  in a warm environment. No API or polling loop starts.

The transport uses a small, directly tested loop rather than adding a batch
framework for this one standard-queue consumer. Revisit Powertools if additional
event sources, FIFO processing, or richer batch behavior is needed.

## Deployment boundary

The developer has confirmed deployment of both images, queue permissions, worker
role/log group, the source queue/DLQ, and the event source mapping. Local container
smoke tests passed; the deployed worker accepted an empty batch. The mapping was
confirmed Enabled with batch size one, `ReportBatchItemFailures`, and maximum
concurrency two. The API's async image and queue URL have now been applied.
Existing synchronous routes remain for private tests; no public endpoint has
been introduced. The developer ran the full async deployed test successfully:
session creation, DynamoDB analysis, job submission, idempotent resubmission,
the SQS worker's generated AgentCore fee result, purge, and post-purge
session/job rejection all passed. This verifies the happy-path integration,
not live retry, DLQ redrive, or production concurrency behavior.

The worker timeout is 120 seconds and queue visibility is 720 seconds. The
25-minute job deadline permits nominal delivery opportunities at 0, 12, and 24
minutes; actual delivery timing is not guaranteed, and completion also requires
an active session. SQS allows five receives before redrive; application code
separately limits job execution attempts to three.

The patched worker image scan reported no findings. The API scan reported two
high glibc findings (CVE-2026-5435 and CVE-2026-19499), nine medium, and three low.
These are not remediated by enabling async execution. The existing private,
synthetic-only assessment was retained; public exposure needs a fresh review.

The worker will report failed message IDs using Lambda partial-batch responses.
Do not acknowledge an active lease or transient failure as success. Dead-letter
messages contain only opaque identifiers/intent, still have bounded retention,
and must not be redriven into expired sessions.

Exactly-once model invocation is not guaranteed: a worker can complete inference
and crash before recording success. Leases prevent overlapping valid ownership,
not repeated paid work after a crash. The deterministic report remains available
even when model generation or delivery fails.

Tests use fake clocks and injected queues/providers for duplicates, idempotency,
ambiguous sends, lease recovery, stale-token fencing, retries, terminal failures,
expiration, cross-session access, purge during inference, and HTTP status codes.
Moto tests also exercise durable storage across independent resource instances,
transactional stale-revision/session fencing, a partition exceeding 100 records,
interrupted-purge recovery, and HTTP submission through an emulated SQS queue to
the worker and result polling. They do not prove live SQS/Lambda delivery, DLQ
routing, production concurrency, or IAM permissions. Those require deployment
checks in the next slice. Per-session job admission limits and public rate/cost
controls remain work before exposing the demo publicly.

Handler tests also verify partial success responses, safe envelope errors,
malformed-body retry, duplicate delivery, lease contention, model retry/exhaustion,
expired/purged/missing-session acknowledgement, remaining-time admission, and
dependency reuse. They do not yet verify a Lambda Runtime Interface Client or a
built worker container; the separate developer-run container and empty-batch
deployment checks described above cover those startup boundaries.

## Private deployed end-to-end check

```sh
uv run python scripts/test_deployed_api.py phineas-api
```

This creates a synthetic session, checks deterministic analysis, submits an
approved fee question, repeats the same idempotency key, and polls the API for a
generated fee result. It can incur paid inference. Polling waits up to three
minutes, not the entire queue retry lifecycle. Timeout does not prove permanent
failure: retry visibility is twelve minutes. A finally block attempts purge on
failure or timeout and after successful generation. Cleanup can itself fail;
TTL remains fallback for abandoned records. A session created remotely whose
response is lost cannot be purged by this script because its ID is unknown.

On success the script also verifies that session and job access both return the
same `session_unavailable` response after purge. It prints only checkpoint
messages and safe failure reasons, never response bodies or identifiers. Local
tests exercise the checker with fake responses; they are not live AWS proof.
The test does not establish DLQ redrive or exactly-once inference.

### References

- [DynamoDB transactions and their 100-action boundary](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/transaction-apis.html)
- [Boto3 SQS SendMessage](https://docs.aws.amazon.com/boto3/latest/reference/services/sqs/client/send_message.html)
- [Lambda SQS partial batch responses](https://docs.aws.amazon.com/lambda/latest/dg/services-sqs-errorhandling.html)
