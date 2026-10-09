import copy
import json
import os
import shutil
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from zoneinfo import ZoneInfo

from .ccswitch import collect_ccswitch
from .agy_tokens import collect_antigravity_sessions
from .claude_code import collect_claude, collect_claude_web
from .cli_sessions import claude_tokens_metric, codex_tokens_metric, collect_gemini_sessions, mcode_tokens_metric
from .codex import collect_codex
from .discovery import discover
from .kimi import collect_kimi
from .kimi_tokens import collect_kimi_tokens
from .model import SCHEMA_VERSION, METRICS, SourceError, failed_source, metric, source, timestamp
from .opencode_tokens import collect_opencode_tokens
from .qoder import collect_qoder
from .web_sources import as_account_lists, collect_qoder_web, collect_trae, collect_workbuddy
from .minimax import collect_minimax
from .deepseek import collect_deepseek
from .mimo import collect_mimo
from .volcengine import collect_volcengine
from .zcode import collect_zcode
from .dreamina import collect_dreamina
from .minimax_design import collect_design
from .billing import refresh_countdowns
from .dreamina_web import merge_dreamina
from .workbuddy_tokens import collect_workbuddy_tokens
from .zcode_local import zcode_tokens_metric


def default_config():
    home=Path.home()
    return {"home":str(home),"app_roots":["/Applications",str(home/"Applications")],
            "ccswitch_db":str(home/".cc-switch/cc-switch.db"),"ccswitch_timezone":"Asia/Shanghai",
            "zcode_usage_db":str(home/".zcode/cli/db/db.sqlite"),
            "opencode_db":str(home/".local/share/opencode/opencode.db"),
            "workbuddy_projects_dir":str(home/".workbuddy/projects"),
            # Direct CLI session logs (used for days CC Switch has not imported).
            "codex_sessions_dir":str(home/".codex/sessions"),"codex_archives_dir":str(home/".codex/archived_sessions"),
            "claude_projects_dir":str(home/".claude/projects"),"gemini_dir":str(home/".gemini"),
            "mcode_db":str(home/".minimax/v2/sqlite/runtime-state.sqlite"),
            "agy_conversations_dir":str(home/".gemini/antigravity-cli/conversations"),
            "codex_binary":shutil.which("codex"),"kimi_binary":shutil.which("kimi"),
            "qoder_app":"/Applications/Qoder CN.app","node_binary":shutil.which("node"),
            "dreamina_binary":shutil.which("dreamina") or (str(home/".local/bin/dreamina") if (home/".local/bin/dreamina").is_file() else None),
            "design_gateway_url":"http://127.0.0.1:8001",
            "design_mcp_entry":"/Applications/MiniMax Design.app/Contents/Resources/mcp-tools/dist/main.js",
            "design_probe_mcp":True,"billing_overrides":{},
            "runtime_dir":str(Path.cwd()/".runtime"),"start_kimi_server":False,
            "codexbar_binary":shutil.which("codexbar"),"enable_codexbar":False,
            # 即梦 is read from its web page by the app; the CLI route is opt-in.
            "enable_dreamina_cli":False,
            "disabled_sources":[],"timeout_seconds":20,"cache_ttl_seconds":120}


def _raise(error):
    raise error


def safe_collect(source_id,scope,now,fn):
    try:
        return fn()
    except SourceError as e:
        disconnected={"cli_not_available","database_not_found","kimi_server_not_running","kimi_server_token_missing",
                      "not_authenticated","qoder_not_authenticated","qoder_sdk_not_installed","qoder_usage_unavailable","codexbar_not_installed",
                      "minimax_credential_not_connected","deepseek_credential_not_connected",
                      "zcode_credential_not_connected","volcengine_credential_not_connected","mimo_not_authenticated",
                      "volcengine_not_authenticated","volcengine_ark_key_not_supported",
                      "dreamina_cli_not_available","dreamina_not_authenticated","design_gateway_not_ready",
                      "design_billing_scope_unavailable","design_personal_scope_required",
                      "zcode_db_not_found","opencode_db_not_found","workbuddy_projects_not_found",
                      "codex_sessions_not_found","claude_projects_not_found","gemini_chats_not_found","mcode_db_not_found",
                      "agy_conversations_not_found",
                      "claude_not_logged_in","claude_subscription_login_missing","claude_token_expired","claude_keychain_denied","claude_keychain_timeout",
                      "claude_keychain_unavailable","web_session_missing","disabled_by_user"}
        return failed_source(source_id,scope,now,e.code,"not_connected" if e.code in disconnected else "error")
    except Exception:
        # No raw exception text: it can contain paths, request URLs or secrets.
        return failed_source(source_id,scope,now,"unexpected_source_error")


