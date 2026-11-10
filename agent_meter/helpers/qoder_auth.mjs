// Decrypt the Qoder CN desktop credential file in memory.
//
// The keychain password arrives through stdin and the token leaves through
// stdout, so neither is written to disk or logged. Run with the Qoder app's
// own Electron runtime (ELECTRON_RUN_AS_NODE=1) — the standard library has
// no AES, and the client ships one.
import { createDecipheriv, pbkdf2Sync } from "node:crypto";
import { readFileSync } from "node:fs";

const INPUT_LIMIT = 65536;

function reply(value) {
  process.stdout.write(JSON.stringify(value), () => process.exit(value.ok ? 0 : 1));
}

function decrypt(request) {
  if (typeof request?.password !== "string" || !request.password) throw { reason: "invalid_format" };
  if (typeof request?.authFile !== "string" || !request.authFile) throw { reason: "invalid_format" };
  let raw;
  try {
    raw = readFileSync(request.authFile);
  } catch {
    throw { reason: "auth_missing" };
  }
  if (raw.subarray(0, 3).toString() !== "v10") throw { reason: "unsupported_format" };
  // Chromium's macOS "v10" envelope: AES-128-CBC under a PBKDF2 key with a
  // fixed space IV — the same rule as the Claude desktop credential study.
  const key = pbkdf2Sync(request.password, "saltysalt", 1003, 16, "sha1");
  let plain;
  try {
    const decipher = createDecipheriv("aes-128-cbc", key, Buffer.alloc(16, 0x20));
    plain = Buffer.concat([decipher.update(raw.subarray(3)), decipher.final()]);
  } catch {
    throw { reason: "decrypt_failed" };
  }
  let session;
  try {
    session = JSON.parse(plain.toString("utf8"));
  } catch {
    throw { reason: "unsupported_format" };
  }
  if (!session || typeof session !== "object" || Array.isArray(session)) throw { reason: "unsupported_format" };
  if (typeof session.token !== "string" || !session.token) throw { reason: "token_missing" };
  return {
    token: session.token,
    expiresAt: typeof session.expiresAt === "string" ? session.expiresAt : null,
  };
}

let chunks = [];
let size = 0;

process.stdin.on("data", (chunk) => {
  size += chunk.length;
  if (size > INPUT_LIMIT) reply({ ok: false, reason: "invalid_format" });
  else chunks.push(chunk);
});
process.stdin.on("error", () => reply({ ok: false, reason: "helper_protocol" }));
process.stdin.on("end", () => {
  let request;
  try {
    request = JSON.parse(Buffer.concat(chunks).toString("utf8"));
  } catch {
    reply({ ok: false, reason: "invalid_format" });
    return;
  }
  chunks = [];
  try {
    reply({ ok: true, session: decrypt(request) });
  } catch (error) {
    reply({ ok: false, reason: error?.reason || "helper_protocol" });
  }
});
