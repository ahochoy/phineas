# Bounded question policy v1

Discover supported prompts with `GET /questions/suggestions`. The deployed async
path uses `POST /sessions/{session_id}/question-jobs` with a request UUID and
question, then polls `GET /sessions/{session_id}/jobs/{job_id}`. The synchronous
`/questions` route remains for local/private operation without async configuration
and is blocked when the async service is configured.

The deterministic classifier accepts these exact phrases after case folding,
whitespace normalization, and removing trailing question/exclamation/full-stop
punctuation:

- Show an overview
- Show subscriptions
- Explain fees
- Explain interest
- Show possible duplicates
- Explain classification coverage

Other phrasing returns intent `unsupported` and a fixed response without invoking
a generative model. Async admission, storage, and delivery can still use AWS.
This initial interface is intended for suggested-question buttons, not broad
natural-language understanding. V1's public UI exposes buttons only; it does not
invite custom questions that the baseline cannot classify. The API still enforces
scope independently of the UI. It has no conversational history or follow-up
resolution. Laya remains a candidate for an evaluated future intent classifier.

For approved intents the application filters deterministic cards to that topic
before calling the existing narrative provider. User question text is never sent
to the model; requests cannot supply model, tools, prompt, or skill overrides.
New chat responses use generated explanatory paragraphs with validated citations
to the filtered cards. Empty findings skip generation; they mean no findings
were detected by the current policy, not proof that no relevant charges exist.

Responses include all relevant deterministic `facts`, an optional `explanation`,
and the compatible selected-highlights envelope. Existing stored jobs without an
explanation remain readable. Direct-call provider failure leaves facts available;
async workers retry unavailable generation and can eventually mark a job failed,
while the separate deterministic analysis remains accessible. An approved overview may
include all supported findings and coverage. No merchant names, transaction rows,
source descriptions, or evidence IDs are returned. This response is still sensitive
aggregate financial information and must not be logged.

Successful authorized questions, including unsupported ones, refresh the idle
window as specified in the data contract. Malformed requests do not. Access is
checked again after generation to honor purge or expiration during a model call.
The conversational explanation change requires a dual-contract Harness prompt
update and worker/API rollout. See
[grounded-explanations.md](coaching/grounded-explanations.md) for validation,
limitations, compatibility order, rollback, and live quality acceptance. Citations
and lexical/numeric checks do not prove complete semantic grounding. Before public
deployment, retain request controls and the logging/privacy boundaries.
