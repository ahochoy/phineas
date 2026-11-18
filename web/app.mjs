import { Api, Workspace } from "./client.mjs";
import { SamplePreview, renderPreviewTable } from "./sample-preview.mjs";
import { DemoAccess } from "./demo-access.mjs";

const names = { "analysis-demo": "Everyday credit card", "credit-card-demo": "A simpler statement" };
const titles = { subscription: "Possible monthly subscription", duplicate: "Possible duplicate purchases",
  fee: "Fees", interest: "Interest", coverage: "What this analysis includes" };
const errors = {
  network_unavailable: "The connection was interrupted. If a question was submitted, Retry uses the same request ID rather than creating another job.",
  question_wait_timeout: "The answer is taking longer than expected. Retry checks the same request; it does not create another question job.",
  question_failed: "This question could not be completed. Your analysis remains available. A new question uses another session slot.",
  question_job_limit_reached: "This session has used its 10 question slots. You can still read your findings and end the session.",
  demo_daily_job_limit_reached: "The demo’s shared daily question allowance has been reached. You can still read your findings and end the session.",
  demo_admissions_paused: "New questions are temporarily paused. Your findings and End session remain available.",
  async_questions_not_configured: "Async questions are not configured on this server. The deterministic analysis still works; cloud configuration is needed for queued answers.",
  job_queue_unavailable: "Question delivery could not be confirmed. Retry safely reuses the same request ID.",
  job_store_busy: "The service is busy. Please retry shortly.",
  session_store_unavailable: "Session storage is temporarily unavailable. Please retry shortly.",
  job_unavailable: "This question job is no longer available. You can try another question while the session remains active.",
  purge_unconfirmed: "Purge was not confirmed. Your session access is retained so you can retry End session. We have not claimed the records were deleted.",
  request_failed: "The request could not be completed. Please retry shortly.",
  invalid_response: "The server returned an unexpected response. Please retry shortly.",
  demo_password_required: "Demo access is locked or has expired. Enter the demo password to continue. End session & purge remains available.",
  demo_unavailable: "The demo is temporarily unavailable. Please retry later.",
  edge_rate_limit_reached: "Too many requests. Wait a minute, then retry.",
};
const $ = (selector) => document.querySelector(selector);
let ready = false;
let paintedReport = null;
let paintedMessages = null;
let connectionFailed = false;
const api = new Api();
const access = new DemoAccess(api, render);
const workspace = new Workspace({ api, changed: render });
const preview = new SamplePreview(api, (state) => {
  $("#sample-preview-status").textContent = state.loading ? "Loading synthetic records…"
    : state.failed ? "The sample preview could not load. Retry to view its records."
    : state.data ? "All source records are shown below. No analysis session was created by this preview." : "";
  $("#sample-preview-retry").hidden = !state.failed;
  const container = $("#sample-preview-table");
  container.setAttribute("aria-busy", String(state.loading));
  container.replaceChildren();
  container.hidden = !state.data;
  if (state.data) container.append(renderPreviewTable(document, state.data, names[state.sampleId]));
});

function selectedSample() { return document.querySelector('input[name="sample"]:checked').value; }

$("#sample-preview").addEventListener("toggle", () => {
  if ($("#sample-preview").open) void preview.load(selectedSample());
});
for (const input of document.querySelectorAll('input[name="sample"]')) {
  input.addEventListener("change", () => {
    if ($("#sample-preview").open) void preview.load(selectedSample());
  });
}
$("#sample-preview-retry").addEventListener("click", () => { void preview.load(selectedSample(), true); });

function paragraph(text, className) {
  const node = document.createElement("p");
  node.textContent = text;
  if (className) node.className = className;
  return node;
}

function assistant(texts, evidence = []) {
  const node = document.createElement("div");
  node.className = "assistant-message";
  node.append(paragraph("PHINEAS", "speaker"));
  for (const text of texts) node.append(paragraph(text));
  if (evidence.length) {
    const details = document.createElement("details");
    details.className = "supporting-facts";
    const summary = document.createElement("summary");
    summary.textContent = "Supporting findings";
    details.append(summary);
    for (const fact of evidence) details.append(paragraph(fact.text));
    node.append(details);
  }
  return node;
}

