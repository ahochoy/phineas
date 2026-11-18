// Same-origin API and session lifecycle. No credentials, IDs, or questions are
// written to browser storage, URLs in the address bar, or application logs.
export class ApiError extends Error {
  constructor(status, code) {
    super(code);
    this.status = status;
    this.code = code;
  }
}

export class Api {
  // Browser-native fetch needs the Window receiver, not this Api instance.
  constructor(fetcher = globalThis.fetch.bind(globalThis)) { this.fetcher = fetcher; this.accessToken = null; }

  async request(path, { method = "GET", body, signal } = {}) {
    let response;
    try {
      response = await this.fetcher(`/api${path}`, {
        method, credentials: "omit", cache: "no-store", referrerPolicy: "no-referrer",
        headers: { ...(body === undefined ? {} : { "Content-Type": "application/json" }),
          ...(this.accessToken ? { Authorization: `Bearer ${this.accessToken}` } : {}) },
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(20_000)]) : AbortSignal.timeout(20_000),
      });
    } catch {
      throw new ApiError(0, "network_unavailable");
    }
    if (!response.ok) {
      // Fixed reason-code allowlist: never expose server validation payloads,
      // proxy error pages, request inputs, or exception strings to the UI.
      const allowed = new Set([
        "session_unavailable", "job_unavailable", "question_job_limit_reached",
        "demo_daily_job_limit_reached", "demo_admissions_paused",
        "async_questions_not_configured", "job_queue_unavailable", "job_store_busy",
        "session_store_unavailable", "request_id_conflict",
        "demo_password_required", "invalid_demo_password", "demo_unavailable", "edge_rate_limit_reached",
      ]);
      const data = await response.json().catch(() => null);
      const code = typeof data?.detail === "string" && allowed.has(data.detail)
        ? data.detail : "request_failed";
      if (code === "demo_password_required") this.accessToken = null;
      throw new ApiError(response.status, code);
    }
    if (response.status === 204) return null;
    try { return await response.json(); }
    catch { throw new ApiError(0, "invalid_response"); }
  }
}

export function answerText(result) {
  if (result.explanation?.status === "generated") {
    return result.explanation.paragraphs.map((paragraph) => paragraph.text);
  }
  const narrative = result.narrative;
  // Server renders the facts. Never calculate or invent financial conclusions.
  const facts = narrative.narrative_status === "generated" && narrative.highlights.length
    ? narrative.highlights : result.facts;
  const texts = [result.message, ...facts.map((fact) => fact.text)];
  if (narrative.narrative_status === "unavailable") {
    texts.push("AI selection is unavailable. The deterministic findings are shown instead.");
  } else if (narrative.narrative_status === "skipped" && facts.length) {
    texts.push("Deterministic answer. AI selection was not used.");
  }
  return texts;
}

