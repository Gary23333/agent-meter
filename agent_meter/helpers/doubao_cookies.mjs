// 解密豆包客户端（Chromium）的 Cookie 值，供本地后端只读使用。
//
// 密码与 Cookie 只经由 stdin/stdout 管道传递，不写文件、不打印。
// 输入：{password, cookies:[{host, name, value(base64), expires_utc}]}
// 输出：{ok:true, cookie:"name=value; ..."} 或 {ok:false, reason}
import { createDecipheriv, pbkdf2Sync, createHash } from "node:crypto";

const INPUT_LIMIT = 65536;
const CHROMIUM_EPOCH = 11644473600; // 1601-01-01 到 1970-01-01 的秒数
const HOST = "doubao.com";

function reply(value) {
  process.stdout.write(JSON.stringify(value), () => process.exit(value.ok ? 0 : 1));
}

function isDoubao(host) {
  const name = String(host || "").replace(/^\./, "").toLowerCase();
  return name === HOST || name.endsWith("." + HOST);
}

function expired(expiresUtc) {
  const value = Number(expiresUtc) || 0;
  if (!value) return false; // 会话 Cookie 在进程存活期间仍有效
  return value / 1e6 - CHROMIUM_EPOCH <= Date.now() / 1000;
}

function decrypt(entry, password) {
  const raw = Buffer.from(String(entry.value || ""), "base64");
  if (!raw.length) return null;
  let plain;
  if (raw.subarray(0, 3).toString() === "v10") {
    const key = pbkdf2Sync(password, "saltysalt", 1003, 16, "sha1");
    const decipher = createDecipheriv("aes-128-cbc", key, Buffer.alloc(16, 0x20));
    try {
      plain = Buffer.concat([decipher.update(raw.subarray(3)), decipher.final()]);
    } catch {
      throw { reason: "decrypt_failed" };
    }
    // Chromium DB v24+ 在明文前加了 32 字节 sha256(host_key)。
    if (plain.length > 32) {
      const digest = createHash("sha256").update(String(entry.host || "")).digest();
      if (plain.subarray(0, 32).equals(digest)) plain = plain.subarray(32);
    }
  } else {
    plain = raw; // 未加密的行原样使用
  }
  try {
    return new TextDecoder("utf-8", { fatal: true }).decode(plain);
  } catch {
    return null;
  }
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
    if (typeof request?.password !== "string" || !request.password || !Array.isArray(request.cookies)) {
      throw { reason: "invalid_format" };
    }
    const pairs = [];
    const seen = new Set();
    for (const entry of request.cookies) {
      if (!entry || typeof entry.name !== "string" || !entry.name || seen.has(entry.name)) continue;
      if (!isDoubao(entry.host) || expired(entry.expires_utc)) continue;
      const value = decrypt(entry, request.password);
      if (value === null) continue;
      seen.add(entry.name);
      pairs.push(entry.name + "=" + value);
    }
    if (!pairs.length) throw { reason: "no_cookies" };
    reply({ ok: true, cookie: pairs.join("; ") });
  } catch (error) {
    reply({ ok: false, reason: error?.reason || "helper_protocol" });
  }
});
