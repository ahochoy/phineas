# Bounded narrative model comparison

Compare Nova Micro and Sonnet 4.6 through per-invocation Harness overrides.
Haiku 5.5 was the original candidate but is unavailable to this AWS account;
its partial reports are preserved, not counted as completed quality evaluations.
The deployed Harness default, public API, queue, and worker remain unchanged.
The existing Harness execution role must authorize both inference profiles and
their destination model ARNs. This experiment does not establish that a model
is compatible with the Harness until a live invocation succeeds.

This is a developer-only evaluation exception to ordinary admission routing:
at most 36 direct paid Harness invocations, sequentially, with no SDK retries.
It does not consume or reset the public demo's 25-job daily allowance. It uses
only the bundled analysis-demo fixture, never uploaded files or stored sessions.
No new infrastructure is created. Each call has a fresh runtime session, one
iteration, no allowed tools, a 60-second invocation timeout, and 1,024 output
tokens. Runtime sessions may remain until their configured lifecycle expiry.

Both candidates receive the same prompt snapshot, aggregate cards, intent,
and anonymous merchant IDs. The six supported questions each run three times;
model order is interleaved within each question. Both use temperature 0.1.
Sonnet 4.6 thinking is off by default; no provider-specific thinking override
is sent. Equal numeric temperatures do not imply equal sampling behavior.
Compatibility must be confirmed by the first live Sonnet call;
the runner stops on access/transport failure rather than spending the rest
of the budget on an incompatible configuration. A completed response rejected
by validation is recorded as a quality failure and the evaluation continues.
The final exit status is nonzero if any answer was rejected; this does not mean
the run was incomplete. Check the completion line and report record count.

## Run

Preview without credentials or paid calls:

```sh
uv run python scripts/compare_narrative_models.py
```

Execute explicitly:

```sh
uv run python scripts/compare_narrative_models.py \
  --harness-arn "$(terraform output -raw phineas_harness_arn)" \
  --execute
```

The report is `evaluations/results/nova-sonnet-comparison.jsonl`, ignored by Git.
Existing files are never overwritten. A failed run may leave a partial report;
do not rerun blindly, since each execution has its own paid-call budget.
Console output contains model, intent, repetition, and safe status only.
It also reports allowlisted API/stream error codes, stop reasons, and whether
transport completed. It never prints provider error messages or response bodies.
Before the full comparison, diagnose compatibility with
one call rather than rerunning the whole comparison:

```sh
uv run python scripts/compare_narrative_models.py \
  --harness-arn "$(terraform output -raw phineas_harness_arn)" \
  --execute --probe-candidate \
  --output evaluations/results/sonnet-probe-1.jsonl
```

Use a new output filename for each deliberate attempt. A completed transport
with an unavailable explanation points to application validation; an API or
stream error points to an earlier failure. Empty usage alone proves neither.
The report intentionally contains synthetic aggregate facts and validated
explanations for human review; it is not production application logging.
Schema-valid rejected prose is retained only as `rejected_synthetic_draft` in
this ignored local review artifact, alongside the rejection code. This explicit
synthetic evaluation exception is not production logging or an accepted answer.
Malformed/oversized drafts are not retained. Do not send this runner private
inputs or publish its reports without review. Usage is captured when supplied by
Harness metadata; missing usage is unknown, not zero. Token counts are not
dollar costs: apply current model-specific Bedrock prices before comparing cost.

## Review and stop

Review each generated answer for factual support, natural partner-like voice,
repetition, relevant optional next steps, and preserved uncertainty. Especially:

- Fees: no invented cause, date, cadence, or receipts/order-history detour.
- Interest: no invented rate, cause, or comparison to an unseen total.
- Coverage: exclusions are not failed detections; cash movement is not spending.
- Subscriptions and duplicates: retain candidate/possible wording, and conditional
  annualization where relevant.

Structural validation passing is not a semantic quality pass. `human_review`
starts null deliberately. Compare all three repetitions, latency, unavailable
results, and usage; do not choose a model from a single favorable response.
Do not change the live default until the results are reviewed. No new evaluation
service, automatic model judge, or deployment pipeline is part of this slice.

References: [Harness invocation overrides](https://docs.aws.amazon.com/bedrock-agentcore/latest/APIReference/API_InvokeHarness.html),
[Sonnet configuration](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-anthropic-claude-sonnet-4-6.html).