function render() {
  const state = workspace;
  const hasSession = Boolean(state.session);
  const canAsk = access.unlocked && hasSession && Boolean(state.report) && !state.busy && !state.blocked;
  $("#start").disabled = !ready || !access.unlocked || hasSession || Boolean(state.busy);
  $("#demo-access").hidden = access.loaded && !access.required;
  $("#access-form").hidden = access.unlocked;
  $("#demo-password").disabled = !access.loaded || access.busy;
  $("#unlock").disabled = !access.loaded || access.busy;
  $("#unlock").textContent = access.busy ? "Checking…" : "Enable demo";
  $("#access-error").textContent = access.error;
  $("#access-error").hidden = !access.error;
  $("#demo-password").setAttribute("aria-invalid", String(access.errorCode === "invalid_demo_password"));
  $("#access-status").textContent = access.unlocked ? "Demo enabled for this tab, for up to four hours. Refreshing requires the password again."
    : access.loaded ? "Analysis and AI questions are locked. The password is shared separately with invited reviewers."
      : "Checking demo access…";
  $("#start-label").textContent = state.busy === "starting" ? "Starting analysis…" : "Start analysis";
  for (const input of document.querySelectorAll('input[name="sample"]')) input.disabled = hasSession || Boolean(state.busy);
  $("#reset").disabled = !hasSession || ["starting", "deleting"].includes(state.busy);
  $("#reset").textContent = state.busy === "deleting" ? "Purging…" : "End session & purge";
  for (const button of $("#suggestions").children) button.disabled = !canAsk;
  $("#status").textContent = ready ? state.notice : "Connecting to Phineas…";
  const error = connectionFailed ? "Phineas could not connect. Check your connection, then retry." : errors[state.error];
  $("#error-box").hidden = !error;
  $("#error-message").textContent = error || "";
  $("#retry").hidden = !(connectionFailed || (state.retry && !state.busy));
  $("#retry").textContent = state.retry === "question" ? "Retry same question" : "Retry";
  $("#findings-empty").hidden = Boolean(state.report);
  $("#findings-content").hidden = !state.report;
  $("#findings-heading").closest("section").setAttribute("aria-busy", String(["starting", "loading"].includes(state.busy)));
  $("#chat-heading").closest("section").setAttribute("aria-busy", String(state.busy === "asking"));

  if (state.report !== paintedReport) {
    paintedReport = state.report;
    $("#findings").replaceChildren();
    $("#sample-name").textContent = "";
    for (const id of ["outflow", "inflow", "transaction-count"]) $(`#${id}`).textContent = "";
    if (state.report) {
      const { analysis, facts } = state.report;
      $("#sample-name").textContent = `${names[state.sampleId]} · synthetic USD statement`;
      // Decimal strings are displayed, never summed or analyzed in JavaScript.
      $("#outflow").textContent = `$${analysis.summary.total_outflow}`;
      $("#inflow").textContent = `$${analysis.summary.total_inflow}`;
      $("#transaction-count").textContent = analysis.summary.transaction_count;
      for (const fact of facts) {
        const article = document.createElement("article");
        article.className = "finding";
        const heading = document.createElement("h3");
        heading.textContent = titles[fact.fact_id.split("_")[0]] || "Finding";
        article.append(heading, paragraph(fact.text));
        $("#findings").append(article);
      }
    }
  }
  const messageKey = JSON.stringify([state.messages, state.busy]);
  if (messageKey !== paintedMessages) {
    paintedMessages = messageKey;
    $("#conversation").replaceChildren();
    if (!state.messages.length) $("#conversation").append(assistant([
      hasSession ? "Your sample is ready. Choose a question above to explore the findings."
        : "Choose a sample to explore what your statement can tell you.",
    ]));
    for (const [index, message] of state.messages.entries()) {
      $("#conversation").append(paragraph(message.question, "user-message"));
      const waiting = state.busy === "asking" && index === state.messages.length - 1;
      $("#conversation").append(assistant(message.texts || [waiting ? "Working on your question…" : "No completed answer received."], message.evidence));
    }
    $("#conversation").scrollTop = $("#conversation").scrollHeight;
  }
  renderSessionNote();
}

function renderSessionNote() {
  const session = workspace.session;
  if (!session) {
    $("#session-note").textContent = "No active session. Session access and chat stay in this tab’s memory only.";
    return;
  }
  const remaining = Math.max(0, Math.ceil((Math.min(Date.parse(session.idle_expires_at),
    Date.parse(session.absolute_expires_at)) - Date.now()) / 60_000));
  $("#session-note").textContent = `Active session · approximately ${remaining} min remaining without activity. Four-hour maximum. End this session before choosing another sample.`;
}

async function connect() {
  connectionFailed = false;
  try {
    const [samples, questions] = await Promise.all([
      api.request("/samples"), api.request("/questions/suggestions"),
    ]);
    if (!Array.isArray(samples) || !Array.isArray(questions)) throw new Error();
    for (const input of document.querySelectorAll('input[name="sample"]')) {
      if (!samples.includes(input.value)) throw new Error();
    }
    $("#suggestions").replaceChildren();
    for (const question of questions) {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = question;
      button.addEventListener("click", () => { void workspace.ask(question); });
      $("#suggestions").append(button);
    }
    ready = true;
  } catch { connectionFailed = true; }
  render();
}

$("#sample-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const sampleId = new FormData(event.currentTarget).get("sample");
  if (access.unlocked && Object.hasOwn(names, sampleId)) void workspace.start(sampleId);
});
$("#access-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const password = $("#demo-password").value;
  $("#demo-password").value = "";
  await access.unlock(password);
  if (access.unlocked) { workspace.error = null; render(); }
  if (!access.unlocked) $("#demo-password").focus();
});
$("#reset").addEventListener("click", () => { void workspace.end(); });
$("#retry").addEventListener("click", () => {
  if (connectionFailed) void connect();
  else if (workspace.retry === "report") void workspace.reloadReport();
  else if (workspace.retry === "question" && workspace.pending) void workspace.ask(workspace.pending.question, true);
});
setInterval(() => {
  workspace.expireIfNeeded();
  render();
}, 10_000);
document.addEventListener("visibilitychange", () => { workspace.expireIfNeeded(); });
window.addEventListener("pagehide", () => { access.lock(); workspace.clear("Session access cleared from this tab."); });
void access.load();
void connect();
