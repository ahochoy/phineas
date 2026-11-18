# Chat explanations, not report excerpts

## What changed

The findings panel remains deterministic. Chat previously asked Bedrock to pick
fact IDs, then displayed the fixed Python-rendered text. Raising temperature
could not make that contract conversational.

Chat now sends a server-owned `task=explain`, approved intent, and only the
relevant aggregate fact cards. The response contains one to three short prose
paragraphs, each citing existing fact IDs. The UI shows the prose as the answer
and the deterministic cards under an expandable Supporting findings disclosure.
No raw question, prior chat, statement rows, readable merchants, credentials, or
session capability is sent to the model. The six exact-phrase intents remain the
scope boundary. This is focused Q&A, not multi-turn model memory.

The existing `select` method and legacy highlight endpoint still work. The
provider's `explain` method shares the same bounded Harness transport: a fresh
runtime session, no tools, one iteration, 60-second invocation timeout, bounded
input/output, safe exception conversion, and no payload logging. Explanation
output is capped at 1,024 tokens; legacy selection remains capped at 512. The
Harness model cap is raised to 1,024 to accommodate the explanation JSON. Model
choice, temperature (0.1), session expiry, queue retries, and admission quotas
are unchanged. We should evaluate expression quality before changing randomness.

## Application validation and its limits

Strict JSON validation bounds text length, paragraph count, citations, and keys.
Every paragraph must cite known, unique fact IDs from its own request. Numeric
values must occur in that paragraph's cited sources. USD/$ amounts are checked
separately from remaining numbers, preventing a transaction count from becoming
a dollar amount and vice versa. Dates must match complete supplied ISO dates;
the fee aggregate has no dates or recurrence evidence, so none may be invented.

Further conservative checks reject exact finding-copy output, obvious contact
details/links/markup, anonymous merchant-ID disclosure, common unsupported fee
causes/advice terms, and missing uncertainty language for subscription/duplicate
candidates. Annualization must retain conditional/estimated language. Rejected
output is never logged or returned. Existing worker retries still end with a
safe terminal failure after exhaustion; deterministic analysis remains available.

These are heuristic safeguards, NOT semantic entailment proof. They do not prove
that every relation, causal implication, negation, named entity, currency phrase,
or nonnumeric statement is supported. Number-role separation also does not
establish every possible unit or temporal meaning. Fact citations are references,
not independent verification. Human review and live response evaluation are
required; do not advertise hallucination-free output or guaranteed grounding.

## Compatibility and rollout

`QuestionResponse.explanation` is additive and optional for old stored jobs. The
legacy narrative envelope remains populated with cited original cards, so older
API readers can still serve a valid result while ignoring the new field. The new
UI renders older results through its prior fact-based path; no old job is
rewritten or regenerated automatically.

The prompt has two contracts: requests with no task keep the original
`fact_ids`-only output; `task=explain` requests use paragraph JSON. This preserves
old workers while rolling forward. Deployment order:

1. Review/apply only the Harness prompt and model token-cap update in Terraform.
   Confirm the Harness update is ready before new explanation invocations.
2. Rebuild, smoke-test, push, scan, and pin the new worker image. Old workers keep
   using the compatible selector contract until replaced.
3. Restart the local web server so it imports the new Python response model.
   Before restarting, purge any active UI test session. This local app can read
   both formats and use the upgraded deployed worker.
4. Evaluate the live UI with fresh questions, not old succeeded jobs. Existing
   job replay intentionally returns the stored old answer.
5. Before publishing, rebuild/deploy the API image so its serializer retains the
   new explanation field (and the web report endpoint exists in cloud). An old
   API can serve the legacy cards but will omit the added explanation field.

Rollback: roll back the worker/API images first. The dual-contract prompt remains
compatible with older workers. Restore the old selector-only prompt last if
desired; new workers against it would reject its output, not silently accept an
old answer as a generated explanation. No table migration, backfill, purge, or
quota reset is required.

The ordinary smoke checker remains backward-compatible. After both new worker
and API images are deployed, require the new contract explicitly:

```sh
uv run python scripts/test_deployed_api.py phineas-api --require-explanation
```

That check consumes one daily question slot, verifies paragraph/citation shape,
and purges its synthetic session. It is not a semantic quality grade.

## Quality evaluation before sharing

Local reference-answer and rejection tests cover all six intents, unsupported
questions, empty findings, unknown/duplicate citations, extra keys, malformed or
oversized output, invented values/dates/causes/advice, number-role confusion,
uncertainty, privacy markers, old jobs, grounding fallback, and purge fencing.
Reference answers are synthetic fixtures, not observed model outputs or evidence
of live-model accuracy. No live evaluation has been performed by these tests.

After rollout, review a fresh answer to each supported question on analysis-demo
(six admitted jobs, potentially six model calls), then the empty fee case on
credit-card-demo (one admitted job, no model call expected). Keep answers in the
UI; record review outcomes/reason codes in notes rather than logging financial
content. Do not bypass admission by directly invoking the provider for this test.

Acceptance for each live answer:

- It directly answers the selected question and is not a copied finding.
- Any amount, count, date, comparison, cause, or recurrence claim is supported by
  the cited evidence. Fees must not acquire invented dates or charge types.
- Missing evidence is acknowledged; a possible duplicate/subscription remains
  uncertain, and annualization remains conditional rather than promised savings.
- Any next step is document review, not personalized financial advice.
- Supporting findings are separately accessible and match the explanation.
- Empty findings and unsupported questions do not invent a result or invoke AI.

Live acceptance is still pending. If a case fails, improve the prompt/validation
or evaluate a different model using the same cases. Do not accept higher
temperature as evidence of better reasoning or more accurate conclusions.

## Focused review regressions

Private UI review found two outputs that passed structural validation but failed
quality review: a fee answer appended receipts/order-history advice, and an
interest answer called the observed charge a small share of unseen overall
charges. The exact synthetic outputs, rejection reasons, and acceptable examples
are recorded in `evaluations/explanation-regressions.json`. The examples are not
fixed templates for generated answers.

The prompt now explicitly prohibits unseen-total comparisons and limits fee and
interest next steps to their own document-review context. This is a prompt-only
correction, not a new runtime semantic validator. Regression tests verify that
the corrected examples still pass the existing structural/numeric safeguards;
they do not prove the model will stop producing either issue. Recheck fresh live
answers after applying the Harness prompt change. The accepted subscription and
duplicate voice/uncertainty behavior should remain unchanged.
