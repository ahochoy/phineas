# Public synthetic demo gates

V1 is deployed as an invited, shared-password synthetic demo. See the
[V1 release checkpoint](releases/v1.md) for the shipped scope, evidence, and
limitations. The sections below distinguish local proof from deployed checks;
they are not a claim of production certification or a comprehensive security audit.

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

## 2. Public admission and rate/cost controls — deployed

The agreed allowance is 25 new jobs per UTC day across all sessions. The code
now atomically reserves the shared day slot, the session slot, and the job while
checking an operator admission-pause record. Idempotent recovery takes no extra
slot; purge never refunds the day count. Missing control fails closed. The
developer confirmed deploying the control record disabled and the updated API
image. Deployed paused checks passed, followed by enabling the control through
Terraform and passing the full generated-fee path. The shared 25/26 boundary and
UTC rollover remain emulator-tested, not live load proof. See
[global-admission.md](coaching/global-admission.md) for keys, rejection behavior,
pause semantics, UTC rollover, tests, and the coached rollout sequence.

Cloudflare Workers now provides the browser origin and route-limited proxy.
Shared reviewer-password access is enforced before session creation, reports,
questions, and polling; the separate origin credential is checked by API Gateway's
Lambda authorizer. Missing/incorrect origin credentials were rejected in deployed
checks. Gateway throttles and edge per-IP limits protect the request paths; purge
remains available with the session capability after reviewer access expires.
The admission pause does not stop queued/running inference. These controls are
not hard dollar caps or identity verification. See
[Cloudflare deployment](coaching/cloudflare-deployment.md).

## 3. Failure visibility and recovery — scoped V1 proof complete

Safe delivery outcome instrumentation is deployed. The developer confirmed
terminal-failure log/metric/alarm notification delivery and a visible synthetic
DLQ-message alarm through SNS email. The test message was removed and the queues
were checked empty. This is not proof of automatic exhausted-retry redrive.
Native error/throttle/backlog alarms and additional observability expansion were
explicitly deferred for V1. See
[failure-visibility.md](coaching/failure-visibility.md) for the outcome contract,
its counting limitations, and the coached rollout.

For future operational expansion, consider safe worker outcomes, terminal job failures, Lambda errors/timeouts and
throttles, queue age/backlog, and DLQ arrivals. Partial-batch failures may be
returned from an otherwise successful Lambda invocation: Lambda Errors alone
will not show every failed job. Record counts/timings/reason codes, never queue
bodies, bearer session IDs, statements, or financial facts. Plan notification
delivery and test it; an alarm without a recipient is not an operational handoff.
Test transient failures, exhausted retries, and DLQ handling without unsafe
redrive into expired sessions.

## 4. Vulnerability and deployment review — V1 artifact reviewed

The API was moved from Debian to the patched Amazon Linux 2023 base family used
by the worker. The developer confirmed a completed ECR scan with no reported
findings for API digest
`sha256:455e8d208a99cf803d1b4b2165b3533535ebed0258e8434147cdad2933628c1f`,
then deployed it and passed private end-to-end checks including explanations.
The worker's patched scan was also clear at its checkpoint. These are historical,
point-in-time results, not permanent assurances. Rebuild/re-scan when base or
dependency advisories change, and pin reviewed deployment artifacts by digest.

### Historical Debian artifact (superseded, not the public API image)

At the 2026-11-16 global-admission checkpoint, API digest
`sha256:6cb7b673e5b1f2f8243dd3cc78bd3948bff141c95b50097e9e0affe0f986604c`
reported two high, ten medium, three low, and one undefined finding. Comparing
stored scans identified the additional medium as CVE-2026-125709 in libstdc++.
The runtime contains libstdc++6 14.2.0-19; Debian listed it as unfixed when
reviewed. No direct C++ file-stream use was identified in application code,
but transitive reachability was not ruled out. The private synthetic testing
assessment was retained; this is an unresolved finding, not public approval.
See the [Debian tracker](https://security-tracker.debian.org/tracker/CVE-2026-125709).

## 5. Public surface and privacy checks — deployed checks recorded

Private-origin checks passed authentication rejection/acceptance, no-store,
synthetic preview, blocked docs/OpenAPI, report, purge, and post-purge rejection.
The public browser flow and mobile layout were exercised by the developer.
An empty DELETE stream caused an edge rejection; the fix was regression-tested,
deployed, and confirmed with a public HTTP 204 purge. The developer subsequently
confirmed that shared-password access works. Guided buttons replace free-text
input so V1 does not promise natural-language intent recognition.

Body/route limits, safe error handling, password token signatures/expiry, and
many lifecycle races have local tests; this is not live distributed abuse/load
proof. Worker request logging is disabled and gateway access logs include only
request ID/status. Providers still process operational network metadata.

## Stop condition

The scoped V1 invited synthetic demo is available. Preserve its stated limits;
do not expand into uploads, identity, retention, classifiers, or new analysis
before an explicit follow-up release decision. Remaining ongoing work is normal
maintenance: monitor alerts, review costs, rotate shared access when appropriate,
and revisit artifact vulnerabilities. No further infrastructure expansion is a
V1 feature gate.
