# Bounded question policy v1

Discover supported prompts with `GET /questions/suggestions`. Send one to
`POST /sessions/{session_id}/questions` as `{"question": "Explain fees"}`.

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
AWS. This initial interface is intended for suggested-question buttons, not broad
natural-language understanding. It has no conversational history or follow-up
resolution. Laya remains a candidate for an evaluated future intent classifier.

For approved intents the application filters deterministic cards to that topic
before calling the existing narrative provider. User question text is never sent
to the model; requests cannot supply model, tools, prompt, or skill overrides.
Model-selected IDs are validated against the filtered cards, preventing selection
of another topic's findings. Empty findings skip generation; they mean no findings
were detected by the current policy, not proof that no relevant charges exist.

Responses include all relevant deterministic `facts` plus the optional selected
highlights. Provider failure leaves the facts available. An approved overview may
include all supported findings and coverage. No merchant names, transaction rows,
source descriptions, or evidence IDs are returned. This response is still sensitive
aggregate financial information and must not be logged.

Successful authorized questions, including unsupported ones, refresh the idle
window as specified in the data contract. Malformed requests do not. Access is
checked again after generation to honor purge or expiration during a model call.
No Terraform or prompt update is required for this slice. Before public deployment,
apply request throttling and the logging controls described in the Bedrock runbook.
