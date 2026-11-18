# Shared reviewer password

V1 keeps the page and synthetic-record preview public but requires an invitation
password for analysis and AI questions. This is a shared secret, not accounts or
identity verification: anyone with the password can use or share it. Keep the
existing edge limits, gateway throttles, and global 25-job daily allowance.

## Enforcement

The Worker intercepts `GET /api/demo/access` and `POST /api/demo/unlock`; these
are not new AWS routes. Unlock accepts bounded JSON with only `password`. It
checks the server-held DEMO_PASSWORD using HMAC verification, and issues a signed,
randomized four-hour access token using an independent DEMO_AUTH_KEY. Tokens
cannot be forged by knowing the password alone; the signing key stays server-side.

The browser holds the token only in memory and attaches it as a Bearer credential.
No login cookies, localStorage, or sessionStorage are added. The password input
is cleared immediately on submission; the application does not retain it, although
a browser password manager may offer to save it. Refreshing requires unlocking
again and still loses access to any existing financial session, as before.

The Worker checks valid, unexpired signatures before forwarding session creation,
report access, question submission, or job polling to AWS. Removing or bypassing
the disabled UI controls does not bypass this check. Missing setup fails closed.
Unlock calls never reach AWS; password attempts have an approximate, per-location,
per-IP limit of 5/minute in addition to the general API limit. Distributed attackers
and shared passwords remain limitations, not solved identity/authentication.

Sample metadata, preview, suggestions, and health remain public and can still
incur bounded edge/API costs. Purge deliberately remains accessible with the
existing opaque session capability after password access expires or is revoked.
Neither permission nor password expiry means stored session records were deleted.
DEMO_ENABLED=false still pauses all API forwarding, including purge.

The reviewer token and password never reach the AWS origin: outgoing headers
are rebuilt using only the separate ORIGIN_TOKEN. No password/token is logged,
encoded in URLs, written into source/config, or sent to the narrative model.
The repository-only local FastAPI host returns 404 for the access-status endpoint;
the UI supports that local mode, but the public Worker's checks remain mandatory.

## Set up and deploy

With Wrangler authenticated to the intended account and `npm ci` completed:

1. Run `npm test` and `npm run deploy:check`.
2. Run `npx wrangler deploy` to deploy the new gate. Until its secrets are set,
   analysis and question requests return 503 rather than running anonymously.
   The page/preview remain usable. Existing queued work is not cancelled.
3. Run `uv run python scripts/set_demo_password.py` in an interactive terminal.
   Choose and confirm a unique passphrase of 12–128 characters. Prefer several
   randomly chosen words; never reuse a personal/account password. Input is hidden.
4. The helper installs DEMO_PASSWORD and a new random 64-character DEMO_AUTH_KEY
   as Worker secrets via stdin, with CLI output/file logging suppressed. It does
   not print or save either value locally. Wrangler secret updates publish the
   updated bindings; do not paste values into wrangler.jsonc or terminal commands.
5. In a fresh tab, confirm preview works while locked, analysis is disabled,
   incorrect password is rejected, and correct password enables analysis/questions.
   Confirm purge still works and refresh re-locks the demo. API enforcement has
   local tests but still needs deployed rejection/acceptance proof.

Share only the chosen password privately with reviewers; never send the signing
key or origin credential. Do not paste passwords into the project chat.

## Rotation and recovery

Re-running the setup helper changes the password and rotates the signing key,
invalidating previously issued reviewer tokens once the new key is deployed.
It does not delete financial sessions or cancel queued/running jobs. To revoke
access urgently, pause the demo first, then rotate and verify before re-enabling.
The two secret updates are sequential, not atomic; a failure may leave a partial
remote update. Keep the demo paused, finish setup, and test rather than assuming
rollback. The AWS origin credential and its authorizer cache are unaffected.

Do not roll back to a pre-password Worker while public access is enabled: that
would remove the gate. This feature needs no Terraform or API/worker-image change.
