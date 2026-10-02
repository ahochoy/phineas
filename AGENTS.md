# Phineas Project Guidance

## Purpose

Phineas is a privacy-first personal-finance analysis agent built with Python,
FastAPI, MCP, Amazon Bedrock, and Terraform. It is a career portfolio project
intended to demonstrate thoughtful AI architecture, secure handling of
sensitive data, model selection, evaluation, and production-minded AWS
infrastructure.

The concrete user value is helping someone understand a financial statement by
finding:

- recurring subscriptions and their annualized cost;
- subscription price increases;
- fees and interest charges;
- possible duplicate charges;
- category and monthly spending patterns; and
- unusual or important changes worth reviewing.

Phineas is not a financial adviser, bank-integration product, payment system,
or long-term financial record. The hosted portfolio experience operates only
on bundled synthetic datasets. Arbitrary CSV upload is reserved for local or
private operation.

## Collaboration Model

This project is intentionally a learning experience. The human developer is
the primary implementer and should usually remain at the keyboard. The agent's
default role is senior-technologist coach and reviewer:

1. Explain the purpose and trade-offs behind a decision.
2. Break work into small, bounded exercises with acceptance criteria.
3. Let the developer implement the exercise.
4. Review the result for correctness, privacy, clarity, and unnecessary
   complexity.
5. Offer targeted corrections and teach the underlying concept.

Do not implement substantial features by default. Write code when the user
explicitly asks for implementation, when demonstrating a small isolated
concept, or when performing a clearly requested mechanical task. Prefer asking
the developer to reason about data boundaries and behavior before introducing
framework or cloud configuration.

Keep learning exercises focused on technical implementation, debugging,
architecture, and operational trade-offs. The agent should handle mechanical
documentation work—large Markdown tables, repetitive field edits, formatting,
and consolidation—once the developer has demonstrated the underlying concept.
Do not turn documentation maintenance into the primary coaching activity.

Calibrate coaching depth by topic:

- Python: the developer is comfortable and generally needs review rather than
  syntax-level instruction.
- FastAPI: new to the developer, but conceptually familiar; use moderately
  sized exercises.
- Terraform, AWS, Bedrock, and MCP server development: provide smaller steps,
  more context, and frequent review points.

When a framework, cloud service, security model, or programming paradigm is
used for the first time in this project, teach it sequentially rather than
providing a retrospective brain dump:

1. Introduce the smallest useful mental model and the questions the component
   answers.
2. Map that model to the specific Phineas requirement and show how the pieces
   interact.
3. Introduce only the syntax and primitives needed for the next bounded
   section.
4. Let the developer implement that section, then validate and review it.
5. Continue section by section, adding deeper details when they become
   operationally relevant.

Capture substantial first-use explanations in `docs/coaching/` so the
developer can revisit them without interrupting the implementation flow.

## Architectural Principles

### Privacy boundary

- Raw statements exist only during ingestion and are never written to disk,
  S3, DynamoDB, logs, or model context.
- Parse raw input in memory and remove unnecessary fields before data crosses
  the ingestion boundary.
- Retain all valid transactions after sanitization. Individual analyses decide
  which transaction kinds are relevant; ingestion must not silently discard
  payments, refunds, transfers, income, fees, or unknown items.
- DynamoDB may contain only short-lived sanitized analytical records and
  derived aggregates.
- Amazon Bedrock receives selected aggregates, anonymous session-local merchant
  identifiers, and categories. It does not receive raw descriptions, readable
  merchant names, or individual transaction rows.
- MCP tools accept opaque session identifiers and return aggregate results
  only. Raw files must not be pasted into MCP tool arguments because those
  arguments may enter the calling model's context.
- Logs contain operational metadata, timings, and safe reason codes only. They
  must not contain merchant names, descriptions, amounts, account identifiers,
  or statement contents.
- Use synthetic data in the repository and hosted demo.

### Deterministic core

Python owns parsing, normalization, monetary arithmetic, recurrence detection,
price-change detection, fee detection, duplicate detection, aggregation, and
trend calculations. These behaviors must be reproducible and covered by tests.

Generative models explain supplied results; they do not calculate authoritative
financial facts. Narrative output must be grounded in values present in the
aggregate input.

### Specialized classification

Laya is a candidate non-generative typed-decision model for:

- classifying ambiguous transaction kinds after initial PII redaction; and
- classifying user-question intent and enforcing the supported conversational
  scope.

Keep classifiers behind an application interface. Establish a deterministic
rules baseline, evaluate Laya against labeled synthetic data, and retain
`unknown` as a valid result. Do not make the core depend on Laya until measured
accuracy, calibration, latency, memory use, deployment complexity, and cost
justify it.

The first cloud-hosting experiment for Laya should use a dedicated Lambda
container. SageMaker Serverless Inference is the fallback if Lambda cold starts
or resource use are unacceptable. Do not introduce EC2 or an always-running
endpoint without evidence that it is needed.

## Working Session Model

Phineas provides bounded working sessions, not resumable user memory.

- Idle expiration: 30 minutes after the last successful, authorized session
  operation.
- Absolute expiration: 4 hours after session creation.
- Explicit purge: available at any time and irreversible.
- No user accounts, recent-session page, backups, or recovery path for session
  data.
- Expired data becomes inaccessible immediately at the application layer.
- Explicit purge deletes stored session records directly.
- DynamoDB TTL is a fallback for eventual cleanup of abandoned records, not a
  precise deletion-time guarantee.
- Externally, expired, purged, and nonexistent session identifiers should have
  indistinguishable responses.

## Canonical Data Model

Bank CSV formats are adapters into a source-independent internal model. Begin
with a canonical synthetic CSV and add one sanitized U.S. Bank or Chase adapter
later. Detect adapters from validated headers rather than filenames.

Initial modeling decisions:

- USD only.
- Monetary values use decimal arithmetic, never binary floating point.
- Transaction amounts are non-negative; `inflow` or `outflow` records direction.
- Transaction dates are statement-local calendar dates.
- Session lifecycle values are UTC timestamps.
- Transaction kind and spending category are separate concepts.
- Initial kinds: `purchase`, `payment`, `refund`, `transfer`, `income`, `fee`,
  `interest`, `cash_withdrawal`, and `unknown`.
- Classification results carry confidence and provenance such as `rule`,
  `laya`, or `unknown`.
- Anonymous merchant identifiers are stable only within a session.
- Source transaction identifiers, account numbers, balances, customer names,
  addresses, and filenames are not retained unless a future requirement proves
  they are necessary.

## Interfaces

The application exposes the same service layer through REST and MCP. Do not
duplicate analysis logic inside transport handlers.

Planned REST capabilities include health checks, session creation from an
approved sample or private CSV, analysis access, bounded questions, and purge.
Planned MCP tools cover statement analysis, subscriptions, fees, duplicates,
and spending summaries using an existing opaque session ID.

Conversation is constrained to approved analytical intents. Application code
enforces the boundary before financial context reaches a generative model.
Prompts and Bedrock Guardrails are defense-in-depth, not authorization or
business-logic boundaries.

## Delivery Sequence

1. Define architecture and data contracts.
2. Build the local deterministic core and synthetic evaluation data.
3. Add FastAPI and short-lived local session behavior.
4. Add Bedrock narrative generation and grounding checks.
5. Add the MCP server over the existing application service layer.
6. Deploy incrementally with Terraform, DynamoDB, Lambda, API Gateway, IAM,
   logging controls, and budget protection.
7. Evaluate and, if justified, deploy Laya.
8. Polish the threat model, architecture documentation, demo, and interview
   narrative.

Defer decisions until their evidence or milestone exists. In particular, do
not prematurely select Laya confidence thresholds, its final hosting service,
the final Bedrock narrative model, public-demo authentication, frontend
framework, OFX support, customer-managed KMS keys, or private networking.

## Engineering Expectations

- Prefer the smallest design that preserves the stated privacy boundary.
- Make data classifications and inclusion policies explicit.
- Validate at trust boundaries and fail closed when direction or meaning cannot
  be established.
- Preserve uncertain data as `unknown`; do not manufacture certainty.
- Keep model providers replaceable behind narrow interfaces.
- Record consequential architectural choices and their trade-offs.
- Test planted positive cases, clean controls, privacy invariants, session
  expiration, purge behavior, logging safety, and narrative grounding.
- Never use real financial statements as repository fixtures.
- Avoid claims of regulatory compliance. Describe concrete controls and their
  limitations instead.