HISTORY_APP={"codex":"codex","claude":"claude","gemini":"gemini","opencode":"opencode","mcode":"minimax_code",
             "grokbuild":"grokbuild","pi":"pi"}


def coverage_matrix(apps,sources):
    by_id={s["id"]:s for s in sources}
    cc=by_id.get("ccswitch",{})
    value=cc.get("metrics",{}).get("tokens",{}).get("value")
    history=set()
    if value:
        for period in value["periods"].values():
            history.update(HISTORY_APP.get(g["app"],g["app"]) for g in period["groups"])
    # Preserve historical sources even if that CLI isn't installed now.
    apps=copy.deepcopy(apps)
    for provider in sorted(history-{a["provider"] for a in apps}):
        apps.append({"name":provider+" CLI history","provider":provider,"installed":False,"path":None,
                     "version":None,"bundle_id":None,"discovery_kind":"ccswitch_history"})
    matrix=[]
    for app in apps:
        provider=app["provider"]
        fields={name:{"status":"not_supported","source":None,"reason":"adapter_not_implemented"} for name in METRICS}
        candidate=by_id.get(provider) or by_id.get("codexbar:"+provider)
        if candidate:
            for name in METRICS:
                m=candidate["metrics"][name]
                fields[name]={"status":m["status"],"source":candidate["id"],"reason":m["reason"],"scope":candidate["scope"]}
        if provider in history:
            # A dedicated local-history source for this provider is the
            # primary token ledger; CC Switch stays the fallback and the
            # cost source for the days it imported.
            local=by_id.get(provider)
            primary=(local if local is not None and local.get("scope")=="local_session_history"
                     and local["metrics"]["tokens"]["status"] in {"available","partial","stale"} else None)
            for name in ("tokens","cost"):
                if name=="tokens" and primary is not None:
                    m=primary["metrics"][name]
                    fields[name]={"status":m["status"],"source":primary["id"],"reason":m["reason"],"scope":"local_session_history"}
                    continue
                m=cc["metrics"][name]
                fields[name]={"status":m["status"],"source":"ccswitch","reason":None,"scope":"local_imported_history"}
        if provider=="ccswitch":
            for name in ("tokens","cost"):
                m=cc.get("metrics",{}).get(name,metric(status="not_connected"))
                fields[name]={"status":m["status"],"source":"ccswitch","reason":m["reason"],"scope":"local_imported_history"}
        matrix.append({"application":app,"fields":fields})
    return matrix


def coverage_summary(coverage):
    return {"applications":len(coverage),
            "installed_applications":sum(r["application"]["installed"] for r in coverage),
            "available_fields":sum(f["status"]=="available" for r in coverage for f in r["fields"].values()),
            "partial_fields":sum(f["status"]=="partial" for r in coverage for f in r["fields"].values()),
            "missing_fields":sum(f["status"] not in {"available","partial"} for r in coverage for f in r["fields"].values())}


