import test from "node:test";
import assert from "node:assert/strict";
import { handle } from "../../cloudflare/worker.mjs";
import { issueAccess } from "../../cloudflare/demo-auth.mjs";

const SECRET = "s".repeat(64);
const SID = "a".repeat(43);
const AUTH_KEY = "k".repeat(64);
const PASSWORD = "test-only-password-123";
const access = await issueAccess(AUTH_KEY);
function env() {
  return { DEMO_ENABLED: "true", ORIGIN_TOKEN: SECRET, DEMO_PASSWORD: PASSWORD, DEMO_AUTH_KEY: AUTH_KEY,
    ASSETS: { fetch: async () => new Response("asset") },
    API_LIMIT: { limit: async () => ({ success: true }) },
    SESSION_LIMIT: { limit: async () => ({ success: true }) },
    QUESTION_LIMIT: { limit: async () => ({ success: true }) },
    UNLOCK_LIMIT: { limit: async () => ({ success: true }) } };
}
function req(path, options = {}) {
  const headers = { "CF-Connecting-IP": "192.0.2.1", "Content-Type": "application/json",
    Authorization: `Bearer ${access.token}`, ...options.headers };
  return new Request("https://demo.workers.dev" + path, { ...options, headers });
}
const unused = async () => { throw new Error("Unexpected upstream call"); };

test("static files receive security headers; private files and docs are not served", async () => {
  const response = await handle(req("/"), env(), unused);
  assert.equal(response.status, 200);
  assert.equal(response.headers.get("cache-control"), "no-store");
  assert.match(response.headers.get("content-security-policy"), /frame-ancestors 'none'/);
  for (const path of ["/README.md", "/.env", "/wrangler.jsonc", "/docs", "/api/docs", "/api/openapi.json"]) {
    assert.equal((await handle(req(path), env(), unused)).status, 404);
  }
});

test("missing secret or disabled demo fails closed", async () => {
  for (const change of [{ ORIGIN_TOKEN: undefined }, { DEMO_ENABLED: "false" }]) {
    assert.equal((await handle(req("/api/health"), { ...env(), ...change }, unused)).status, 503);
  }
});

test("proxy fixes destination, strips visitor credentials and filters response headers", async () => {
  let call;
  const response = await handle(req("/api/health", { headers: {
    "x-phineas-origin-token": "attacker", "Authorization": "private", "Cookie": "private",
  } }), env(), async (url, options) => {
    call = { url, options };
    return Response.json({ status: "ok" }, { headers: {
      "Set-Cookie": "private", "x-phineas-origin-token": SECRET, "Access-Control-Allow-Origin": "*",
    } });
  });
  assert.equal(response.status, 200);
  assert.equal(call.url, "https://51b01wb0w6.execute-api.us-east-2.amazonaws.com/public/health");
  assert.equal(call.options.headers["x-phineas-origin-token"], SECRET);
  assert.equal(call.options.headers.Cookie, undefined);
  assert.equal(call.options.headers.Authorization, undefined);
  assert.equal(call.options.redirect, "manual");
  assert.equal(response.headers.get("x-phineas-origin-token"), null);
  assert.equal(response.headers.get("set-cookie"), null);
  assert.equal(response.headers.get("access-control-allow-origin"), null);
});

test("unknown routes, queries, and encoded path tricks never reach origin", async () => {
  for (const path of ["/api/health?url=https://evil.example", "/api/https://evil.example", "/api/sessions/%61/report",
    `/api/sessions/${SID}/questions`, `/api/sessions/${SID}/narrative`, "/api/samples/private/preview"]) {
    assert.equal((await handle(req(path), env(), unused)).status, 404);
  }
});

test("cross-origin browser requests and missing trusted IP are denied", async () => {
  for (const headers of [{ Origin: "https://evil.example" }, { "Sec-Fetch-Site": "cross-site" }]) {
    assert.equal((await handle(req("/api/health", { headers }), env(), unused)).status, 403);
  }
  const request = req("/api/health");
  request.headers.delete("CF-Connecting-IP");
  assert.equal((await handle(request, env(), unused)).status, 503);
});

