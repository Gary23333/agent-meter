"""Account-connection acceptance for the B1/B3 gates (read-only).

The local backend's /v1/sources already carries each account source's status,
reason and metric availability; this module turns that into a short, stable
report for the five account sources that need a human login (qoder, workbuddy,
mimo, stepfun, volcengine). It never triggers a collection and never reads
credentials: run it after logging in to confirm the gate is actually closed.
"""
import json
import sys
from pathlib import Path
from urllib.request import Request, urlopen

TARGETS = ("qoder", "workbuddy", "mimo", "stepfun", "volcengine")
CONNECTED_STATUSES = {"available", "partial", "stale"}
NOT_CONNECTED_REASONS = {"not_authenticated", "web_session_missing", "mimo_not_authenticated",
                         "stepfun_credential_not_connected", "stepfun_not_authenticated",
                         "volcengine_credential_not_connected", "volcengine_not_authenticated",
                         "zcode_credential_not_connected", "disabled_by_user", "disabled_in_config"}


def account_connection_report(sources, targets=TARGETS):
    by_id = {}
    for src in sources:
        sid = src.get("id", "")
        if "#" in sid:
            continue
        by_id[sid] = src
    rows = []
    for target in targets:
        src = by_id.get(target)
        if src is None:
            rows.append({"source": target, "status": "missing", "reason": "source_not_present",
                         "connected": False, "has_quota": False})
            continue
        reason = (src.get("diagnostics") or {}).get("reason")
        status = src.get("status")
        connected = status in CONNECTED_STATUSES and reason not in NOT_CONNECTED_REASONS
        quota = (src.get("metrics") or {}).get("quota") or {}
        rows.append({"source": target, "status": status, "reason": reason,
                     "connected": connected,
                     "has_quota": quota.get("status") in {"available", "partial"}})
    return {"targets": rows,
            "connected": [r["source"] for r in rows if r["connected"]],
            "missing": [r["source"] for r in rows if not r["connected"]]}


def fetch_sources(runtime_dir, port=8769):
    runtime = Path(runtime_dir).expanduser()
    token = (runtime / "api.token").read_text().strip()
    request = Request("http://127.0.0.1:%d/v1/sources" % port,
                      headers={"Authorization": "Bearer " + token})
    with urlopen(request, timeout=120) as response:
        return json.load(response).get("sources", [])


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description="Read-only account connection check (B1/B3 gates)")
    parser.add_argument("--runtime", default=str(Path.cwd() / ".runtime"))
    parser.add_argument("--port", type=int, default=8769)
    args = parser.parse_args(argv)
    try:
        report = account_connection_report(fetch_sources(args.runtime, args.port))
    except OSError as error:
        print(json.dumps({"error": "backend_unreachable", "detail": str(error)}, ensure_ascii=False))
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 2 if report["missing"] else 0