# Ledger Lens — Project Spec
*Working name. Privacy-first personal finance analyzer. Python · FastAPI · MCP · AWS Bedrock · Terraform.*

## 1. Problem

Given a year of bank or credit card transactions, tell me:
- **Subscriptions:** every recurring charge, its cadence (weekly/monthly/annual), and its annualized cost.
- **Price creep:** subscriptions whose price went up during the year.
- **Fees I missed:** overdraft, late, foreign transaction, ATM, annual, and interest charges, with totals.
- **Duplicates and oddities:** duplicate charges, free trials that converted to paid, and one-off anomalies.
- **Spending patterns:** spend by category and month, trends, and the biggest movers.

…and then **forget everything.** Nothing about my finances outlives the request.

## 2. Privacy principles (the heart of the project)

1. **Ephemeral by design.** Statements are parsed in memory. Never write to S3, a database, or disk (`/tmp` included). The response is the only output.
2. **The LLM never sees raw transactions.** Deterministic Python does the detection. Bedrock only receives *redacted aggregates* (merchant names, categories, totals, cadences) to categorize ambiguous merchants and write a plain-English summary.
3. **Redact before anything leaves the parser.** Mask account and card numbers and names; drop balances and transaction IDs that aren't needed. Bedrock Guardrails' sensitive-information filters act as a second layer.
4. **MCP tools return aggregates only.** Whatever an MCP tool returns lands in the calling assistant's context, and the assistant's provider sees it, so tools never return raw rows.
5. **Zero-trust principles, pragmatically:** authenticate every request, least-privilege IAM per component, no public data stores, and encryption in transit. Full zero-trust networking (VPC, PrivateLink) is a stretch goal, not the MVP.
6. **Logs contain no financial data.** Log request metadata and timings only. Short CloudWatch retention. Bedrock model-invocation logging stays off.
7. **Test data is synthetic.** A generator produces realistic fake statements. Real statements never go in the repo.

## 3. Architecture

```
Client (curl / small web UI / MCP client such as Claude Desktop or Claude Code)
   │  HTTPS + auth
   ▼
API Gateway (HTTP API, JWT or IAM auth)
   ▼
Lambda (container image): FastAPI app (via Mangum)
   ├── parser/       CSV first (most banks export it), OFX optional, PDF stretch
   ├── redact/       mask PII before analysis output leaves
   ├── analyze/      deterministic detectors (subscriptions, fees, duplicates, trends)
   ├── narrate/      Bedrock Converse API: redacted aggregates → summary + categories
   └── mcp/          MCP server (official Python `mcp` SDK) exposing the same capabilities
   ▼
Amazon Bedrock (Claude model) + Bedrock Guardrail
```

**Deterministic core, LLM at the edges.** Detection must be reproducible and testable; the model adds judgment only where rules are weak (ambiguous merchant names, readable summaries).

## 4. Interfaces

**REST (FastAPI)**
- `POST /analyze` (multipart statement upload) → full report JSON: subscriptions, fees, duplicates, category/month breakdown, narrative.
- `GET /health`

**MCP tools** (stateless; each call takes the statement content or a short-lived upload reference)
- `analyze_statement` → summary report (aggregates only)
- `find_subscriptions` → recurring charges, cadence, annualized cost, price changes
- `find_fees` → fee lines grouped by type, with totals
- `spending_summary` → category × month totals and top changes

## 5. Detection logic (MVP)

- **Normalize merchants:** strip store numbers, locations, and payment-processor prefixes (e.g. `SQ *`, `PAYPAL *`).
- **Recurring detection:** group by normalized merchant; look for consistent intervals (±3 days monthly, ±10 days annual) and similar amounts (±10%); flag amount increases as price creep.
- **Fees:** keyword and pattern rules plus amount heuristics per fee type.
- **Duplicates:** same merchant and amount within a short window.
- **Trends:** month-over-month by category; flag outliers (e.g. more than 2 standard deviations).

## 6. Infrastructure (Terraform)

- ECR repository + Lambda (container) + API Gateway HTTP API with an authorizer
- IAM role scoped to `bedrock:InvokeModel` on one model, plus its own log group
- Bedrock Guardrail (sensitive-information filters)
- CloudWatch log group with 1–3 day retention
- AWS Budgets alarm
- **No** S3 bucket and no database; their absence is part of the design
- Stretch: VPC + Bedrock VPC endpoint, KMS customer-managed key, WAF

## 7. Testing

- **Synthetic data generator:** a year of fake transactions with planted subscriptions, a price increase, fees, and duplicates.
- **Detection tests:** everything planted is found; control data produces no false alarms.
- **Privacy tests:** no files written during analysis, and log output contains no merchant names, amounts, or account numbers. Assert these in pytest.
- **LLM checks:** the narrative references only numbers present in the aggregates (no invented figures).

## 8. Milestones

| Phase | Deliverable |
|---|---|
| 1 — Core | Synthetic data generator, CSV parser, redaction, detectors, pytest suite (runs locally, no AI) |
| 2 — AI + API | FastAPI endpoints, Bedrock narrative + Guardrail, MCP server, tested from Claude Desktop/Code |
| 3 — Cloud | Terraform deploy to AWS, auth, log retention, budget alarm |
| 4 — Polish | README with architecture diagram, privacy model, design trade-offs, demo GIF, "what I'd do next" |

## 9. Before you start

- Request Bedrock model access in your AWS account (approval can take time).
- Set up an AWS budget alarm on day one.
- Decide your first bank's CSV format and write a parser for that one; add more later.

## 10. Interview talking points this creates

- Handling sensitive data: data minimization, ephemerality, redaction, and why the LLM never sees raw rows.
- Deterministic vs. LLM responsibilities: what should be rules, what should be the model, and why.
- Implementing MCP (server side) and the context-leak trade-off of MCP tool outputs.
- AWS Bedrock + Guardrails + Terraform: infrastructure as code for AI services.
- Evaluation: proving detections are correct and proving the privacy guarantees with tests.
