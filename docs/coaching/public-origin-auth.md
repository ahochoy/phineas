# Public origin authentication

The browser talks only to the Cloudflare Worker. The Worker proxies approved API
requests and supplies a dedicated `x-phineas-origin-token` server-side. It must
overwrite any incoming value, never forward visitor-supplied origin credentials.
The token is not an AWS access key and grants no direct access to DynamoDB, SQS,
Secrets Manager, or Bedrock. It is a bearer credential: disclosure would allow
origin access until rotation. This is service authentication, not user identity.

API Gateway HTTP API uses a REQUEST Lambda authorizer with payload format 2.0,
simple responses, and identity source `$request.header.x-phineas-origin-token`.
All exposed application routes must use it. Keep gateway authorization caching
disabled initially (`authorizer_result_ttl_in_seconds = 0`) so it does not add a
second credential revocation delay. Do not enable anonymous `$default` routes.

The standalone `lambdas/origin_authorizer.py` handler checks the 64-character
URL-safe token created by the bootstrap script. Missing, malformed, duplicate,
or incorrect tokens fail closed. It uses constant-time comparison. Missing
configuration, malformed stored secrets, and SDK failures also fail closed.
No event, token, response payload, or exception details are logged or returned.
Only the Boolean `isAuthorized` is returned; platform invocation logs still exist.

Secrets Manager supplies AWSCURRENT using the Lambda execution role. A warm
process caches a successful read for at most 60 seconds; failed refresh does not
reuse an expired credential. Rotation can therefore take up to 60 seconds to
invalidate a previously accepted token, plus any in-flight requests. Rotate
deliberately and test both rejection and acceptance. Restarting authorizer
environments may be needed for urgent revocation. Secret values remain outside
Terraform state, source control, browser bundles, and command-line arguments.

Execution-role permissions and invocation permissions are separate: the former
allows this handler to read the one secret and write its log group; the latter
will allow only the specific API Gateway authorizer to invoke this Lambda.
Neither grants permissions to invoke the financial application yet.

Package this single file at ZIP root (`origin_authorizer.py`), with handler
`origin_authorizer.lambda_handler` on managed Python 3.14. It imports the SDK
provided by that runtime; no application package, Pydantic, or container image
is required. Public routes and integration remain disabled until authentication,
throttling, route allowlisting, safe logs, and direct-origin rejection are proven.
Origin authentication does not itself rate-limit visitors or stop edge abuse.

## Private deployed check

After deploying the standalone Lambda, run:

```sh
uv run python scripts/test_deployed_authorizer.py
```

This uses the developer's AWS identity to invoke the authorizer three times and
read the current origin secret once. The real token is held only in memory and
sent directly in the authorizer test invocation; it is never written to a fixture,
shell argument, console, or report. The script prints safe checkpoints for missing,
incorrect, and valid credentials. This verifies Lambda execution and secret access,
not gateway configuration or public-origin rejection. Those need separate proof
after attaching the authorizer to protected routes. No model calls or session
records are created by this check. Do not enable SDK wire/debug logging.

After the protected stage is deployed, run the separate gateway-origin check:

```sh
uv run python scripts/test_public_origin.py "$(terraform output -raw public_api_origin)"
```

This reads the token into memory, restricts its destination to the configured
AWS origin, and refuses redirects. It checks anonymous/incorrect-token rejection,
authenticated health, no-store, 50-row sample preview, unavailable docs/OpenAPI,
session creation/report/purge, and post-purge rejection. It attempts purge even
when report validation fails; an ambiguous create or failed delete can still
leave records for expiry/TTL cleanup. Only safe checkpoints are printed.
No questions are submitted, so this does not consume model admission slots or
prove asynchronous questions through the gateway. That remains part of final
end-to-end proof through Cloudflare. This check is not load or throttle proof.
