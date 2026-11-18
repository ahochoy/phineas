// Public synthetic fixture browsing, independent of live sessions and chat.
export class SamplePreview {
  constructor(api, changed = () => {}) {
    this.api = api;
    this.changed = changed;
    this.data = null;
    this.sampleId = null;
    this.loading = false;
    this.failed = false;
    this.version = 0;
    this.cache = new Map();
  }

  async load(sampleId, retry = false) {
    if (!retry && this.sampleId === sampleId && (this.loading || this.data)) return;
    const version = ++this.version;
    this.sampleId = sampleId;
    this.data = this.cache.get(sampleId) || null;
    this.failed = false;
    this.loading = !this.data;
    this.changed(this);
    if (this.data) return;
    try {
      const data = await this.api.request(`/samples/${encodeURIComponent(sampleId)}/preview`);
      if (version !== this.version) return;
      if (data.sample_id !== sampleId || data.synthetic !== true || !Array.isArray(data.columns)
        || !data.columns.every((column) => typeof column === "string")
        || !Array.isArray(data.rows) || !data.rows.every((row) => Array.isArray(row)
          && row.length === data.columns.length && row.every((cell) => typeof cell === "string"))) {
        throw new Error("invalid_preview");
      }
      this.cache.set(sampleId, data);
      this.data = data;
    } catch {
      if (version === this.version) this.failed = true;
    } finally {
      if (version === this.version) {
        this.loading = false;
        this.changed(this);
      }
    }
  }
}

export function renderPreviewTable(document, data, name) {
  const table = document.createElement("table");
  const caption = document.createElement("caption");
  caption.textContent = `${name} · ${data.rows.length} synthetic records · read only`;
  table.append(caption);
  const head = document.createElement("thead");
  const header = document.createElement("tr");
  for (const label of ["Row", ...data.columns]) {
    const cell = document.createElement("th");
    cell.scope = "col";
    cell.textContent = label;
    header.append(cell);
  }
  head.append(header);
  table.append(head);
  const body = document.createElement("tbody");
  data.rows.forEach((row, index) => {
    const line = document.createElement("tr");
    const number = document.createElement("th");
    number.scope = "row";
    number.textContent = String(index + 1);
    line.append(number);
    row.forEach((value, column) => {
      const cell = document.createElement("td");
      cell.textContent = value;
      if (data.columns[column] === "amount") cell.className = "numeric";
      line.append(cell);
    });
    body.append(line);
  });
  table.append(body);
  return table;
}