def collect(config=None,now=None):
    config=dict(default_config(),**(config or {}))
    now=time.time() if now is None else now
    runtime=Path(config["runtime_dir"])
    runtime.mkdir(mode=0o700,parents=True,exist_ok=True)
    timeout=config["timeout_seconds"]
    # In-memory only (set through the local API); never part of the snapshot.
    # The first account per provider keeps the plain source id; others are "id#2"...
    accounts=as_account_lists(config.get("web_sessions"))
    web={p:lst[0] for p,lst in accounts.items()}
    # Switches from the app (e.g. Claude off), also in memory only.
    user_off=set((config.get("preferences") or {}).get("disabled_sources") or [])
    jobs={
      "ccswitch":("local_imported_history",lambda:collect_ccswitch(config["ccswitch_db"],now,ZoneInfo(config["ccswitch_timezone"]))),
      "codex":("account",lambda:collect_codex(config["codex_binary"],now,timeout,str(runtime))),
      # claude.ai web login (shared with the desktop app) first, else Claude Code's Keychain login.
      "claude":("account",lambda:collect_claude_web(web["claude"],now,timeout) if "claude" in web
                else collect_claude(config["home"],now,timeout)),
      "kimi":("account",lambda:collect_kimi(config["home"],config["kimi_binary"],now,timeout,
          url=config.get("kimi_url"),start_server=config["start_kimi_server"],cwd=str(runtime))),
      # A website login (if connected) replaces the Qoder SDK route.
      "qoder":("account",lambda:collect_qoder_web(web["qoder"],now,timeout) if "qoder" in web
               else collect_qoder(config["qoder_app"],config["node_binary"],runtime,now,timeout)),
      "workbuddy":("account",lambda:collect_workbuddy(web.get("workbuddy"),now,timeout)),
      "trae_cn":("account",lambda:collect_trae(web.get("trae_cn"),now,timeout)),
      "minimax_code":("account",lambda:collect_minimax(config["ccswitch_db"],now,timeout,(web.get("minimax_code") or {}).get("api_key"))),
      "dreamina":("creative_account",lambda:collect_dreamina(config["dreamina_binary"],now,timeout,config["billing_overrides"].get("dreamina"))
                  if config.get("enable_dreamina_cli") else _raise(SourceError("web_session_missing"))),
      "minimax_design":("creative_personal_account",lambda:collect_design(config["design_gateway_url"],now,timeout,
          config["billing_overrides"].get("minimax_design"),config["node_binary"],config["design_mcp_entry"],config["design_probe_mcp"])),
      "deepseek_api":("api_account",lambda:collect_deepseek(now,timeout,(web.get("deepseek_api") or {}).get("api_key"),
          (web.get("deepseek_api") or {}).get("user_token"))),
      "zcode":("account",lambda:collect_zcode(web.get("zcode"),now,timeout)),
      "mimo":("api_account",lambda:collect_mimo(web.get("mimo"),now,timeout) if "mimo" in web
              else _raise(SourceError("web_session_missing"))),
      "volcengine":("account",lambda:collect_volcengine(web.get("volcengine"),now,timeout)),
      # Local token history that CC Switch does not import; ZCode's own local
      # usage db attaches to its account source below (kimi pattern).
      "opencode":("local_session_history",lambda:collect_opencode_tokens(config["opencode_db"],config["ccswitch_db"],now)),
      "gemini":("local_session_history",lambda:collect_gemini_sessions(config["gemini_dir"],config["ccswitch_db"],now)),
      "antigravity":("local_session_history",lambda:collect_antigravity_sessions(config["agy_conversations_dir"],config["ccswitch_db"],now)),
    }
    web_collectors={"claude":collect_claude_web,"qoder":collect_qoder_web,"workbuddy":collect_workbuddy,"trae_cn":collect_trae,
                    "mimo":collect_mimo,"zcode":collect_zcode,"volcengine":collect_volcengine}
    def labelled(key,label,fn):
        def run():
            out=fn()
            out["id"]=key
            if label:out["account_label"]=label
            return out
        return run
    for provider,lst in accounts.items():
        if provider not in jobs or provider not in web_collectors:continue
        scope,fn=jobs[provider]
        jobs[provider]=(scope,labelled(provider,lst[0].get("label"),fn))
        for n,session in enumerate(lst[1:],start=2):
            key=provider+"#"+str(n)
            jobs[key]=(scope,labelled(key,session.get("label"),
                       lambda s=session,c=web_collectors[provider]:c(s,now,timeout)))
    if config.get("enable_codexbar"):
        from .codexbar import collect_codexbar
        jobs["codexbar"]=("account",lambda:collect_codexbar(config["codexbar_binary"],now,timeout))
    def switched_off(key):
        # A switch binds the provider, so it also covers "#2" accounts.
        base=key.split("#",1)[0]
        return base in config["disabled_sources"] or base in user_off
    sources=[]
    with ThreadPoolExecutor(max_workers=min(16,max(4,len(jobs)))) as pool:
        futures={key:pool.submit(safe_collect,key,scope,now,fn) for key,(scope,fn) in jobs.items()
                 if not switched_off(key)}
        # Parse the local session logs alongside the network jobs. submit()
        # runs immediately, so the user switches must gate each one.
        token_futures={}
        for provider, fn in (
            ("kimi",lambda:collect_kimi_tokens(config["home"],now)),
            ("workbuddy",lambda:collect_workbuddy_tokens(config["workbuddy_projects_dir"],now)),
            ("codex",lambda:codex_tokens_metric(config["codex_sessions_dir"],config["codex_archives_dir"],
                                                config["ccswitch_db"],now)),
            ("claude",lambda:claude_tokens_metric(config["claude_projects_dir"],config["ccswitch_db"],now)),
            ("minimax_code",lambda:mcode_tokens_metric(config["mcode_db"],config["ccswitch_db"],now)),
            ("zcode",lambda:zcode_tokens_metric(config["zcode_usage_db"],now)),
        ):
            if not switched_off(provider):
                token_futures[provider]=pool.submit(fn)
        for key in jobs:
            if key not in futures:
                reason="disabled_by_user" if key.split("#",1)[0] in user_off else "disabled_in_config"
                sources.append(failed_source(key,jobs[key][0],now,reason,"not_connected"))
                continue
            result=futures[key].result()
            if isinstance(result,list):sources.extend(result)
            else:sources.append(result)
    # Local token history, attached even when the account servers are down.
    for src in sources:
        future=token_futures.get(src["id"])
        if future is None:
            continue
        try:src["metrics"]["tokens"]=future.result()
        except SourceError as e:src["metrics"]["tokens"]=metric(status="not_connected",reason=e.code)
        except Exception:src["metrics"]["tokens"]=metric(status="error",reason="local_token_parse_failed")
    # Web-page observations (即梦 membership / credit split) from the app.
    if not switched_off("dreamina"):
        sources=merge_dreamina(sources,config.get("observations"),now)
    # Optional API-equivalent cost estimates from the local price table.
    # CC Switch and CodexBar keep their own estimates; a provider-billed cost
    # (DeepSeek web usage) is never overwritten.
    from .prices import estimate_source_cost, load_prices
    table=load_prices(config["runtime_dir"])
    for src in sources:
        if src["id"] in {"ccswitch","deepseek_api"} or src["id"].startswith("codexbar:"):continue
        tokens=src["metrics"]["tokens"]
        if tokens["status"] not in {"available","partial"} or src["metrics"]["cost"]["value"] is not None:continue
        estimated=estimate_source_cost(tokens,table)
        if estimated is not None:src["metrics"]["cost"]=estimated
    apps=discover(config["app_roots"])
    if config.get("enable_dreamina_cli") and config.get("dreamina_binary"):
        apps.append({"name":"即梦 CLI","provider":"dreamina","installed":True,"path":config["dreamina_binary"],
                     "version":None,"bundle_id":None,"discovery_kind":"configured_cli"})
    coverage=coverage_matrix(apps,sources)
    return {"schema_version":SCHEMA_VERSION,"collected_at":timestamp(now),"display_timezone":"Asia/Shanghai",
            "sources":sources,"coverage":coverage,
            "coverage_summary":coverage_summary(coverage),
            "aggregation_policy":"No cross-account balance sums. CC Switch is primary local token history; account usage remains separate."}


