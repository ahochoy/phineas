import test from "node:test";
import assert from "node:assert/strict";
import { Api, ApiError, Workspace, answerText } from "../../web/client.mjs";

const session = () => ({ session_id: "opaque-session", created_at: "2026-01-01T00:00:00Z",
  idle_expires_at: "2026-01-01T00:30:00Z", absolute_expires_at: "2026-01-01T04:00:00Z" });
const report = { analysis: { summary: {} }, facts: [] };
const fact = { fact_id: "fee", text: "A deterministic test finding." };
const result = { message: "Review findings.", facts: [fact],
  narrative: { narrative_status: "generated", highlights: [fact] } };
const complete = { job_id: "job", state: "succeeded", result };

test("default fetch keeps the browser global receiver", async () => {
  const original = globalThis.fetch;
  globalThis.fetch = function () {
    assert.equal(this, globalThis, "Browser fetch requires its global receiver");
    return Promise.resolve(new Response('["analysis-demo"]'));
  };
  try {
    assert.deepEqual(await new Api().request("/samples"), ["analysis-demo"]);
  } finally {
    globalThis.fetch = original;
  }
});

function setup(responses) {
  let time = Date.parse("2026-01-01T00:00:00Z");
  let id = 0;
  const calls = [];
  const api = { request: async (path, options) => {
    calls.push({ path, options });
    const response = responses.shift();
    if (response instanceof Error) throw response;
    return typeof response === "function" ? response() : response;
  } };
  const workspace = new Workspace({ api, now: () => time, uuid: () => `request-${++id}`,
    sleep: async (ms) => { time += ms; } });
  return { workspace, calls, advance: (ms) => { time += ms; } };
}

test("HTTP client uses same-origin, no-store, no credentials and JSON bodies", async () => {
  const calls = [];
  const api = new Api(async (...args) => { calls.push(args); return new Response('{"ok":true}'); });
  assert.deepEqual(await api.request("/sessions", { method: "POST", body: { sample_id: "analysis-demo" } }), { ok: true });
  assert.equal(calls[0][0], "/api/sessions");
  const options = calls[0][1];
  assert.equal(options.credentials, "omit");
  assert.equal(options.cache, "no-store");
  assert.equal(options.referrerPolicy, "no-referrer");
  assert.deepEqual(JSON.parse(options.body), { sample_id: "analysis-demo" });
});

test("HTTP errors never surface raw validation or proxy payloads", async () => {
  const api = new Api(async () => new Response('{"detail":[{"input":"SECRET"}]}', { status: 422 }));
  await assert.rejects(api.request("/test"), (error) => error.code === "request_failed" && !error.message.includes("SECRET"));
  const offline = new Api(async () => { throw new Error("SECRET credentials"); });
  await assert.rejects(offline.request("/test"), (error) => error.code === "network_unavailable");
});

test("create, load report, submit, poll, and render server-selected facts", async () => {
  const { workspace: w, calls } = setup([session(), report, { job_id: "job", state: "pending" }, complete]);
  await w.start("analysis-demo");
  assert.equal(w.report, report);
  await w.ask("Explain fees");
  assert.deepEqual(w.messages[0].texts, [result.message, fact.text]);
  assert.deepEqual(calls.map((call) => call.path), ["/sessions", "/sessions/opaque-session/report",
    "/sessions/opaque-session/question-jobs", "/sessions/opaque-session/jobs/job"]);
  assert.equal(w.busy, null);
});

test("ambiguous submission retry reuses request UUID and does not duplicate chat", async () => {
  const { workspace: w, calls } = setup([session(), report, new ApiError(503, "job_queue_unavailable"), complete]);
  await w.start("analysis-demo");
  await w.ask("Explain fees");
  assert.equal(w.retry, "question");
  await w.ask(w.pending.question, true);
  assert.equal(calls[2].options.body.request_id, calls[3].options.body.request_id);
  assert.equal(w.messages.length, 1);
  assert.equal(w.pending, null);
});

test("poll timeout retains job request identity for deliberate retry", async () => {
  const pending = { job_id: "job", state: "running" };
  const { workspace: w, calls } = setup([session(), report, pending, ...Array(90).fill(pending), complete]);
  await w.start("analysis-demo");
  await w.ask("Explain fees");
  assert.equal(w.error, "question_wait_timeout");
  const original = w.pending.request_id;
  await w.ask(w.pending.question, true);
  assert.equal(calls.at(-1).options.body.request_id, original);
  assert.equal(w.error, null);
});

for (const code of ["demo_daily_job_limit_reached", "question_job_limit_reached", "demo_admissions_paused"]) {
  test(`${code} blocks more questions but preserves report and purge`, async () => {
    const { workspace: w, calls } = setup([session(), report, new ApiError(429, code), null]);
    await w.start("analysis-demo");
    await w.ask("Explain fees");
    assert.equal(w.blocked, true);
    assert.equal(w.report, report);
    const before = calls.length;
    await w.ask("Explain fees");
    assert.equal(calls.length, before);
    await w.end();
    assert.equal(calls.at(-1).options.method, "DELETE");
    assert.equal(w.session, null);
  });
}

