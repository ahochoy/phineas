# Bedrock integration: grounded highlight selection

The application builds an explicit list of fact cards from deterministic findings.
Each card contains a local fact ID, an optional anonymous merchant ID, and a
Python-rendered explanation with precomputed values. The projection does not
serialize the entire report and cannot include raw descriptions, merchant names,
evidence IDs, individual rows, or the application session credential.

AgentCore runs Nova Micro to select and order up to five cards. The returned JSON
must contain only `fact_ids`. Pydantic rejects other keys or malformed output;
application code rejects unknown or duplicate IDs. The API then returns the
original cards, never model-written financial claims. This first mode is labeled
`selected_facts_v1`: it is grounded selection, not free-form narrative generation.
It proves integration and output validation; it does not yet demonstrate natural
language synthesis or question answering. A later free-text mode needs separate
grounding evaluation and must not inherit this mode's stronger guarantee.

## Infrastructure exercise

In `harness.tf`, replace the existing smoke-test `system_prompt` block with:

```hcl
  system_prompt {
    text = file("${path.module}/prompts/narrative.txt")
  }
```

`file()` reads UTF-8 prompt text on the Terraform machine. `path.module` locates
the directory containing the Terraform module, avoiding assumptions about the
terminal's working directory. The text is sent to the Harness configuration and
stored in Terraform state; prompts must contain no secrets or statement data.

Run `terraform fmt`, `terraform validate`, and `terraform plan`. Review the plan
before applying: expect an in-place Harness update, with no role expansion or
resource destruction. The prompt may be redacted as sensitive in the plan, so
review `prompts/narrative.txt` itself. Retain Nova Micro, memory disabled, and
the existing token/time/lifecycle limits. The client further limits each request
to one iteration, 512 tokens, and 60 seconds, with an allowlist that matches no
tools. Request callers cannot provide model, tool, prompt, or skill overrides.

After applying, verify readiness:

```bash
aws bedrock-agentcore-control get-harness \
  --region us-east-2 \
  --harness-id "$(terraform output -raw phineas_harness_id)" \
  --query 'harness.{status:status,version:harnessVersion}'
```

Do not invoke until status is READY. No separate create-harness call is needed:
Terraform owns the existing resource. The AgentCore CLI is another provisioning
path, but should not independently deploy a second copy of this Terraform resource.

## Local application connection

The SDK uses the local AWS credential chain; the ARN is configuration, not a key.
Set the environment before starting (or restarting) Uvicorn:

```bash
export PHINEAS_HARNESS_ARN="$(terraform output -raw phineas_harness_arn)"
export AWS_REGION=us-east-2
uv run uvicorn phineas.api:app --reload --host 127.0.0.1 --no-access-log
```

In `/docs`, create an `analysis-demo` session. Request its deterministic analysis,
then POST `/sessions/{session_id}/narrative`. Inspect `narrative_status`:

- `generated`: the provider returned a valid selection, rendered from known facts.
- `skipped`: no Harness ARN was configured; no AWS call was made.
- `unavailable`: AWS, stream completion, response validation, or size limits failed.
  The deterministic analysis remains available.

Missing or invalid session IDs are rejected before AWS invocation. Session access
is checked again after generation so purge or expiry during a call prevents the
response from releasing financial results. Purge cannot retract aggregates already
sent to AWS during an in-flight call.

The adapter buffers text events until a successful `end_turn`, closes the stream,
and rejects error events, tool use, incomplete output, or output over 8192 characters.
There is no automatic retry, to avoid duplicate paid work. Input is bounded to
100 cards and 32000 UTF-8 bytes. Fresh runtime UUIDs avoid context reuse across
application requests; they do not immediately delete the underlying runtime,
which remains subject to AgentCore lifecycle settings.

This local synthetic-only test does not establish public-demo cost protection.
Before enabling a public narrative endpoint, add request throttling and spend
controls. Before any private-data cloud mode, review AgentCore/model invocation
logging and trace configuration: financial payloads must not be logged. No payload,
model response, exception detail, session ID, or financial amount is logged by this
application adapter. AWS service retention and tracing are separate controls.

The server's caller credentials authorize invocation; the Harness execution role
authorizes Bedrock inference. These are different permission boundaries. Tests use
an injected fake client and do not spend money or verify the live AWS configuration.
