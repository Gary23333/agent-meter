// Use the user's installed SDK. Never submit an Agent prompt.
import { pathToFileURL } from "node:url";

let release;
let q;
let stage = "import_sdk";
try {
  const sdk = await import(pathToFileURL(process.env.AGENT_METER_QODER_SDK).href);
  stage = "construct_query";
  async function* noPrompt() {
    await new Promise(resolve => { release = resolve; });
  }
  q = sdk.query({
    prompt: noPrompt(),
    options: {
      auth: sdk.qodercliAuth(),
      transport: new sdk.WorkerTransport({ pathToQoderWorkerRuntime: process.env.AGENT_METER_QODER_WORKER }),
      persistSession: false,
      strictMcpConfig: true,
      mcpServers: {},
      cwd: process.cwd(),
      debug: false,
      stderr: () => {},
    },
  });
  stage = "initialize";
  await q.initializationResult();
  stage = "read_usage";
  const usage = await q.getUsageInfo();
  // Only account quota fields; an empty helper session is not usage history.
  const safe = usage == null ? null : Object.fromEntries(
    ["userId", "userType", "userQuota", "addOnQuota", "orgResourcePackage", "totalUsagePercentage", "isQuotaExceeded"]
      .filter(key => key in usage).map(key => [key, usage[key]])
  );
  console.log(JSON.stringify({ kind: "qoder_usage", usage: safe }));
} catch (error) {
  const code = typeof error?.code === "string" && /^[A-Z_]{1,80}$/.test(error.code) ? error.code : null;
  const missing = code === "ERR_MODULE_NOT_FOUND" ? /Cannot find package '([@a-zA-Z0-9_./-]+)'/.exec(error.message)?.[1] : null;
  const category = ["authentication", "credential", "token", "login", "log in", "permission", "transport", "version", "model"]
    .find(word => String(error?.message).toLowerCase().includes(word)) ?? "unknown";
  console.log(JSON.stringify({ kind: "qoder_error", error_type: error?.constructor?.name, code, missing_package: missing, category, stage }));
  process.exitCode = 1;
} finally {
  release?.();
  await q?.close();
}
