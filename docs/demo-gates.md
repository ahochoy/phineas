# Gates before a public synthetic demo

The deployed async happy path has passed private testing. That is not approval
for public exposure. Keep hosted inputs bundled and synthetic, and keep the
deployment private until the gates below have evidence.

## 1. Bounded question admission

Deployed and verified by the developer against the private API:

- At most 10 distinct question jobs may be created in one session's lifetime.
  Ten is an initial demo policy, not a measured product requirement or cost quota.
- All intents count, including unsupported questions. Completed, failed, and
  deadline-exceeded jobs keep their slots. This bounds record growth and avoids
  repeated failures becoming an unlimited model retry budget.
- Reusing a request UUID for the same intent returns the existing job, even when
  the session has used all slots. A different intent still returns 409.
- The next distinct submission returns 429 `question_job_limit_reached`, without
  sending a queue message or refreshing activity. There is no Retry-After header
  because time does not refill this lifetime allowance. Existing jobs, analysis,
  and purge remain available while the session is otherwise valid.
- DynamoDB atomically increments `question_job_count` in METADATA and creates the
  job. The conditional increment requires an unexpired, non-purging session and
  remaining capacity. Revision-controlled worker updates do not increment it.
- The local store applies the same policy under its lock.
- When async service is configured, `/questions` and `/narrative` refuse direct
  synchronous generation with 409 `async_questions_required`. Without async
  configuration, local/private synchronous behavior is unchanged.

### Deployment and compatibility

New sessions initialize the counter to zero. Old session metadata has no counter:
reading, polling, replaying existing request IDs, and purge still work, but new
job creation fails closed with a safe store-unavailable response. We do not assume
that a missing counter means no older jobs exist. Let old sessions expire (at
most four hours) or explicitly purge them during the private rollout; do not
backfill a zero counter over existing jobs.

The API image has been rebuilt, scanned, and deployed. No DynamoDB table change or
additional IAM permission is required: the API already has UpdateItem and PutItem
on this table. The worker never creates new jobs, so its existing transactional
write path remains compatible. The API role's Harness invocation grant was
removed in a separately reviewed Terraform step. The worker's grant remains.

Local proof covers the limit, independent sessions, idempotent replay at capacity,
duplicate-write rollback, a competing last-slot writer, terminal failures,
old metadata, HTTP 429/no-store behavior, and synchronous bypass rejection.
The deployed admission check passed. To repeat it:

```sh
uv run python scripts/test_deployed_api.py phineas-api --admission-only
```

The checker creates a fresh synthetic session, verifies blocked synchronous
routes, submits ten unsupported questions, replays the first request, and checks
the eleventh distinct job returns 429. It verifies analysis/polling remain usable,
then attempts purge in a finally block and checks post-purge rejection. The
expected passing path requests no model output, but uses Lambda, SQS, and
DynamoDB resources. It prints safe checkpoints only. This sequential deployed
test does not establish race safety or global admission limits. Run the normal
script separately to recheck a generated fee answer. The developer reran that
full async check after removing the API grant: generated fee output, idempotency,
purge, and post-purge rejection all passed.

### Limits of this gate

This is not a global spending cap. Callers could create new sessions, flood
polling, or repeatedly re-enqueue an existing pending job through retries. Those
replays do not create extra job slots but still consume API, queue, and database
resources. Worker concurrency two limits parallelism, not total work or spend.
Budgets notify; they do not stop requests. Do not label this gate sufficient for
anonymous public access.

## 2. Public admission and rate/cost controls — pending

Choose the public ingress/access boundary before exposing it. Protect session
creation, new jobs, pending-job re-enqueues, and polling. Add an operator kill
switch and a global admission allowance for paid work if a firm demo spending
boundary is required. Define rejection and outage behavior. Gateway throttling
alone must not be represented as a hard financial cap. No public URL or access
model is selected by the first gate.

## 3. Failure visibility and recovery — pending

Track safe worker outcomes, terminal job failures, Lambda errors/timeouts and
throttles, queue age/backlog, and DLQ arrivals. Partial-batch failures may be
returned from an otherwise successful Lambda invocation: Lambda Errors alone
will not show every failed job. Record counts/timings/reason codes, never queue
bodies, bearer session IDs, statements, or financial facts. Plan notification
delivery and test it; an alarm without a recipient is not an operational handoff.
Test transient failures, exhausted retries, and DLQ handling without unsafe
redrive into expired sessions.

## 4. Vulnerability and deployment review — pending

The worker's patched image scan was clear at its checkpoint. The API retained
two high glibc findings and additional medium/low findings for private testing.
Review current vendor fixes and all outstanding findings before public launch;
record scope, evidence, residual risk, and a revisit trigger. A historical scan
is not a permanent clean bill of health. Pin deployed artifacts by digest.

## 5. Public surface and privacy checks — pending

Verify synthetic allowlisting, request/body limits, generic validation errors,
session expiration/purge, response no-store, safe application/platform logs, and
the chosen browser origin/access boundary. Decide which docs and synchronous
legacy routes should be exposed. Verify that a proxy does not log capability IDs
embedded in URLs. Do not expose the service merely because happy-path smoke
tests pass.

## Stop condition

This slice stops at privately deployed and verified per-session admission
controls and the API IAM reduction. It does not create public ingress, choose
authentication, or claim the other gates are complete. Infrastructure work
remains a coached Terraform exercise.