test("expired or purged session clears results and conversation", async () => {
  const { workspace: w } = setup([session(), report, new ApiError(404, "session_unavailable")]);
  await w.start("analysis-demo");
  await w.ask("Explain fees");
  assert.equal(w.report, null);
  assert.equal(w.session, null);
  assert.deepEqual(w.messages, []);
});

test("local idle expiry clears data without extending activity through timers", async () => {
  const { workspace: w, advance, calls } = setup([session(), report]);
  await w.start("analysis-demo");
  advance(30 * 60_000);
  assert.equal(w.expireIfNeeded(), true);
  assert.equal(w.session, null);
  assert.equal(w.report, null);
  assert.equal(calls.length, 2);
});

test("activity cannot extend absolute expiration", async () => {
  const { workspace: w, advance } = setup([session(), report]);
  await w.start("analysis-demo");
  advance(3.75 * 60 * 60_000);
  w.touch();
  assert.equal(w.session.idle_expires_at, "2026-01-01T04:00:00.000Z");
  advance(15 * 60_000);
  assert.equal(w.expireIfNeeded(), true);
});

test("purge failure preserves capability and never claims deletion succeeded", async () => {
  const { workspace: w } = setup([session(), report, new ApiError(0, "network_unavailable"), null]);
  await w.start("analysis-demo");
  await w.end();
  assert.equal(w.error, "purge_unconfirmed");
  assert.equal(w.session.session_id, "opaque-session");
  assert.equal(w.report, report);
  await w.end();
  assert.equal(w.session, null);
  assert.match(w.notice, /purged/);
});

test("late answer cannot redisplay results after purge", async () => {
  let resolve;
  const delayed = new Promise((done) => { resolve = done; });
  const { workspace: w } = setup([session(), report, () => delayed, null]);
  await w.start("analysis-demo");
  const question = w.ask("Explain fees");
  await w.end();
  resolve(complete);
  await question;
  assert.equal(w.report, null);
  assert.equal(w.session, null);
  assert.deepEqual(w.messages, []);
});

test("late report cannot repopulate an expired page", async () => {
  let resolve;
  const delayed = new Promise((done) => { resolve = done; });
  const { workspace: w } = setup([session(), () => delayed]);
  const starting = w.start("analysis-demo");
  await Promise.resolve();
  w.clear("Expired");
  resolve(report);
  await starting;
  assert.equal(w.report, null);
  assert.equal(w.session, null);
});

test("failed job is terminal, not an automatic new charged request", async () => {
  const { workspace: w, calls } = setup([session(), report, { job_id: "job", state: "failed" }]);
  await w.start("analysis-demo");
  await w.ask("Explain fees");
  assert.equal(w.error, "question_failed");
  assert.equal(w.retry, null);
  assert.equal(w.pending, null);
  assert.equal(calls.length, 3);
});

test("report failure retains session for retry or purge", async () => {
  const { workspace: w } = setup([session(), new ApiError(503, "session_store_unavailable"), report]);
  await w.start("analysis-demo");
  assert.equal(w.retry, "report");
  assert.ok(w.session);
  await w.reloadReport();
  assert.equal(w.report, report);
  assert.equal(w.retry, null);
});

test("only one question can be submitted at a time", async () => {
  let resolve;
  const delayed = new Promise((done) => { resolve = done; });
  const { workspace: w, calls } = setup([session(), report, () => delayed]);
  await w.start("analysis-demo");
  const asking = w.ask("Explain fees");
  await w.ask("Explain interest");
  assert.equal(calls.length, 3);
  resolve(complete);
  await asking;
});

test("unavailable model output falls back to server facts without claiming AI success", () => {
  assert.match(answerText({ ...result, narrative: { narrative_status: "unavailable", highlights: [] } }).at(-1), /unavailable/);
  assert.match(answerText({ ...result, narrative: { narrative_status: "skipped", highlights: [] } }).at(-1), /not used/);
});

test("new chat shows generated prose, not copied facts; legacy jobs still render", () => {
  const explanation = { status: "generated", paragraphs: [
    { text: "A useful explanation distinct from the finding.", fact_ids: ["fee"] },
  ] };
  assert.deepEqual(answerText({ ...result, explanation }), [explanation.paragraphs[0].text]);
  assert.deepEqual(answerText(result), [result.message, fact.text]);
});

test("generated explanation retains separate evidence for the UI disclosure", async () => {
  const explained = { ...complete, result: { ...result, explanation: {
    status: "generated", paragraphs: [{ text: "A distinct explanation.", fact_ids: ["fee"] }],
  } } };
  const { workspace: w } = setup([session(), report, explained]);
  await w.start("analysis-demo");
  await w.ask("Explain fees");
  assert.deepEqual(w.messages[0].evidence, [fact]);
  assert.deepEqual(w.messages[0].texts, ["A distinct explanation."]);
});
