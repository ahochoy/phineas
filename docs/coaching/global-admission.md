# Shared daily admission and operator pause

## The decision

The demo accepts at most **25 new question jobs per UTC day**, shared by all API
instances using the same sessions table. The per-session lifetime limit remains
10. Every new job counts, including unsupported questions. This limits admitted
work, not exact dollars or model calls per calendar day.

Reusing a request UUID with the same session and intent returns its admitted job,
without another session or daily slot. That remains true while paused or at
capacity, so an ambiguous queue send or client timeout can recover. A pending
replay can still send another queue message. A different intent remains a conflict.

Slots are reserved when the job record commits, before sending to SQS. Failed
queue sends, failed model calls, job deadlines, expiration, and session purge do
not refund slots. Refunding on an uncertain outcome could permit repeated paid
work. Recover using the original request UUID, not a new one.

## Four actions, one transaction

For a new DynamoDB job, one transaction:

1. Checks that the operator control is enabled and uses schema version `1`.
2. Increments the sampled UTC day's counter only while it is below 25.
3. Increments the session counter only while the session is active and below 10.
4. Creates the job only if its request UUID is new within that session.

Either all four actions commit, or none do. A competing last-slot writer,
duplicate creation, pause transition, or expired/purging session cannot partially
consume counters. Post-failure reads identify safe rejection reasons; they never
authorize admission. Already admitted worker claims/results retain their existing
revision and session fencing and do not touch global controls.

## Operational records, not financial records

The existing table gains two operational key shapes:

| Purpose | `pk` | `sk` | Other attributes |
| --- | --- | --- | --- |
| Operator control | `CONTROL#QUESTION_ADMISSION` | `CONFIG` | `schema_version = "1"`, `enabled` boolean |
| UTC daily count | `ADMISSION#YYYY-MM-DD` | `COUNTER` | `admitted_jobs` integer, `expires_at` epoch seconds |

These records contain no session identifiers, user questions, merchants, or
financial data. Session purge queries only its `SESSION#...` partition and leaves
operational counts intact. They must not be given session recovery semantics.

The control record has no TTL. Missing or invalid control fails closed with the
existing safe store-unavailable response. The API never automatically creates
or enables it. A disabled control yields 503 `demo_admissions_paused` for new jobs.
A full daily counter yields 429 `demo_daily_job_limit_reached`. Rejected new jobs
do not enqueue messages or refresh session activity. If multiple limits apply,
the per-session rejection may take precedence.

Daily counters are created by application transactions, not Terraform. Do not
delete or reset today's counter as part of deployment or recovery. A new UTC date
selects a different key; TTL is not the reset mechanism. Cleanup is scheduled for
midnight two dates after the counted date, keeping a closed day at least another
full day. Existing counter expiry must match that policy before incrementing it.
Day selection uses server-owned job creation time, not client data or local time.
Requests begun near midnight may commit against the prior sampled day.

## Pause is admission-only

Disabling the control stops new jobs whose admission transaction observes that
state. It does not cancel jobs admitted before the change, stop model calls in
flight, block idempotent recovery of those jobs, or disable deterministic
analysis, polling, session creation, or purge. Worker shutdown is a separate
emergency action with its own queue/lease implications.

The in-memory reference applies the same allowance under its lock and has an
explicit local enabled default and `set_admissions_enabled()` method. It is
process-local, not a substitute for distributed DynamoDB enforcement. There is
no public endpoint to change controls or reset counters.

## Rollout boundary

The developer confirmed applying the operator control initially disabled and
deploying the global-admission API image. The deployed paused check passed:
new jobs were rejected while deterministic analysis, purge, and post-purge
rejection remained correct. The control was then enabled through a separately
reviewed Terraform apply, and the full generated-fee check passed, including
submission, idempotent replay, SQS/worker/AgentCore processing, and purge.
The enabled state remains deliberately managed through Terraform. Do not mix
application daily counters into Terraform-managed data or reset them during apply.

The API already has the necessary GetItem, UpdateItem, PutItem, and
ConditionCheckItem permissions on this table. No table/index or worker IAM
change is required for this slice. The control was provisioned before deploying
the new API image. Existing workers remain compatible because they do not
create jobs. Enabling the control has no protective effect on an older API image
that does not implement this check, so keep the rollout private.

The existing `--admission-only` smoke test spends **10 daily slots** on a successful
run; the generated-fee smoke test spends one. Purge does not refund them. Do not
exhaust or reset the live demo counter just to prove a boundary: emulator tests
cover 25/26, races, and UTC rollover. Design deployed checks with the remaining
allowance in mind and keep their outcome/output operational-only.

### Verify the disabled control first

```sh
uv run python scripts/test_deployed_api.py phineas-api --paused-only
```

This creates a fresh synthetic session and requires exactly 503
`demo_admissions_paused` for a new unsupported question. A generic store error,
quota rejection, or accepted job does not pass. It then checks deterministic
analysis, attempts purge in a finally block, and verifies post-purge rejection.
The expected passing path admits no job and consumes no daily slots or model
inference, though Lambda/database requests still apply. This mode does not
change the operator control and cannot be combined with `--admission-only`.
Its local tests verify routing, safe output, exact response matching, cleanup,
and no queue sends/provider calls against the local API. The developer also
confirmed all deployed paused checkpoints passed before enabling admissions.

## Evidence and remaining gates

Tests cover shared quota across sessions and independent DynamoDB instances,
purge without quota refund, duplicate-write rollback, competing last-slot writers,
concurrent same-UUID creation, pause between read and commit, pause/resume,
already-queued work during pause, ambiguous commit/send recovery, missing/invalid
control, invalid daily records, UTC rollover without TTL cleanup, and HTTP status
and no-store behavior. The developer's deployed paused/enabled checks establish
those happy paths. The 25/26 boundary, UTC rollover, failure recovery, and races
remain emulator-tested, not live load or fault-injection proof.

This still does not bound session creation, polling, repeated pending-job sends,
or other AWS traffic. It does not supply authentication, ingress throttling, a
hard financial ceiling, worker shutdown, or alarms. The public demo remains
gated on those decisions and the outstanding vulnerability/privacy review.

Reference: [DynamoDB transactional all-or-nothing behavior](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/transaction-apis.html).
