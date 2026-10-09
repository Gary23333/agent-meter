import argparse
import json
import sys
from pathlib import Path

from .collector import SnapshotService, atomic_json, default_config
from .server import load_or_create_token, make_server


def main():
    parser=argparse.ArgumentParser(description="Read-only local agent usage backend")
    parser.add_argument("command",choices=["collect","serve","verify"])
    parser.add_argument("--config",type=Path,help="JSON paths and options; never put credentials in this file")
    parser.add_argument("--output",type=Path)
    parser.add_argument("--reference",type=Path,help="Optional sanitized Codex native reference JSON for reconciliation")
    parser.add_argument("--port",type=int,default=8769)
    parser.add_argument("--start-kimi-server",action="store_true",help="Allow a temporary no-prompt Kimi helper")
    parser.add_argument("--disable",action="append",default=[],choices=["ccswitch","codex","claude","kimi","qoder","codexbar","minimax_code","deepseek_api","dreamina","minimax_design","workbuddy","trae_cn","zcode","opencode","gemini","antigravity"])
    parser.add_argument("--local-only",action="store_true",help="Collect local CC Switch history, skip account network helpers")
    args=parser.parse_args()
    config=default_config()
    if args.config:
        try:
            data=json.loads(args.config.read_text())
            if not isinstance(data,dict) or set(data)-set(config)-{"kimi_url"}:
                raise ValueError()
            config.update(data)
        except (ValueError,OSError):
            parser.error("Invalid backend config")
    if args.start_kimi_server:config["start_kimi_server"]=True
    config["disabled_sources"]=list(set(config["disabled_sources"]+args.disable+
        (["codex","claude","kimi","qoder","codexbar","minimax_code","deepseek_api","dreamina","minimax_design","workbuddy","trae_cn"] if args.local_only else [])))
    service=SnapshotService(config)
    if args.command=="serve":
        token=load_or_create_token(Path(config["runtime_dir"])/"api.token")
        server=make_server(service,token,args.port)
        print(json.dumps({"listening":"http://127.0.0.1:"+str(server.server_address[1]),
                          "token_file":str(Path(config["runtime_dir"])/"api.token")}),flush=True)
        try:server.serve_forever()
        except KeyboardInterrupt:pass
        finally:server.server_close()
        return
    snapshot=service.get(force=True)
    if args.command=="verify":
        from .verify import verify_snapshot
        reference=json.loads(args.reference.read_text()) if args.reference else None
        report=verify_snapshot(snapshot,config,reference)
        if args.output:atomic_json(args.output,report)
        else:print(json.dumps(report,ensure_ascii=False,indent=2))
        if report["failed_checks"]:sys.exit(1)
    elif args.output:
        atomic_json(args.output,snapshot)
        print(json.dumps({"written":str(args.output),"coverage":snapshot["coverage_summary"],
                          "sources":[{"id":s["id"],"status":s["status"],"reason":s["diagnostics"].get("reason")} for s in snapshot["sources"]]},ensure_ascii=False))
    else:print(json.dumps(snapshot,ensure_ascii=False,indent=2))
