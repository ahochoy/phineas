# FastAPI: the first HTTP slice

FastAPI maps HTTP requests to Python functions. Pydantic request models validate
incoming fields; response models validate and serialize the returned aggregate
and describe its shape in OpenAPI. Uvicorn is the ASGI server that receives
network requests and runs the FastAPI application.

Run locally:

```bash
uv run uvicorn phineas.api:app --reload --host 127.0.0.1 --no-access-log
```

Open http://127.0.0.1:8000/docs for the generated API explorer. Call `GET /samples`,
then `POST /analyses/sample-summary` with:

```json
{"sample_id": "credit-card-demo"}
```

The route calls the sample service, which selects bundled synthetic text from an
allowlist and delegates to the same application function used by the CLI.
Request values are never turned into file paths. No raw upload route exists.
Summary totals include all inflows and outflows and must not be called spending.

The ordinary `def` route runs synchronous parsing outside the async event loop
using FastAPI's thread pool. Converting it to `async def` would not make the
parsing asynchronous. TestClient exercises HTTP behavior without opening a port.

The sample-summary endpoint is stateless. Working sessions now use an in-memory
store through a `SessionStore` protocol and `SessionService`. No AWS credentials,
Bedrock, or database are needed. It does not yet detect subscriptions or other findings.
The health endpoint checks process responsiveness, not AWS service readiness.
Later sessions will enforce access expiration independently of AgentCore runtime
lifetime. Deployments must omit `--reload`; this command is for local development.

## Working sessions

1. `POST /sessions` with `{"sample_id": "credit-card-demo"}` returns a bearer
   `session_id` and UTC creation/expiration timestamps.
2. `GET /sessions/{session_id}/summary` returns aggregates and refreshes the
   30-minute idle window, capped by the original four-hour absolute deadline.
3. `DELETE /sessions/{session_id}` directly removes the session records and
   returns 204. Later accesses or deletes return the same 404 response used for
   expired, malformed, or nonexistent IDs.

Every response uses `Cache-Control: no-store`. Do not log request bodies or
session URLs: session IDs are bearer credentials. `--no-access-log` disables
Uvicorn's default URL logging; future proxies and API Gateway require equivalent
redaction or logging configuration. Synthetic aggregate output is safe to inspect
in the local explorer, but the session ID should still be treated as a credential.

The store holds only sanitized transactions, never source descriptions. Each
session creation uses a fresh merchant registry. A lock makes lifecycle operations
atomic within one process. Expired records are inaccessible at the application
boundary and swept on subsequent store operations; this is not precise background
deletion. Process exit loses all sessions. Use one worker locally: multiple workers
or Lambda instances require a shared store such as DynamoDB. Reloads also lose
sessions. Request rate limits and a memory-capacity policy are required before
public deployment.

Tests inject a clock rather than sleeping, proving both exact expiration boundaries
and that normal activity cannot extend absolute lifetime. Application session IDs
are independent of AgentCore runtime session IDs.