export class Workspace {
  constructor({ api = new Api(), changed = () => {}, now = Date.now,
    uuid = () => crypto.randomUUID(), sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms)) } = {}) {
    Object.assign(this, { api, changed, now, uuid, sleep });
    this.session = null;
    this.report = null;
    this.sampleId = null;
    this.busy = null;
    this.messages = [];
    this.error = null;
    this.retry = null;
    this.pending = null;
    this.generation = 0;
    this.blocked = false;
    this.notice = "Choose a synthetic statement to start.";
  }

  emit() { this.changed(this); }
  path(suffix = "") { return `/sessions/${encodeURIComponent(this.session.session_id)}${suffix}`; }
  touch() {
    this.session.idle_expires_at = new Date(Math.min(this.now() + 30 * 60_000,
      Date.parse(this.session.absolute_expires_at))).toISOString();
  }

  clear(notice) {
    this.generation += 1;
    this.abort?.abort();
    this.session = this.report = this.pending = this.sampleId = null;
    this.busy = this.error = this.retry = null;
    this.messages = [];
    this.blocked = false;
    this.notice = notice;
    this.emit();
  }

  expireIfNeeded() {
    if (this.session && this.now() >= Math.min(Date.parse(this.session.idle_expires_at),
      Date.parse(this.session.absolute_expires_at))) {
      this.clear("This session has expired. Start a new sample analysis.");
      return true;
    }
    return false;
  }

  fail(error) {
    const code = error instanceof ApiError ? error.code : "request_failed";
    if (code === "session_unavailable") {
      this.clear("This session is no longer available. Start a new sample analysis.");
      return;
    }
    this.error = code;
    if (["question_job_limit_reached", "demo_daily_job_limit_reached", "demo_admissions_paused"].includes(code)) {
      this.blocked = true;
      this.retry = null;
    }
  }

  async start(sampleId) {
    if (this.busy || this.session) return;
    this.busy = "starting";
    this.error = this.retry = null;
    this.emit();
    const generation = this.generation;
    try {
      const session = await this.api.request("/sessions", { method: "POST", body: { sample_id: sampleId } });
      if (generation !== this.generation) return;
      this.session = session;
      this.sampleId = sampleId;
      this.retry = "report";
      const report = await this.api.request(this.path("/report"));
      if (generation !== this.generation) return;
      this.report = report;
      this.touch();
      this.retry = null;
      this.notice = "Analysis ready. Choose a question button to explore the findings.";
    } catch (error) {
      if (generation === this.generation) this.fail(error);
    } finally {
      if (generation === this.generation) { this.busy = null; this.emit(); }
    }
  }

  async reloadReport() {
    if (!this.session || this.busy || this.expireIfNeeded()) return;
    const generation = this.generation;
    this.busy = "loading";
    this.error = null;
    this.emit();
    try {
      const report = await this.api.request(this.path("/report"));
      if (generation !== this.generation) return;
      this.report = report;
      this.touch();
      this.retry = null;
      this.notice = "Analysis ready.";
    } catch (error) {
      if (generation === this.generation) this.fail(error);
    } finally {
      if (generation === this.generation) { this.busy = null; this.emit(); }
    }
  }

  async ask(question, replay = false) {
    if (!this.session || this.busy || this.blocked || this.expireIfNeeded()) return;
    question = question.trim();
    if (!question || question.length > 200) return;
    const pending = replay && this.pending ? this.pending : { request_id: this.uuid(), question };
    if (!replay) this.messages.push({ question, texts: null });
    this.pending = pending;
    this.busy = "asking";
    this.retry = null;
    this.error = null;
    this.abort = new AbortController();
    const signal = this.abort.signal;
    const generation = this.generation;
    this.notice = "Phineas is working on your question…";
    this.emit();
    try {
      let job = await this.api.request(this.path("/question-jobs"), { method: "POST", body: pending, signal });
      if (generation !== this.generation) return;
      this.touch();
      const deadline = this.now() + 180_000;
      while (job.state === "pending" || job.state === "running") {
        if (this.now() >= deadline) throw new ApiError(0, "question_wait_timeout");
        await this.sleep(2000);
        if (generation !== this.generation || signal.aborted) return;
        job = await this.api.request(this.path(`/jobs/${encodeURIComponent(job.job_id)}`), { signal });
        if (generation !== this.generation) return;
        this.touch();
      }
      if (job.state !== "succeeded" || !job.result) {
        this.pending = null;
        throw new ApiError(0, "question_failed");
      }
      this.messages.at(-1).texts = answerText(job.result);
      this.messages.at(-1).evidence = job.result.explanation?.status === "generated" ? job.result.facts : [];
      this.pending = null;
      this.notice = "Answer ready. Review the findings and their limitations.";
    } catch (error) {
      if (generation === this.generation) {
        this.retry = this.pending ? "question" : null;
        this.fail(error);
      }
    } finally {
      if (generation === this.generation) { this.busy = null; this.emit(); }
    }
  }

  async end() {
    if (!this.session || ["starting", "deleting"].includes(this.busy)) return;
    // Invalidate in-flight UI work before purging so late responses cannot
    // redisplay data or restart polling. A failed purge retains the capability.
    this.generation += 1;
    this.abort?.abort();
    const generation = this.generation;
    this.busy = "deleting";
    this.error = this.retry = null;
    this.emit();
    try {
      await this.api.request(this.path(), { method: "DELETE" });
      if (generation === this.generation) this.clear("Session ended. Stored session records were purged.");
    } catch (error) {
      if (generation === this.generation) {
        if (error instanceof ApiError && error.code === "session_unavailable") {
          this.clear("This session is no longer available.");
        } else {
          this.busy = null;
          this.error = "purge_unconfirmed";
          this.notice = "Deletion was not confirmed. Keep this page open and retry End session.";
          this.emit();
        }
      }
    }
  }
}
