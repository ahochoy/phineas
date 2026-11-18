// Trusted edge boundary. Never log requests, capabilities, bodies, or secrets.
import { configured, passwordMatches, issueAccess, verifyAccess } from "./demo-auth.mjs";
const ASSETS = new Set(["/", "/index.html", "/styles.css", "/app.mjs", "/client.mjs", "/sample-preview.mjs", "/demo-access.mjs"]);
const ORIGIN = "https://51b01wb0w6.execute-api.us-east-2.amazonaws.com/public";
const CAP = "[A-Za-z0-9_-]{20,200}";
const JOB = "[A-Za-z0-9_-]{20,200}";
const CSP = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'";
const SAFE_ERRORS = new Set(["session_unavailable", "job_unavailable", "unknown_sample",
  "question_job_limit_reached", "demo_daily_job_limit_reached", "demo_admissions_paused",
  "async_questions_not_configured", "job_queue_unavailable", "job_store_busy",
  "session_store_unavailable", "request_id_conflict"]);

function secure(response) {
  const result = new Response(response.body, response);
  result.headers.set("Cache-Control", "no-store");
  result.headers.set("Referrer-Policy", "no-referrer");
  result.headers.set("X-Content-Type-Options", "nosniff");
  result.headers.set("Content-Security-Policy", CSP);
  result.headers.set("Permissions-Policy", "camera=(), microphone=(), geolocation=()");
  result.headers.delete("Set-Cookie");
  return result;
}

function error(status, detail) {
  return secure(Response.json({ detail }, { status,
    headers: status === 429 ? { "Retry-After": "60" } : {} }));
}

function route(method, path) {
  if (method === "GET" && path === "/demo/access") return "access";
  if (method === "POST" && path === "/demo/unlock") return "unlock";
  if (method === "GET" && ["/health", "/samples", "/questions/suggestions"].includes(path)) return "read";
  if (method === "GET" && /^\/samples\/(analysis-demo|credit-card-demo)\/preview$/.test(path)) return "read";
  if (method === "POST" && path === "/sessions") return "create";
  if (method === "GET" && new RegExp(`^/sessions/${CAP}/report$`).test(path)) return "read";
  if (method === "GET" && new RegExp(`^/sessions/${CAP}/jobs/${JOB}$`).test(path)) return "read";
  if (method === "POST" && new RegExp(`^/sessions/${CAP}/question-jobs$`).test(path)) return "question";
  if (method === "DELETE" && new RegExp(`^/sessions/${CAP}$`).test(path)) return "purge";
  return null;
}

async function bounded(stream, max) {
  if (!stream) return new Uint8Array();
  const reader = stream.getReader();
  const parts = [];
  let size = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > max) {
        await reader.cancel();
        throw new RangeError("body_limit");
      }
      parts.push(value);
    }
  } finally { reader.releaseLock(); }
  const result = new Uint8Array(size);
  let offset = 0;
  for (const part of parts) { result.set(part, offset); offset += part.length; }
  return result;
}

function validBody(kind, body) {
  if (!body || typeof body !== "object" || Array.isArray(body)) return false;
  const keys = Object.keys(body).sort().join(",");
  if (kind === "unlock") return keys === "password" && typeof body.password === "string" && body.password.length > 0 && body.password.length <= 128;
  if (kind === "create") return keys === "sample_id" && ["analysis-demo", "credit-card-demo"].includes(body.sample_id);
  return keys === "question,request_id" && typeof body.question === "string" &&
    body.question.trim().length > 0 && body.question.length <= 200 &&
    typeof body.request_id === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(body.request_id);
}

