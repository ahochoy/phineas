// Shared-password demo access, not user identity. No persistence or logging.
const encode = (value) => new TextEncoder().encode(value);
const hex = (bytes) => Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
const now = () => Math.floor(Date.now() / 1000);
export const ACCESS_SECONDS = 4 * 60 * 60;

export function configured(env) {
  return typeof env.DEMO_PASSWORD === "string" && env.DEMO_PASSWORD.length >= 12 && env.DEMO_PASSWORD.length <= 128 &&
    /^[A-Za-z0-9_-]{64}$/.test(env.DEMO_AUTH_KEY ?? "");
}

async function key(secret) {
  return crypto.subtle.importKey("raw", encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign", "verify"]);
}

export async function passwordMatches(env, supplied) {
  if (!configured(env) || typeof supplied !== "string" || supplied.length > 128) return false;
  const signingKey = await key(env.DEMO_AUTH_KEY);
  const expected = await crypto.subtle.sign("HMAC", signingKey, encode("phineas-password:" + env.DEMO_PASSWORD));
  // HMAC verification avoids a character-by-character password comparison.
  return crypto.subtle.verify("HMAC", signingKey, expected, encode("phineas-password:" + supplied));
}

export async function issueAccess(secret, seconds = now()) {
  const expires = seconds + ACCESS_SECONDS;
  const nonce = hex(crypto.getRandomValues(new Uint8Array(16)));
  const payload = `v1.${expires}.${nonce}`;
  const signature = await crypto.subtle.sign("HMAC", await key(secret), encode("phineas-access:" + payload));
  return { token: `${payload}.${hex(new Uint8Array(signature))}`, expires_at: new Date(expires * 1000).toISOString() };
}

export async function verifyAccess(secret, authorization, seconds = now()) {
  if (typeof authorization !== "string") return false;
  const match = /^Bearer (v1\.(\d{10})\.[a-f0-9]{32})\.([a-f0-9]{64})$/.exec(authorization);
  if (!match) return false;
  const expires = Number(match[2]);
  if (expires <= seconds || expires > seconds + ACCESS_SECONDS) return false;
  const signature = Uint8Array.from(match[3].match(/../g), (value) => Number.parseInt(value, 16));
  return crypto.subtle.verify("HMAC", await key(secret), signature, encode("phineas-access:" + match[1]));
}