test("all API traffic and costly routes are rate-limited; binding failure denies access", async () => {
  for (const name of ["API_LIMIT", "SESSION_LIMIT", "QUESTION_LIMIT"]) {
    const bindings = env();
    bindings[name].limit = async () => ({ success: false });
    const path = name === "SESSION_LIMIT" ? "/api/sessions" : name === "QUESTION_LIMIT" ? `/api/sessions/${SID}/question-jobs` : "/api/health";
    const response = await handle(req(path, name === "API_LIMIT" ? {} : { method: "POST" }), bindings, unused);
    assert.equal(response.status, 429);
    assert.equal(response.headers.get("retry-after"), "60");
  }
  const bindings = env();
  bindings.API_LIMIT.limit = async () => { throw new Error("private"); };
  assert.equal((await handle(req("/api/health"), bindings, unused)).status, 503);
});

test("body limits apply even without Content-Length and reject unapproved fields", async () => {
  for (const body of ["x".repeat(4097), JSON.stringify({ sample_id: "analysis-demo", csv: "private" }),
    JSON.stringify({ sample_id: "private" }), "not json"]) {
    const response = await handle(req("/api/sessions", { method: "POST", body }), env(), unused);
    assert.ok([400, 413].includes(response.status));
  }
  assert.equal((await handle(req("/api/sessions", { method: "POST", body: "{}", headers: {
    "Content-Length": "5000",
  } }), env(), unused)).status, 413);
});

test("allowed session, question, read, and purge requests proxy successfully", async () => {
  const calls = [
    ["POST", "/api/sessions", { sample_id: "analysis-demo" }],
    ["POST", `/api/sessions/${SID}/question-jobs`, { question: "Explain fees", request_id: "12345678-1234-1234-1234-123456789abc" }],
    ["GET", `/api/sessions/${SID}/report`],
    ["GET", `/api/sessions/${SID}/jobs/12345678-1234-1234-1234-123456789abc`],
    ["DELETE", `/api/sessions/${SID}`],
  ];
  for (const [method, path, body] of calls) {
    const result = await handle(req(path, { method, body: body ? JSON.stringify(body) : undefined }), env(),
      async () => method === "DELETE" ? new Response(null, { status: 204 }) : Response.json({ result: "ok" }));
    assert.equal(result.status, method === "DELETE" ? 204 : 200);
    assert.equal(result.headers.get("cache-control"), "no-store");
  }
});

test("purge accepts a present but empty body stream", async () => {
  let calls = 0;
  const request = req(`/api/sessions/${SID}`, { method: "DELETE",
    body: new ReadableStream({ start(controller) { controller.close(); } }),
    duplex: "half", headers: { "Content-Length": "0" },
  });
  assert.notEqual(request.body, null);
  const response = await handle(request, env(), async (url, options) => {
    calls++;
    assert.equal(options.method, "DELETE");
    assert.equal(options.body, undefined);
    return new Response(null, { status: 204 });
  });
  assert.equal(response.status, 204);
  assert.equal(calls, 1);
});

test("purge still rejects any actual body bytes without calling AWS", async () => {
  for (const body of ["x", "{}", " ", "private".repeat(1000)]) {
    const response = await handle(req(`/api/sessions/${SID}`, {
      method: "DELETE", body,
    }), env(), unused);
    assert.equal(response.status, 400);
    assert.deepEqual(await response.json(), { detail: "invalid_request" });
  }
});

test("upstream redirects and authorization failures never reach browser", async () => {
  for (const status of [301, 302, 401, 403]) {
    const response = await handle(req("/api/health"), env(), async () => new Response("PRIVATE", {
      status, headers: { Location: "https://evil.example" },
    }));
    assert.equal(response.status, 502);
    assert.equal(response.headers.get("location"), null);
    assert.doesNotMatch(await response.text(), /PRIVATE/);
  }
});

test("validation and unexpected error payloads are not echoed; safe codes survive", async () => {
  const response = await handle(req("/api/health"), env(), async () => Response.json({ detail: [{ input: "PRIVATE" }] }, { status: 422 }));
  assert.deepEqual(await response.json(), { detail: "request_failed" });
  const limited = await handle(req("/api/health"), env(), async () => Response.json({ detail: "demo_daily_job_limit_reached" }, { status: 429 }));
  assert.deepEqual(await limited.json(), { detail: "demo_daily_job_limit_reached" });
});

test("oversized and malformed upstream output fails safely", async () => {
  for (const body of ["PRIVATE", "x".repeat(131073)]) {
    const response = await handle(req("/api/health"), env(), async () => new Response(body));
    assert.ok([502, 503].includes(response.status));
    assert.doesNotMatch(await response.text(), /PRIVATE/);
  }
});
