# Cloudflare public frontend and edge proxy

The existing buildless web UI is served by a Cloudflare Worker with Static
Assets. `run_worker_first` is true so the Worker applies headers and its static
file allowlist before serving assets. Only the six public HTML/CSS/JS paths are
served, not README, Python source, deployment configuration, or repository files.
There is no SPA fallback for unknown/API paths. The Worker bundle lives outside
the public asset directory. Use a workers.dev URL; the convenience subdomain can
redirect there without changing the browser origin or requiring CORS.

`/api` requests use the exact AWS route allowlist. The Worker builds the fixed
AWS URL, strips the browser's `/api` prefix, and forwards to `/public` at API
Gateway. Lambda Web Adapter removes `/public` before FastAPI routes. No visitor
query strings, arbitrary targets, cookies, Authorization, forwarding headers,
or origin credentials are forwarded. Headers are rebuilt with the server-held
ORIGIN_TOKEN. Unknown routes, encoded path tricks, and query strings are rejected.
Origin redirects are not followed. Origin 401/403 becomes a safe gateway error.

POST requests require JSON, a streamed 4,096-byte limit (not just Content-Length),
and the approved fields. Session creation accepts only bundled sample IDs.
Bodyless operations accept either a null body or a stream containing zero bytes;
stream presence alone does not imply a payload. Actual DELETE body bytes are
rejected before AWS forwarding. A public purge smoke test caught this distinction
after Node tests with null bodies and private-origin tests had passed.
Question submissions permit only request UUID and bounded question text; the
application still owns intent/admission checks. Responses are bounded to 128 KiB.
Validation payloads and unexpected errors are reduced to safe reason codes.
Successful API responses and static files receive no-store, no-referrer, nosniff,
same-origin CSP, and disabled camera/microphone/geolocation permissions. Cookies
are not returned. Cross-origin browser requests are refused; this is not bot
authentication and does not prevent scripted clients from calling the Worker.

## Limits and privacy

Rate Limiting bindings use the Cloudflare-supplied connecting IP as a transient
counter key: 120 API requests/minute, 3 session creations/minute, and 12 question
submissions/minute. A fourth binding permits 5 password attempts/minute per IP.
Missing IP or limiter errors fail closed. Purge/report/polling
are subject to the general limit but not the tighter creation/question limits.
Shared-IP users share limits. These counters are approximate and per Cloudflare
location; they are not global quotas or monetary caps. Gateway throttles and
the application's 25-new-jobs/UTC-day allowance remain separate layers.

There are no application console logs. Wrangler observability is disabled to
avoid retaining invocation URLs containing session capabilities. Do not enable
request logging, live tail, analytics payload collection, or header/body logging
without reviewing what they capture. Cloudflare/AWS still process network
metadata; this design does not claim that providers retain no operational data.
Never embed ORIGIN_TOKEN in config, source, static assets, browser code, tfvars,
or shell arguments. The only browser session capability stays in tab memory.

## Bounded rollout

1. Install pinned tooling using `npm ci` and run `npm test` plus
   `npm run deploy:check`. The latter bundles locally and does not deploy.
2. Review Wrangler's bindings/config: static web assets, three rate limiters,
   no request logging, and DEMO_ENABLED=false during initial setup. ORIGIN_TOKEN,
   DEMO_PASSWORD, and DEMO_AUTH_KEY are intentionally absent from source.
   Namespace IDs 71001–71004 should not be reused for other
   account workloads that need independent counters.
3. Deploy only at the developer's explicit step, keeping DEMO_ENABLED=false.
   The site may be reachable, but API requests must return 503 without reaching
   AWS. Missing secret is also fail-closed even if the enable flag is changed.
4. With Wrangler logged in to the intended Cloudflare account, run
   `uv run python scripts/install_cloudflare_origin_secret.py`. It transfers the
   existing AWSCURRENT token via Wrangler stdin, suppresses CLI output and file
   logging, and never writes a credential file or passes the token as an argument.
   It checks the AWS account, targets only `phineas-finance`, and leaves enablement
   unchanged. A timeout/error can leave a successful remote update unconfirmed;
   do not infer rollback or rotate the AWS secret blindly. Do not print/copy/paste
   the credential. This step updates Cloudflare, not Terraform or the AWS secret.
5. Enable the demo deliberately, then verify the real workers.dev URL in a
   browser: sample preview, analysis, supported question/polling, failure and
   quota states, purge, and post-purge rejection. Recheck anonymous origin
   rejection and safe platform logs before sharing the link.

The shared reviewer password gate is an additional launch requirement. Follow
[demo password setup](demo-password.md); absent secrets fail closed for analysis,
questions, and session reads. Public metadata/preview do not require unlock.

Do not call a dry run, mocked binding tests, or the AWS origin smoke test proof
that the complete Cloudflare deployment works. A clear API image scan is also
point-in-time evidence, not a security guarantee. Current origin image:
`sha256:455e8d208a99cf803d1b4b2165b3533535ebed0258e8434147cdad2933628c1f`.

For an edge pause, deploy DEMO_ENABLED=false; no AWS requests should be proxied.
The DynamoDB admission pause separately blocks new questions but does not stop
already queued/running work. Preserve purge access where possible when choosing
an operational pause. Token rotation requires coordinating both providers and
allowing the authorizer's 60-second cache expiry. No automated rotation is added.

References: [Worker-first asset routing](https://developers.cloudflare.com/workers/static-assets/routing/worker-script/),
[rate limit behavior](https://developers.cloudflare.com/workers/runtime-apis/bindings/rate-limit/).
