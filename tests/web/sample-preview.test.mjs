import test from "node:test";
import assert from "node:assert/strict";
import { SamplePreview, renderPreviewTable } from "../../web/sample-preview.mjs";

const fixture = (sample_id) => ({ sample_id, synthetic: true,
  columns: ["posted_date", "description", "amount"],
  rows: [["2026-01-02", "Synthetic merchant", "12.99"]] });

test("preview uses only fixture endpoint and caches the public sample in memory", async () => {
  const calls = [];
  const preview = new SamplePreview({ request: async (path) => { calls.push(path); return fixture("analysis-demo"); } });
  await preview.load("analysis-demo");
  await preview.load("analysis-demo");
  assert.deepEqual(calls, ["/samples/analysis-demo/preview"]);
  assert.equal(preview.loading, false);
  assert.equal(preview.failed, false);
});

test("switching samples ignores a late response from the prior selection", async () => {
  let resolve;
  const first = new Promise((done) => { resolve = done; });
  let count = 0;
  const preview = new SamplePreview({ request: async () => ++count === 1 ? first : fixture("credit-card-demo") });
  const old = preview.load("analysis-demo");
  await preview.load("credit-card-demo");
  resolve(fixture("analysis-demo"));
  await old;
  assert.equal(preview.data.sample_id, "credit-card-demo");
});

test("preview failure can retry without changing the session or invoking analysis", async () => {
  let count = 0;
  const preview = new SamplePreview({ request: async () => {
    if (++count === 1) throw new Error("SECRET");
    return fixture("analysis-demo");
  } });
  await preview.load("analysis-demo");
  assert.equal(preview.failed, true);
  assert.equal(preview.data, null);
  await preview.load("analysis-demo", true);
  assert.equal(preview.failed, false);
  assert.equal(preview.data.rows.length, 1);
});

test("non-synthetic, mismatched, or malformed preview data is not rendered", async () => {
  for (const data of [{ ...fixture("analysis-demo"), synthetic: false }, fixture("other"),
    { ...fixture("analysis-demo"), rows: [["missing cells"]] }]) {
    const preview = new SamplePreview({ request: async () => data });
    await preview.load("analysis-demo");
    assert.equal(preview.failed, true);
    assert.equal(preview.data, null);
  }
});

test("table preserves every cell as text, with scoped headers and no HTML interpolation", () => {
  const document = { createElement: (tag) => ({ tag, children: [], append(...nodes) { this.children.push(...nodes); } }) };
  const data = fixture("analysis-demo");
  data.rows.push(["2026-01-03", "<img src=x onerror=alert(1)>", "3.00"]);
  const table = renderPreviewTable(document, data, "Synthetic sample");
  assert.equal(table.tag, "table");
  assert.equal(table.children[0].tag, "caption");
  const header = table.children[1].children[0];
  assert.equal(header.children.length, 4);
  assert.ok(header.children.every((cell) => cell.scope === "col"));
  const rows = table.children[2].children;
  assert.equal(rows.length, 2);
  assert.equal(rows[1].children[0].scope, "row");
  assert.equal(rows[1].children[2].textContent, data.rows[1][1]);
  assert.equal(rows[1].children[3].className, "numeric");
});
