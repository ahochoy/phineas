// The access token exists only in tab memory. Passwords are never retained here.
export class DemoAccess {
  constructor(api, changed = () => {}, now = Date.now) {
    this.api = api;
    this.changed = changed;
    this.now = now;
    this.required = true;
    this.loaded = false;
    this.expires = 0;
    this.busy = false;
    this.error = "";
    this.errorCode = "";
  }
  get unlocked() { return this.loaded && (!this.required || Boolean(this.api.accessToken) && this.now() < this.expires); }
  async load() {
    try {
      const result = await this.api.request("/demo/access");
      if (typeof result?.password_required !== "boolean") throw new Error();
      this.required = result.password_required;
      this.loaded = true;
    } catch (error) {
      // The repository-only FastAPI host has no edge login endpoint. Its 404
      // permits local coaching; the deployed Worker independently enforces auth.
      if (error.status === 404) { this.required = false; this.loaded = true; }
      else this.error = "Demo access could not load. Refresh to retry.";
    }
    this.changed();
  }
  async unlock(password) {
    if (this.busy) return;
    this.busy = true;
    this.error = "";
    this.errorCode = "";
    this.changed();
    try {
      const result = await this.api.request("/demo/unlock", { method: "POST", body: { password } });
      const expires = Date.parse(result?.expires_at);
      if (typeof result?.token !== "string" || !/^v1\.\d{10}\.[a-f0-9]{32}\.[a-f0-9]{64}$/.test(result.token) ||
          !Number.isFinite(expires) || expires <= this.now()) throw new Error();
      this.api.accessToken = result.token;
      this.expires = expires;
    } catch (error) {
      this.errorCode = error.code ?? "";
      this.error = error.code === "invalid_demo_password" ? "That password didn’t match. Try again." :
        error.code === "edge_rate_limit_reached" ? "Too many attempts. Wait a minute, then retry." :
          "Access could not be enabled. Check your connection and try again.";
    } finally { this.busy = false; this.changed(); }
  }
  lock() { this.api.accessToken = null; this.expires = 0; }
}
