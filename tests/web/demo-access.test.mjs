import test from "node:test";
import assert from "node:assert/strict";
import { DemoAccess } from "../../web/demo-access.mjs";
import { Api } from "../../web/client.mjs";

const NOW = 1_800_000_000_000;
const TOKEN = `v1.1800014400.${"a".repeat(32)}.${"b".repeat(64)}`;
test("unlock holds only a short-lived token and refresh starts locked", async () => {
  let now = NOW;
  const calls = [];
  const api = { request: async (path, options) => {
    calls.push({ path, options });
    return path === "/demo/access" ? { password_required: true } :
      { token: TOKEN, expires_at: new Date(NOW + 14_400_000).toISOString() };
  } };
  const access = new DemoAccess(api, () => {}, () => now);
  await access.load();
  assert.equal(access.unlocked, false);
  await access.unlock("fixture-password");
  assert.equal(access.unlocked, true);
  assert.equal(api.accessToken, TOKEN);
  assert.equal(calls[1].options.body.password, "fixture-password");
  assert.equal(access.password, undefined);
  now += 14_400_000;
  assert.equal(access.unlocked, false);
  access.lock();
  assert.equal(api.accessToken, null);
  assert.equal(new DemoAccess(api).unlocked, false);
});

test("wrong password and unavailable server never unlock", async () => {
  for (const code of ["invalid_demo_password", "edge_rate_limit_reached", "demo_unavailable"]) {
    const api = { request: async (path) => {
      if (path === "/demo/access") return { password_required: true };
      throw { code };
    } };
    const access = new DemoAccess(api);
    await access.load();
    await access.unlock("wrong");
    assert.equal(access.unlocked, false);
    assert.ok(access.error.length);
    assert.equal(api.accessToken, undefined);
  }
});

test("only the missing local endpoint enables local mode; other failures remain locked", async () => {
  for (const status of [404, 503, 0]) {
    const access = new DemoAccess({ request: async () => { throw { status }; } });
    await access.load();
    assert.equal(access.unlocked, status === 404);
  }
});

test("API attaches tab token, omits cookies, and clears rejected access", async () => {
  let options;
  const api = new Api(async (path, request) => {
    options = request;
    return Response.json({ detail: "demo_password_required" }, { status: 401 });
  });
  api.accessToken = TOKEN;
  await assert.rejects(api.request("/sessions", { method: "POST", body: { sample_id: "analysis-demo" } }));
  assert.equal(options.headers.Authorization, `Bearer ${TOKEN}`);
  assert.equal(options.credentials, "omit");
  assert.equal(api.accessToken, null);
});
