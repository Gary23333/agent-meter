// Decrypt the Claude desktop Chromium cookie jar in memory (read-only).
// The keychain password and the encrypted rows arrive over stdin and the
// decrypted jar leaves over stdout; nothing touches disk or a log. Run with
// plain node: Claude's Electron ships the RunAsNode fuse disabled, so the
// caller supplies the real UA assembled statically from the app bundle.
import { createDecipheriv, createHash, pbkdf2Sync } from "node:crypto";

const INPUT_LIMIT = 1024 * 1024;

function reply(value) {
  process.stdout.write(JSON.stringify(value), () => process.exit(value.ok ? 0 : 1));
}

function decryptValue(blob, key, hostKey, dbVersion) {
  if (blob.subarray(0, 3).toString() !== "v10") throw { reason: "unsupported_format" };
  let plain;
  try {
    const decipher = createDecipheriv("aes-128-cbc", key, Buffer.alloc(16, 0x20));
    plain = Buffer.concat([decipher.update(blob.subarray(3)), decipher.final()]);
  } catch {
    throw { reason: "decrypt_failed" };
  }
  if (dbVersion >= 24) {
    // Cookie DB v24 prepends sha256(host_key); a mismatch means a wrong key.
    const digest = createHash("sha256").update(hostKey).digest();
    if (plain.length < 32 || !plain.subarray(0, 32).equals(digest)) throw { reason: "decrypt_failed" };
    plain = plain.subarray(32);
  }
  return plain.toString("utf8");
}

function decrypt(request) {
  if (typeof request?.password !== "string" || !request.password) throw { reason: "invalid_format" };
  if (typeof request?.userAgent !== "string" || !request.userAgent) throw { reason: "invalid_format" };
  if (!Number.isInteger(request?.dbVersion) || request.dbVersion < 0) throw { reason: "invalid_format" };
  if (!Array.isArray(request?.cookies)) throw { reason: "invalid_format" };
  const key = pbkdf2Sync(request.password, "saltysalt", 1003, 16, "sha1");
  const cookies = request.cookies.map((row) => {
    if (typeof row?.host_key !== "string" || typeof row?.name !== "string") throw { reason: "invalid_format" };
    if (typeof row.encrypted_value === "string" && row.encrypted_value) {
      const value = decryptValue(Buffer.from(row.encrypted_value, "base64"), key, row.host_key, request.dbVersion);
      return { name: row.name, value };
    }
    if (typeof row.value === "string") return { name: row.name, value: row.value };
    throw { reason: "invalid_format" };
  });
  return { user_agent: request.userAgent, cookies };
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
    reply({ ok: true, ...decrypt(request) });
  } catch (error) {
    reply({ ok: false, reason: error?.reason || "helper_protocol" });
  }
});