def atomic_json(path,payload):
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    with tempfile.NamedTemporaryFile(mode="w",dir=path.parent,delete=False,encoding="utf-8") as handle:
        temp=Path(handle.name)
        json.dump(payload,handle,ensure_ascii=False,indent=2,allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temp,0o600)
    os.replace(temp,path)


class SnapshotService:
    def __init__(self,config=None,collect_fn=collect,clock=time.time):
        self.config=dict(default_config(),**(config or {}))
        self.collect_fn,self.clock=collect_fn,clock
        # self.lock only guards state fields; collection holds collect_lock so
        # config setters never wait behind a long network refresh.
        self.lock=threading.Lock()
        self.collect_lock=threading.Lock()
        self.snapshot=None
        self.last_refresh=0
        self.generation=0

    def _invalidate(self):
        self.last_refresh=0
        # Survives a collection that is still running: when it stores its
        # result it must not mark data collected under the old config fresh.
        self.generation+=1

    def set_web_sessions(self,sessions):
        """Replace website logins; the next read collects fresh data."""
        with self.lock:
            self.config["web_sessions"]={p:list(v) for p,v in sessions.items()}
            self._invalidate()

    def set_preferences(self,preferences):
        with self.lock:
            self.config["preferences"]=preferences
            self._invalidate()

    def set_observations(self,observations):
        with self.lock:
            self.config["observations"]=observations
            self._invalidate()

    def set_prices(self,currency,models):
        """Persist the price table; the next read re-estimates costs."""
        from .prices import save_prices
        save_prices(self.config["runtime_dir"],currency,models)
        with self.lock:
            self._invalidate()

    def _cached(self,now):
        if self.snapshot is None or now-self.last_refresh>=self.config["cache_ttl_seconds"]:
            return None
        out=copy.deepcopy(self.snapshot)
        out["served_from_cache"]=True
        return refresh_countdowns(out,now)

    def get(self,force=False):
        with self.lock:
            if not force:
                cached=self._cached(self.clock())
                if cached is not None:return cached
        with self.collect_lock:
            # Double-checked: another reader may have just collected.
            with self.lock:
                now=self.clock()
                if not force:
                    cached=self._cached(now)
                    if cached is not None:return cached
                config,generation=self.config,self.generation
            fresh=self.collect_fn(config,now=now)
            old={s["id"]:s for s in (self.snapshot or {}).get("sources",[])}
            replaced=False
            for index,src in enumerate(fresh["sources"]):
                previous=old.get(src["id"])
                if src["diagnostics"].get("reason") not in {"dreamina_not_authenticated","not_authenticated",
                        "design_account_changed_during_query","design_personal_scope_required","web_session_missing","disabled_by_user",
                        "mimo_not_authenticated","volcengine_not_authenticated","volcengine_ark_key_not_supported"} and src["status"] in {"error","not_connected"} and previous and previous["status"] in {"available","partial","stale"}:
                    cached=copy.deepcopy(previous)
                    cached["status"]="stale"
                    cached["diagnostics"]["last_attempt_at"]=timestamp(now)
                    cached["diagnostics"]["last_error"]=src["diagnostics"]["reason"]
                    for m in cached["metrics"].values():
                        if m["value"] is not None:m["status"]="stale"
                    # Local token history does not depend on the account network:
                    # keep the fresh measurement instead of the stale one.
                    if src["metrics"]["tokens"]["status"] in {"available","partial"}:
                        cached["metrics"]["tokens"]=src["metrics"]["tokens"]
                    fresh["sources"][index]=cached
                    replaced=True
            if replaced:
                # Rebuild coverage after stale recovery so the UI can't show a
                # fresh-looking field attached to an old source.
                fresh["coverage"]=coverage_matrix([r["application"] for r in fresh["coverage"] if r["application"]["installed"]],fresh["sources"])
                fresh["coverage_summary"]=coverage_summary(fresh["coverage"])
            refresh_countdowns(fresh,now)
            fresh["served_from_cache"]=False
            with self.lock:
                self.snapshot=fresh
                self.last_refresh=now if generation==self.generation else 0
            atomic_json(Path(self.config["runtime_dir"])/"snapshot.json",fresh)
            return copy.deepcopy(fresh)
