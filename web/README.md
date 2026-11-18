# Phineas web interface

Buildless HTML, CSS, and JavaScript modules, preserving `docs/brand-spec.md`.
The interface calls the existing REST application at the same-origin `/api`
prefix. It never invokes AWS directly or contains AWS credentials.

The hosted Worker requires a shared demo password before analysis or questions.
The password form obtains a signed four-hour access token held in tab memory,
not cookies or browser storage. Preview remains public. Refreshing requires
unlocking again; purge remains available with an existing session capability.
The repository-only FastAPI web host has no edge-auth endpoint and continues
without this gate for local coaching. The Worker enforces authentication
independently of UI controls. See [password setup](../docs/coaching/demo-password.md).

## Run locally with the deployed worker

Stop the earlier static-only preview server if it still uses port 5173. From the
repository root, with your local AWS login active:

```sh
PHINEAS_SESSIONS_TABLE="$(terraform output -raw sessions_table_name)" \
PHINEAS_HARNESS_ARN="$(terraform output -raw phineas_harness_arn)" \
PHINEAS_QUESTION_QUEUE_URL="https://sqs.us-east-2.amazonaws.com/927161114143/phineas-question-jobs" \
AWS_REGION=us-east-2 \
uv run uvicorn phineas.web:create_web_app --factory \
  --host 127.0.0.1 --port 5173 --no-access-log --no-proxy-headers
```

Open <http://127.0.0.1:5173>. This is local-only hosting with the real DynamoDB,
SQS, and AgentCore workflow. Questions consume the daily allowance and can invoke
Bedrock. AWS credentials stay in the server-side SDK credential chain. Do not
bind this development server to a public interface.

To exercise deterministic session/analysis/purge behavior without AWS, omit the
four environment settings. Async questions then return an explicit configuration
error; there is no synchronous-generation fallback or fake AI response.

## User flow and privacy

Expand **Preview records** beneath the sample picker to inspect every
source CSV row and column in a read-only spreadsheet-style table. Changing the
selected sample changes the preview; the table scrolls horizontally on small
screens. Preview errors have a separate retry action and do not block analysis.

`GET /samples/{sample_id}/preview` returns only allowlisted bundled synthetic
fixtures, never session transactions, arbitrary paths, or uploaded content. It
does not create/refresh a session, reserve a job slot, call AWS, or invoke a model.
Readable synthetic descriptions are intentionally shown in this public source
preview; the sanitized analysis/model boundary is unchanged. The table is not a
new general-purpose statement viewer or editable spreadsheet.

Everyday credit card contains 50 records spanning January–March 2026, with
same-day purchases, recurring activity, payments, a refund, fees, and interest.
Each of the three months has a card payment, a USD 3.00 monthly fee, and a
month-end interest charge. Interest amounts are illustrative, not calculated
from an APR or balance: January USD 2.85, February USD 3.40, March USD 1.25.
A simpler statement contains 10 records and remains a clean control without
detected subscriptions, duplicate purchases, fees, or interest. Both views use
the same server-owned fixtures as analysis, not separate table mock data. Start
a fresh session after a fixture change; existing sessions keep their original
sanitized records. The deployed worker and API should ultimately use matching
code/image versions, particularly because the worker owns the analysis policy.

Choose a sample and Start analysis. Read the cash-movement summary and findings,
then choose a question button. V1 intentionally has no free-text composer: the
exact-phrase baseline supports six guided questions, not paraphrases or arbitrary
chat. The API retains its bounded question field and rejects unsupported intents;
removing the composer does not replace the server-side scope boundary.

The browser polls question jobs every two seconds for up to three minutes.
Explicit Retry reuses the request UUID after ambiguous submission or a timeout;
terminal failures are not automatically resubmitted. There is one active question
per tab. No question is submitted automatically when a sample is selected.

End session & purge calls the real DELETE endpoint. Failed deletion retains the
capability and asks the visitor to retry, never claiming success. Admission limits
and pauses leave findings and purge available. Skipped/unavailable AI selection
is labeled honestly, with deterministic facts shown when available.

Session access and chat live only in tab memory, not browser storage, cookies,
address-bar URLs, or application logs. Refresh loses access without immediately
deleting backend records; server expiration still applies. Browser expiry
estimates clear the display but are not authorization. Timers do not send
heartbeats. Purge/expiry invalidate late responses so answers cannot repopulate
the display afterward.

## Implementation boundary

`phineas.web` mounts the configured API and only the `web/` directory. It adds
no-store, no-referrer, nosniff, and a same-origin CSP. Keep access logs disabled
as shown because capabilities appear in API request paths. This slice changes no
CORS, public ingress, Lambda deployment, or Cloudflare deployment. The old preview
snapshot and preview-only copy are removed.

`GET /sessions/{session_id}/report` combines the existing analysis with Python's
existing fact-card projection. It invokes no model and returns no raw rows.
Financial logic is not duplicated in JavaScript.

## Checks

New answers show generated explanatory prose, with original facts in Supporting
findings. Old job results still render their fact-based answer. See
`docs/coaching/grounded-explanations.md` for the required prompt/worker/API rollout
and live quality review; reloading the page alone cannot upgrade a stored answer.

```sh
uv run pytest -q
uv run pyright
node --test tests/web/client.test.mjs
node --check web/app.mjs
```

Python integration tests exercise REST lifecycle and grounding with in-memory
storage and a controlled provider/queue. Node tests exercise the actual API client
and lifecycle controller with scripted responses: polling, UUID reuse, expiry,
purge races/failure, quotas, and deterministic fallback. These do not prove browser
rendering or the deployed cloud path. Exercise the page with the deployed worker
separately before public deployment.
