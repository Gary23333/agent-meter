import json
import os
import subprocess
import tempfile
import signal
import plistlib
from .installed_sdk import materialize_qoder_sdk
from pathlib import Path

from .model import SourceError, account_key, metric, number, source


def normalize_qoder(payload, now):
    if not isinstance(payload, dict):
        raise SourceError("qoder_usage_unavailable")
    out = source("qoder", "account", now)
    out["account_key"] = account_key("qoder_cn", payload.get("userId"))
    rows, wallets = [], []
    for key in ("userQuota", "addOnQuota", "orgResourcePackage"):
        raw = payload.get(key)
        if raw is None:
            continue
        if not isinstance(raw, dict):
            raise SourceError("invalid_qoder_quota")
        used = number(raw.get("percentage"), optional=True)
        total = number(raw.get("cap" if key == "orgResourcePackage" else "total"), optional=True)
        remaining = number(raw.get("remaining"), optional=True)
        # Don't invent a missing percentage from a different quota bucket.
        rows.append({"bucket": key, "used_percent": used,
                     "remaining_percent": max(0,100-used) if used is not None else None})
        unit = raw.get("unit")
        if unit is not None and (not isinstance(unit,str) or len(unit)>40):
            raise SourceError("invalid_qoder_unit")
        wallets.append({"bucket": key, "total": total, "used": number(raw.get("used"), optional=True),
                        "remaining": remaining, "unit": unit})
    out["metrics"]["quota"] = metric(rows or None)
    out["metrics"]["credits"] = metric(wallets or None)
    out["diagnostics"]["no_agent_turn"] = True
    return out


def collect_qoder(app, node, runtime_dir, now, timeout=20):
    app = Path(app)
    package = "node_modules/@qoder-ai/qoder-cn-agent-sdk"
    worker = app/"Contents/Resources/app.asar.unpacked"/package/"dist/_worker/qoder-worker-runtime.obf.mjs"
    archive = app/"Contents/Resources/app.asar"
    if not worker.is_file() or not archive.is_file():
        raise SourceError("qoder_sdk_not_installed")
    info=plistlib.loads((app/"Contents/Info.plist").read_bytes())
    executable=app/"Contents/MacOS"/info["CFBundleExecutable"]
    root = Path(runtime_dir)
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="qoder-read-",dir=root) as temp:
        # Node's ESM loader doesn't resolve packaged ASAR dependencies. Cache
        # installed code privately; it is excluded from the distributable.
        sdk=materialize_qoder_sdk(archive,root)
        env = dict(os.environ, AGENT_METER_QODER_SDK=str(sdk), AGENT_METER_QODER_WORKER=str(worker))
        if not node:env["ELECTRON_RUN_AS_NODE"]="1"
        try:
            process = subprocess.Popen([node or str(executable),str(Path(__file__).parent/"helpers/qoder_usage.mjs")],
                    env=env,cwd=temp,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,start_new_session=True)
        except OSError:
            raise SourceError("cli_not_available") from None
        try:
            output, _ = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            raise SourceError("qoder_helper_timeout") from None
        finally:
            try:os.killpg(process.pid,signal.SIGTERM)
            except ProcessLookupError:pass
            try:process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid,signal.SIGKILL)
                process.wait(timeout=2)
        if len(output)>1024*1024:
            raise SourceError("response_too_large")
        for line in reversed(output.splitlines()):
            try:
                data = json.loads(line)
                if data.get("kind")=="qoder_usage":
                    return normalize_qoder(data.get("usage"),now)
                if data.get("kind")=="qoder_error":
                    if data.get("category") in {"authentication","credential","token","login","log in"}:
                        raise SourceError("qoder_not_authenticated")
                    if data.get("stage")=="initialize":
                        raise SourceError("qoder_sdk_initialization_failed")
                    known={"QoderWorkerRuntimeError":"qoder_worker_unavailable", "QoderCliProcessError":"qoder_cli_unavailable",
                           "ControlRequestError":"qoder_control_failed", "AuthAccessTokenEnvVarError":"qoder_not_authenticated"}
                    raise SourceError(known.get(data.get("error_type"),"qoder_helper_failed"))
            except (ValueError, AttributeError):
                continue
        raise SourceError("qoder_helper_failed")
