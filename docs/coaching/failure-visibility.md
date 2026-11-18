# Failure visibility: delivery, job, and invocation

These answer different questions:

- **Invocation:** did the Lambda handler crash or time out? Lambda's Errors and
  Throttles metrics help here.
- **Delivery:** did this SQS record need another attempt? A partial-batch failure
  response can request a retry without making the invocation fail.
- **Job:** did the application persist a result or exhaust its attempts? A failed
  job can be acknowledged successfully because further retries are not useful.

The queue is another perspective: age and backlog show stalled processing, and
the DLQ shows deliveries that exhausted transport retries. A terminal application
failure does not have to reach the DLQ.

## Implemented locally

`QuestionWorker.process` returns a fixed outcome; the SQS entrypoint emits one
plain JSON line per processed or deferred record:

```json
{"event":"question_delivery","schema_version":1,"outcome":"completed","duration_ms":385}
```

The allowed outcomes are:

- `completed`: a result was persisted, including deterministic unsupported-intent
  responses; this does not necessarily mean a model was invoked.
- `terminal_observed`: already-successful work was acknowledged without repeating it.
- `terminal_failed`: a failed job was recorded or observed, including exhausted
  application attempts or a deadline failure detected by the store.
- `invalidated`: missing, expired, purged, or mismatched work was discarded.
- `retry_required`: the worker requested another delivery (including active leases).
- `invalid_message`: the message body failed validation.
- `store_unavailable`: the session/job storage boundary reported unavailable.
- `unexpected_failure`: another exception crossed the transport boundary.
- `deferred`: insufficient invocation time remained to start this record.

Only these labels, a schema version, and nonnegative elapsed milliseconds are
emitted. No message/job/session identifiers, intent, amounts, financial facts,
payloads, exception strings, or tracebacks are included in these records. Invalid
outer envelopes still raise the fixed `invalid_sqs_envelope` error before work;
they have no per-record outcome. Dependency-initialization failures and hard
runtime termination also require platform-level monitoring.

This uses ordinary JSON logs, not EMF or direct PutMetricData. Terraform metric
filters can turn selected log events into metrics without adding SDK calls,
permissions, or a telemetry dependency to the worker. Custom metrics and alarms
still have their own costs. Keep dimensions low-cardinality; never use capability
IDs as dimensions.

## Limits and evidence

Delivery counts are observations, not exactly-once unique-job counts: duplicate
deliveries can repeat `terminal_failed`. Timing covers record handling, not total
queue wait or end-to-end job latency. A crash may prevent an outcome from being
emitted. Failures only discovered by API polling may not be observed by a worker.
Combine these signals with native Lambda and SQS metrics; silence is not proof
that all jobs succeeded.

Local tests cover success and duplicate delivery, terminal failure after three
attempts, repeated terminal-failure observations, invalidation, malformed bodies,
transient/unexpected failures, and time-budget deferral. Captured output is checked
for sensitive values. These are local tests, not deployed alarm proof.

## Next coached deployment steps

1. Rebuild the **worker** image, run its local native-Lambda smoke check, push a
   new immutable tag, and review its ECR scan. See
   [worker-container.md](worker-container.md). No API image change is needed.
2. Pin `worker_image_digest` to the reviewed digest in the private tfvars file.
   Review a plan that changes only the worker image, then apply it.
3. Run the existing deployed async happy-path check and verify safe outcome
   records in the worker log group. Empty-batch smoke tests intentionally emit
   no per-record outcomes and do not prove this instrumentation.
4. Agree alarm thresholds/evaluation windows and a notification destination.
   Add metric filters and alarms incrementally; test notification delivery and
   controlled synthetic failure paths before calling the gate complete.

Do not expose public ingress or redrive a DLQ blindly as part of this slice.
The admission pause blocks new jobs, not already queued worker execution.