export async function handle(request, env, upstream = globalThis.fetch.bind(globalThis)) {
  try {
    const url = new URL(request.url);
    if (!url.pathname.startsWith("/api/") && url.pathname !== "/api") {
      if (!["GET", "HEAD"].includes(request.method) || !ASSETS.has(url.pathname) || url.search) return error(404, "not_found");
      // Only public web files are addressable, even though web/ also has README.
      return secure(await env.ASSETS.fetch(new Request(url.href, { method: request.method })));
    }
    const path = url.pathname.slice(4);
    const kind = route(request.method, path);
    if (!kind || url.search || path.includes("%")) return error(404, "not_found");
    if (env.DEMO_ENABLED !== "true" || !/^[A-Za-z0-9_-]{64}$/.test(env.ORIGIN_TOKEN ?? "")) return error(503, "demo_unavailable");
    const callerOrigin = request.headers.get("Origin");
    if ((callerOrigin && callerOrigin !== url.origin) || request.headers.get("Sec-Fetch-Site") === "cross-site") return error(403, "request_rejected");
    const ip = request.headers.get("CF-Connecting-IP");
    if (!ip) return error(503, "demo_unavailable");
    if (!(await env.API_LIMIT.limit({ key: ip })).success) return error(429, "edge_rate_limit_reached");
    const limiter = kind === "unlock" ? env.UNLOCK_LIMIT : kind === "create" ? env.SESSION_LIMIT : kind === "question" ? env.QUESTION_LIMIT : null;
    if (limiter && !(await limiter.limit({ key: ip })).success) return error(429, "edge_rate_limit_reached");
    if (kind === "unlock" && !limiter) return error(503, "demo_unavailable");
    if (kind === "access") return secure(Response.json({ password_required: true }));
    const protectedRoute = kind === "create" || kind === "question" || (kind === "read" && path.startsWith("/sessions/"));
    if (kind === "unlock" || protectedRoute) {
      if (!configured(env)) return error(503, "demo_unavailable");
      if (protectedRoute && !(await verifyAccess(env.DEMO_AUTH_KEY, request.headers.get("Authorization")))) {
        return error(401, "demo_password_required");
      }
    }
    let body;
    if (request.method === "POST") {
      if (request.headers.get("Content-Type")?.split(";")[0].trim().toLowerCase() !== "application/json") return error(415, "json_required");
      const declared = request.headers.get("Content-Length");
      if (declared && (!/^\d+$/.test(declared) || Number(declared) > 4096)) return error(413, "request_too_large");
      let parsed;
      try { parsed = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(await bounded(request.body, 4096))); }
      catch (failure) { return error(failure instanceof RangeError ? 413 : 400, "invalid_request"); }
      if (!validBody(kind, parsed)) return error(400, "invalid_request");
      body = JSON.stringify(parsed);
    } else if (request.body !== null) {
      // Incoming HTTP requests can have a non-null stream with zero bytes.
      // Validate bytes, not stream presence; purge must remain bodyless.
      try {
        if ((await bounded(request.body, 1)).byteLength !== 0) return error(400, "invalid_request");
      } catch { return error(400, "invalid_request"); }
    }
    if (kind === "unlock") {
      if (!(await passwordMatches(env, JSON.parse(body).password))) return error(401, "invalid_demo_password");
      return secure(Response.json(await issueAccess(env.DEMO_AUTH_KEY)));
    }
    // Construct headers afresh: no cookies, authorization, forwarding headers,
    // visitor origin token, or request metadata reaches AWS.
    const response = await upstream(ORIGIN + path, {
      method: request.method, body, redirect: "manual",
      signal: AbortSignal.timeout(15_000),
      headers: { "Accept": "application/json", "Content-Type": "application/json",
        "x-phineas-origin-token": env.ORIGIN_TOKEN },
    });
    if (response.status >= 300 && response.status < 400 || response.status === 401 || response.status === 403) {
      await response.body?.cancel();
      return error(502, "origin_unavailable");
    }
    if (response.status === 204) return secure(new Response(null, { status: 204 }));
    const raw = await bounded(response.body, 131072);
    let payload;
    try { payload = JSON.parse(new TextDecoder().decode(raw)); }
    catch { return error(502, "origin_unavailable"); }
    if (!response.ok) return error(response.status >= 500 ? 503 : response.status,
      SAFE_ERRORS.has(payload?.detail) ? payload.detail : "request_failed");
    return secure(Response.json(payload, { status: response.status }));
  } catch {
    return error(503, "demo_unavailable");
  }
}

export default { fetch: (request, env) => handle(request, env) };
