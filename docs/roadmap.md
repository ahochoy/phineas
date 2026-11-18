# Phineas release roadmap

Agreed 2026-11-17. Product purpose: help people understand their spending and
notice changes worth acting on, without unnecessary exposure of financial data.
This roadmap supersedes the original MCP delivery requirement.

## V1: public synthetic statement demo

Freeze feature expansion and model evaluation. Retain Nova Micro. Visitors can
preview an approved synthetic statement, run existing deterministic analysis,
ask supported questions, and purge their short-lived session. This is bounded
Q&A, not arbitrary conversation, bank integration, or personal financial advice.

The public demo is deployed at [phineas-finance.hochoy.dev](https://phineas-finance.hochoy.dev)
with Cloudflare Workers in front of the authenticated AWS origin. The developer
verified public question buttons and mobile behavior, and confirmed HTTP 204
purge after fixing the empty DELETE-body-stream edge case. Private deployed
checks also cover async questions, idempotency, and post-purge rejection; origin
checks cover authentication, preview, report, purge, and blocked docs. The V1
buttons-only interface and shared reviewer-password gate are implemented; the
developer confirmed the deployed password flow works. See the
[release checkpoint](releases/v1.md).

The launch checklist is retained below for operational reference; these are not
all pending implementation tasks. Detailed controls and evidence limitations
are in [Cloudflare deployment](coaching/cloudflare-deployment.md).

1. Build, scan, pin, and privately verify the latest API image, including report,
   sample preview, and explanation serialization.
2. Publish the frontend on Cloudflare and connect the same-origin `/api` path.
3. Protect public ingress, including session creation, question submission,
   re-enqueue paths, and polling. Prevent bypass of edge controls. Shared daily
   admission and concurrency limits are not complete abuse protection or hard
   monetary caps. Do not expose an unprotected origin as an intermediate step.
4. Review current container vulnerabilities and public response/body limits,
   capability handling, route exposure, caching, and platform/application logs.
   Review or explicitly accept residual risks before launch; do not equate a
   historical clean scan or passing happy path with public approval.
5. Exercise the actual HTTPS URL: preview, create, analyze, ask, poll, purge,
   post-purge rejection, unsupported questions, limits, failure handling, and
   mobile/keyboard usability. Record evidence and an operator pause procedure.

Tasks may interleave: security review precedes public exposure, not follows it.
Infrastructure changes remain small, reviewed Terraform coaching steps. No more
telemetry expansion is required unless a specific launch blocker is discovered.
Terminal-failure and DLQ alerts plus SNS email delivery have been tested by the
developer. Existing coaching notes may describe those historical steps as pending.

Completion means a working shareable URL with the above gates verified, not a
claim that the original broader finance-analysis specification is complete.

## V2: understand category spending over time

Evaluate a classifier such as Laya for spending categories, separate from
transaction kinds. Aggregate purchases from different merchants into categories
and calculate month-over-month USD totals and changes in deterministic Python.
Use richer datasets with hundreds of transactions spanning approximately three
months. Define refunds, partial months, unknown categories, and comparison
denominators before interpreting a rise or fall in spending.

Review classification inputs and privacy explicitly: removing merchant names
also removes useful category signals. Do not silently send raw descriptions or
readable merchants to a model. More realistic data does not authorize real bank
statements in fixtures or the public demo. Start with realistic synthetic data;
any private real-data workflow needs a separately reviewed boundary.

Current storage accepts at most 99 transactions plus session metadata in its
atomic write path. Supporting hundreds requires a deliberate persistence and
partial-failure design, not just a larger fixture or raised validation limit.
Evaluate classifier quality, uncertainty, provenance, latency, and cost against
a deterministic baseline before making Laya a dependency. Hosting remains a
decision backed by evidence, not a release promise.

## V3: notice anomalies and prompt useful action

Add subscription price increases and other evidence-backed changes/anomalies.
Surface specific, cautious nudges such as a possible repeat charge or a change
in a recurring amount. Preserve the distinction between a candidate and a
confirmed error, and never imply that Phineas has taken action on an account.

Within-session nudges fit the current lifecycle. Background monitoring across
months, push/email notifications, or readable merchant names would change the
retention, identity, consent, and privacy model. They require a new decision;
this roadmap does not authorize accounts, long-term records, or notifications.

## Out of committed scope

MCP is dropped from the committed roadmap. It can be reconsidered only for a
concrete integration use case. Laya, category trends, and new anomaly detection
are not V1 launch gates. Sonnet evaluation is stopped; its local reports remain
historical evidence, not a deployed model choice.
