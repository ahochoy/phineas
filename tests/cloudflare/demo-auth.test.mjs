import test from "node:test";
import assert from "node:assert/strict";
import { issueAccess, verifyAccess, passwordMatches, ACCESS_SECONDS } from "../../cloudflare/demo-auth.mjs";
import { handle } from "../../cloudflare/worker.mjs";

const KEY = "k".repeat(64);
const PASSWORD = "fixture-only-password-123";
const SID = "a".repeat(43);
function env() {
  return { DEMO_ENABLED: "true", ORIGIN_TOKEN: "o".repeat(64), DEMO_PASSWORD: PASSWORD, DEMO_AUTH_KEY: KEY,
    API_LIMIT: { limit: async () => ({ success: true }) }, SESSION_LIMIT: { limit: async () => ({ success: true }) },
    QUESTION_LIMIT: { limit: async () => ({ success: true }) }, UNLOCK_LIMIT: { limit: async () => ({ success: true }) } };
}
function request(path, options = {}) {
  return new Request("https://demo.workers.dev/api" + path, { ...options,
    headers: { "CF-Connecting-IP": "192.0.2.1", "Content-Type": "application/json", ...options.headers } });
}
const unused = async () => { throw new Error("Must not reach AWS"); };

test("password comparison and signed access reject tampering, expiry, and rotation", async () => {
  assert.equal(await passwordMatches(env(), PASSWORD), true);
  assert.equal(await passwordMatches(env(), "wrong"), false);
  const issued = await issueAccess(KEY, 1_800_000_000);
  const bearer = `Bearer ${issued.token}`;
  assert.equal(await verifyAccess(KEY, bearer, 1_800_000_001), true);
  assert.equal(await verifyAccess(KEY, bearer, 1_800_000_000 + ACCESS_SECONDS), false);
  assert.equal(await verifyAccess(KEY, bearer, 1_799_999_999), false);
  assert.equal(await verifyAccess("r".repeat(64), bearer, 1_800_000_001), false);
  assert.equal(await verifyAccess(KEY, bearer.replace("v1.", "v2."), 1_800_000_001), false);
  assert.equal(await verifyAccess(KEY, bearer.slice(0, -1) + "z", 1_800_000_001), false);
  assert.equal(await verifyAccess(KEY, null), false);
});

test("page access status and preview stay public but analysis, questions, and polling are gated", async () => {
  const status = await handle(request("/demo/access"), env(), unused);
  assert.deepEqual(await status.json(), { password_required: true });
  const paths = [
    ["/sessions", "POST"], [`/sessions/${SID}/report`, "GET"],
    [`/sessions/${SID}/question-jobs`, "POST"], [`/sessions/${SID}/jobs/${SID}`, "GET"],
  ];
  for (const [path, method] of paths) {
    const response = await handle(request(path, { method }), env(), unused);
    assert.equal(response.status, 401);
    assert.deepEqual(await response.json(), { detail: "demo_password_required" });
  }
  const preview = await handle(request("/samples/analysis-demo/preview"), env(), async () => Response.json({ rows: [] }));
  assert.equal(preview.status, 200);
});

test("unlock issues only a signed token; wrong password, limiter, and missing setup fail closed", async () => {
  const unlock = (password) => request("/demo/unlock", { method: "POST", body: JSON.stringify({ password }) });
  const valid = await handle(unlock(PASSWORD), env(), unused);
  assert.equal(valid.status, 200);
  const body = await valid.json();
  assert.equal(await verifyAccess(KEY, `Bearer ${body.token}`), true);
  assert.doesNotMatch(JSON.stringify(body), new RegExp(PASSWORD));
  assert.equal(valid.headers.get("cache-control"), "no-store");
  const wrong = await handle(unlock("wrong"), env(), unused);
  assert.equal(wrong.status, 401);
  assert.deepEqual(await wrong.json(), { detail: "invalid_demo_password" });
  assert.equal((await handle(unlock(PASSWORD), { ...env(), DEMO_AUTH_KEY: undefined }, unused)).status, 503);
  assert.equal((await handle(unlock(PASSWORD), { ...env(), UNLOCK_LIMIT: undefined }, unused)).status, 503);
  const limited = env();
  limited.UNLOCK_LIMIT.limit = async () => ({ success: false });
  assert.equal((await handle(unlock(PASSWORD), limited, unused)).status, 429);
});

test("valid signed access unlocks creation but is stripped before AWS; purge works even when locked", async () => {
  const token = (await issueAccess(KEY)).token;
  const response = await handle(request("/sessions", { method: "POST", headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify({ sample_id: "analysis-demo" }) }), env(), async (url, options) => {
    assert.equal(options.headers.Authorization, undefined);
    assert.equal(options.headers["x-phineas-origin-token"], "o".repeat(64));
    assert.doesNotMatch(options.body, new RegExp(token));
    return Response.json({ session_id: SID }, { status: 201 });
  });
  assert.equal(response.status, 201);
  assert.equal((await handle(request(`/sessions/${SID}`, { method: "DELETE" }), env(),
    async () => new Response(null, { status: 204 }))).status, 204);
});
