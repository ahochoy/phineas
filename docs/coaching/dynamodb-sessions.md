# DynamoDB sessions: application wiring

The table is configured by Terraform. The application selects DynamoDB only when
`PHINEAS_SESSIONS_TABLE` is set; otherwise it uses the local in-memory store.

```bash
export PHINEAS_SESSIONS_TABLE="$(terraform output -raw sessions_table_name)"
export AWS_REGION=us-east-2
uv run uvicorn phineas.api:app --reload --host 127.0.0.1 --no-access-log
```

Keep `PHINEAS_HARNESS_ARN` set if testing narratives too. No raw CSV upload is
exposed. Use the approved synthetic sample IDs in Swagger.

## Local verification against the real table

1. Create an `analysis-demo` session and retain its opaque session ID privately.
2. Retrieve `/sessions/{session_id}/analysis`.
3. Restart Uvicorn with the same environment, then retrieve the same session again
   within 30 minutes. It should survive the process restart.
4. Delete that session. Subsequent requests should return `session_unavailable`.

Do not paste session records or bearer IDs into logs or chat. The SDK uses your
current local AWS credentials. DynamoDB transactions authorize the underlying item
actions; the deployed application's role will need table-scoped PutItem, DeleteItem,
UpdateItem, GetItem, and Query. It does not use BatchWriteItem, Scan, or indexes.
The AgentCore Harness role needs no table permissions.

## Storage and concurrency decisions

- Partition key: `SESSION#<id>`. Sort keys: `METADATA` and `TRANSACTION#<id>`.
- Metadata stores UTC lifecycle values, schema version, sample ID, row count, and
  an optimistic concurrency revision. Transaction items contain only the validated
  sanitized model serialized as JSON. JSON retains money as exact decimal strings
  and is revalidated with Pydantic on reading; no binary floats represent money.
- A maximum of 99 transaction rows plus one metadata item fits the 100-action
  DynamoDB transaction limit. Size checks conservatively bound each item and the
  full transaction. This is a documented MVP limit, not silent truncation: exceeding
  it returns 413. Supporting larger private statements needs another storage design.
- Create and purge each use a single atomic transaction. Failed creation cannot
  expose a partial statement. Purge directly deletes both metadata and records.
- Reads are strongly consistent and queries paginate. A conditional revision check
  prevents lost refreshes; concurrent changes trigger a bounded reread/retry.
  Conditional refresh also requires unexpired metadata, preventing resurrection
  after purge or expiration. Missing records never become new sessions via UpdateItem.
- Every item's `expires_at` is fixed to the absolute four-hour deadline. Idle
  expiration is enforced from metadata on every request. Rows may remain stored
  after idle expiration until absolute TTL cleanup, which AWS performs eventually.
  There is no precise physical-deletion guarantee for expired sessions.
- SDK resources are lazy and thread-local because FastAPI sync routes run in a
  thread pool and Boto3 resources are not thread-safe.
- Operational failures return a safe 503, not a misleading missing-session 404.
  Provider exception details and stored contents are not returned or logged.

Moto-based tests exercise round trips, Decimal preservation, exact expiration,
absolute caps, atomic create failure, pagination, purge, separate app instances,
and deletion during an in-flight access. They do not verify production IAM or
DynamoDB service availability. Real-table verification remains a separate step.
