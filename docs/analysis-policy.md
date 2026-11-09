# Deterministic analysis policy 0.1.0

`GET /sessions/{session_id}/analysis` analyzes sanitized session records through
the application service. It uses the existing idle-refresh and expiration rules.
Select `analysis-demo` when creating a session to see planted positive cases;
`credit-card-demo` is a clean control for these first checks.

## Eligible purchases

Recurrence and duplicate checks use positive outflow purchases with an identified
merchant. Payments, refunds, transfers, income, fees, interest, unknown kinds,
zero amounts, and unidentified merchants are excluded from those two checks but
remain in the session and cash-movement summary. The response reports the total
excluded count and unknown-kind count. No unidentified merchants are grouped.

## Monthly recurring-charge candidates

Require at least three purchases at one merchant, all with equal amounts, with
every consecutive posting-date gap between 28 and 31 days inclusive. Annualized
cost is the observed amount times 12 using Decimal arithmetic. This is an estimate
assuming continuation, not a forecast or actual annual spend. Regular shopping
can satisfy the rule; the result is a candidate, not a confirmed subscription.
All eligible rows for that merchant must satisfy the rule. Extra purchases, price
changes, missed months, and posting shifts can suppress detection in this version.
Weekly/annual recurrence and price-change detection are not implemented yet.

## Possible duplicate purchases

Group by exact session merchant ID, posting date, and Decimal amount. Groups with
at least two rows produce one possible-duplicate finding with a count. Legitimate
same-day repeat purchases are possible. Different merchants, dates, amounts, and
unidentified merchants must not be merged. No automatic removal takes place.

## Fees and interest

Report separate counts and totals for transactions classified `fee` or `interest`
with outflow direction. Earned interest is excluded. No description-based fee
subtype inference or offsetting of refunded charges is performed in this version.

## Output boundary

Internal findings contain evidence transaction IDs. These fields are explicitly
excluded from Pydantic serialization; HTTP responses contain aggregate findings
and anonymous merchant IDs only. Raw rows, descriptions, readable merchant names,
and session credentials are not included. The summary still represents total
cash movement, not purchase spending. This partial result is not yet the full
AnalysisReport contract: category totals, trends, price changes, narrative, and
detailed exclusion breakdowns are later slices. No Bedrock invocation occurs.
