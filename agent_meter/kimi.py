import json
import os
import socket
import subprocess
import time
from pathlib import Path

from .model import SourceError, decimal_string, integer, metric, number, source, timestamp
from .transport import get_json


def normalize_kimi(envelope, now):
    if envelope.get("code") != 0:
        raise SourceError("kimi_envelope_error")
    data = envelope.get("data")
    if not isinstance(data, dict) or data.get("kind") != "ok":
        raise SourceError("kimi_upstream_unavailable")
    out = source("kimi", "account", now)
    rows, resets = [], []
    quota = data.get("quota")
    if isinstance(quota,dict) and isinstance(quota.get("usages"),dict):
        for name in ("limit5h", "limit7d", "monthTotal", "monthCode"):
            raw = quota["usages"].get(name)
            if raw is None:
                continue
            used = number(raw.get("usedRatio")) * 100
            reset = timestamp(raw.get("resetAt"))
            rows.append({"bucket": name, "used_percent": used, "remaining_percent": max(0, 100-used), "resets_at": reset})
            if reset is not None:
                resets.append({"bucket": name, "resets_at": reset})
        wallet=quota.get("extraUsage")
        out["diagnostics"]["contract"]="quota_usages"
    elif isinstance(data.get("summary"),dict) and isinstance(data.get("limits"),list):
        # Installation-specific contract verified from the live local server.
        # Preserve counts and their window; don't guess which tier is weekly.
        for name,raw in [("summary",data["summary"])]+[("limit_"+str(i),r) for i,r in enumerate(data["limits"])]:
            window=raw.get("window")
            if not isinstance(window,dict) or window.get("unit") not in {"second","minute","hour","day","week","month"}:
                raise SourceError("invalid_kimi_window")
            duration=number(window.get("duration"))
            used_count=number(raw.get("used"));limit=number(raw.get("limit"))
            used=used_count/limit*100 if limit else None
            reset=timestamp(raw.get("reset_at"))
            rows.append({"bucket":name,"used_percent":used,"remaining_percent":max(0,100-used) if used is not None else None,
                         "used":used_count,"limit":limit,"unit":"provider_quota_units",
                         "window":{"duration":duration,"unit":window["unit"]},"resets_at":reset})
            if reset is not None:resets.append({"bucket":name,"resets_at":reset})
        wallet=data.get("extra_usage")
        out["diagnostics"]["contract"]="summary_limits"
    else:
        raise SourceError("invalid_kimi_quota")
    out["metrics"]["quota"] = metric(rows or None)
    out["metrics"]["reset_time"] = metric(resets or None)
    if wallet is not None:
        from decimal import Decimal
        if not isinstance(wallet, dict) or wallet.get("currency") not in {"CNY", "USD"}:
            raise SourceError("invalid_kimi_wallet")
        balance = wallet.get("balanceCents")
        if balance is not None and (isinstance(balance,bool) or not isinstance(balance,int)):
            raise SourceError("invalid_kimi_balance")
        out["metrics"]["credits"] = metric({
            "amount": str(Decimal(balance) / 100) if balance is not None else None,
            "unit": wallet["currency"], "kind": "booster_wallet",
            "monthly_used_amount": str(Decimal(integer(wallet["monthlyUsedCents"])) / 100) if wallet.get("monthlyUsedCents") is not None else None,
            "monthly_limit_amount": str(Decimal(integer(wallet["monthlyChargeLimitCents"])) / 100) if wallet.get("monthlyChargeLimitCents") is not None else None,
        })
    return out


def instance_urls(home):
    urls = []
    for path in sorted((Path(home)/".kimi-code/server/instances").glob("*.json")):
        try:
            row = json.loads(path.read_text())
            if row.get("host") not in {"127.0.0.1", "localhost"}:
                continue
            os.kill(integer(row["pid"]), 0)
            port = integer(row["port"])
            if 0 < port < 65536:
                urls.append("http://127.0.0.1:"+str(port))
        except (OSError, ValueError, KeyError, SourceError):
            continue
    return urls


def collect_kimi(home, binary, now, timeout=15, url=None, start_server=False, cwd=None):
    token_path = Path(home)/".kimi-code/server.token"
    if not token_path.is_file():
        raise SourceError("kimi_server_token_missing")
    try:
        token = token_path.read_text().strip()
    except OSError:
        raise SourceError("kimi_server_token_invalid") from None
    if not token or "\n" in token:
        raise SourceError("kimi_server_token_invalid")
    urls = [url] if url else instance_urls(home)
    last_error = SourceError("kimi_server_not_running")
    for endpoint in urls:
        try:
            out = normalize_kimi(get_json(endpoint.rstrip('/')+"/api/v1/oauth/usage", token, timeout, local=True), now)
            out["diagnostics"]["connection"] = "existing_local_server"
            return out
        except SourceError as e:
            last_error = e
    if not start_server or not binary:
        raise last_error
    # This optional helper runs no prompts and never opens a browser. Its logs
    # can contain a bearer credential, so both streams must remain private.
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    # A CLI uninstalled since config time must still map to a fixed code.
    try:
        process = subprocess.Popen([binary, "web", "--port", str(port), "--no-open"], cwd=cwd,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError:
        raise SourceError("cli_not_available") from None
    try:
        deadline = time.monotonic()+timeout
        endpoint = "http://127.0.0.1:"+str(port)
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise SourceError("kimi_helper_exited")
            try:
                get_json(endpoint+"/api/v1/healthz", timeout=1, local=True)
                out = normalize_kimi(get_json(endpoint+"/api/v1/oauth/usage", token, timeout, local=True), now)
                out["diagnostics"]["connection"] = "temporary_local_helper_no_prompts"
                return out
            except SourceError as e:
                if e.code not in {"connection_failed"}:
                    raise
                time.sleep(.1)
        raise SourceError("kimi_helper_timeout")
    finally:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)
