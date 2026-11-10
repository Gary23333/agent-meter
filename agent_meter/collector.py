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

from .applications import application_usage, coverage_matrix
from .agy_tokens import collect_antigravity_sessions
from .agy_quota import collect_antigravity_quota
from .claude_code import collect_claude, collect_claude_web
from .cli_sessions import claude_tokens_metric, codex_tokens_metric, collect_gemini_sessions, mcode_tokens_metric
from .codex import collect_codex
from .codex_images import codex_image_metric
from .design_tokens import collect_design_tokens
from .discovery import discover
from .kimi import collect_kimi
from .kimi_tokens import collect_kimi_tokens
from .kimi_desktop_tokens import collect_kimi_desktop_tokens
from .kimi_legacy_tokens import collect_kimi_legacy_tokens
from .model import SCHEMA_VERSION, SourceError, failed_source, metric, source, timestamp
from .opencode_tokens import collect_opencode_tokens
from .mimocode_tokens import collect_mimocode_tokens, collect_deveco_tokens
from .qoder import collect_qoder
from .qoder_tokens import collect_qoder_credits, merge_credits_metric
from .web_sources import as_account_lists, collect_qoder_web, collect_trae, collect_workbuddy
from .minimax import collect_minimax
from .deepseek import collect_deepseek
from .dsh_tokens import collect_dsh_sessions
from .imported_history import collect_imported_history
from .mimo import collect_mimo
from .stepfun import collect_stepfun
from .volcengine import collect_volcengine
from .zcode import collect_zcode
from .zcode_desktop import collect_zcode_desktop
from .dreamina import collect_dreamina, collect_dreamina_canvas
from .minimax_design import collect_design
from .billing import refresh_countdowns
from .pet import PetMind
from .reset_forecast import CACHE_NAME, collect_reset_forecast, refresh_forecast_countdowns
from .dreamina_web import merge_dreamina
from .workbuddy_tokens import collect_workbuddy_tokens
from .zcode_local import zcode_tokens_metric


def default_config():
    home=Path.home()
    return {"home":str(home),"app_roots":["/Applications",str(home/"Applications")],
            "opencode_db":str(home/".local/share/opencode/opencode.db"),
            # MiMo Code / DevECo keep independent opencode-isomorphic ledgers.
            "mimocode_db":str(home/".local/share/mimocode/mimocode.db"),
            "deveco_db":str(home/".local/share/deveco/deveco-stable.db"),
            "zcode_usage_db":str(home/".zcode/cli/db/db.sqlite"),
            # ZCode desktop's own login store; reset cards need its JWT.
            "zcode_v2_dir":str(home/".zcode/v2"),
            "workbuddy_projects_dir":str(home/".workbuddy/projects"),
            # Direct CLI session logs; every reader owns its own ledger.
            "codex_sessions_dir":str(home/".codex/sessions"),"codex_archives_dir":str(home/".codex/archived_sessions"),
            # Codex 内置 image_gen：PNG 按张统计 + 历史库里的调用数（版本号会变，模块内 glob 兜底）。
            "codex_images_dir":str(home/".codex/generated_images"),
            "codex_history_db":str(home/".codex/thread_history_1.sqlite"),
            "codex_state_db":str(home/".codex/state_5.sqlite"),
            "codex_image_quality":"high",
            "claude_projects_dir":str(home/".claude/projects"),"gemini_dir":str(home/".gemini"),
            # Claude Desktop's local-agent sessions use the same JSONL schema
            # as Claude Code, under a per-session .claude/projects tree.
            "claude_desktop_sessions_dir":str(home/"Library/Application Support/Claude/local-agent-mode-sessions"),
            "mcode_db":str(home/".minimax/v2/sqlite/runtime-state.sqlite"),
            "agy_conversations_dir":str(home/".gemini/antigravity-cli/conversations"),
            # The desktop app writes the same conversation schema to its own
            # root; the source treats the two as one Antigravity ledger.
            "agy_desktop_conversations_dir":str(home/".gemini/antigravity/conversations"),
            # DeepSeek Harness (dsh) session ledgers are zstd-compressed; the
            # CLI path is only needed when the stdlib route is unavailable.
            "dsh_sessions_dir":str(home/".dsh/sessions"),"zstd_binary":shutil.which("zstd"),
            # The design agent's embedded opencode runtime keeps its own
            # data-home; its ledger overlaps the standalone db only through
            # copied sessions, which the collector excludes by session id.
            "design_opencode_db":str(home/"Library/Application Support/@hilo/desktop/ai-runtime/data-home/opencode/opencode.db"),
            "codex_binary":shutil.which("codex"),"kimi_binary":shutil.which("kimi"),
            # Kimi.app's Agent runtime keeps its own ledger with the same schema.
            "kimi_desktop_sessions_dir":str(home/"Library/Application Support/kimi-desktop/daimon-share/daimon/runtime/kimi-code/home/sessions"),
            # Pre-migration Kimi CLI ledger; writes stopped 2026-06-17.
            "kimi_legacy_sessions_dir":str(home/".kimi/sessions"),
            "qoder_app":"/Applications/Qoder CN.app","node_binary":shutil.which("node"),
            "qoder_projects_dir":str(home/".qoder-cn/projects"),
            "dreamina_binary":shutil.which("dreamina") or (str(home/".local/bin/dreamina") if (home/".local/bin/dreamina").is_file() else None),
            # The canvas CLI replaced `dreamina`; its auth account route has no
            # credit query, so it is only the fallback identity/VIP transport.
            "dreamina_canvas_binary":shutil.which("dreamina-canvas") or (str(home/".local/bin/dreamina-canvas") if (home/".local/bin/dreamina-canvas").is_file() else None),
            "design_gateway_url":"http://127.0.0.1:8001",
            "design_mcp_entry":"http://127.0.0.1:18810/mcp",
            "design_probe_mcp":True,"billing_overrides":{},
            # Third-party reset trackers throttle themselves; keep their pages out of the
            # 120 s snapshot cycle.
            "enable_reset_forecast":True,"reset_forecast_refresh_minutes":45,
            "runtime_dir":str(Path.cwd()/".runtime"),"local_only":False,"start_kimi_server":False,
            # One-time legacy import; a missing file just means no history.
            "history_store":None,
            "codexbar_binary":shutil.which("codexbar"),"enable_codexbar":False,
            # 即梦 is read from its web page by the app; the CLI route is opt-in.
            "enable_dreamina_cli":False,
            "disabled_sources":[],"timeout_seconds":20,"codex_timeout_seconds":45,"cache_ttl_seconds":120,
            # 会话活动页：只扫最近窗口，空闲阈值判定「进行中」证据。
            "activity_window_hours":24,"activity_idle_minutes":15}


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
                      "zcode_desktop_not_installed","zcode_desktop_credentials_unreadable","zcode_desktop_node_missing",
                      "stepfun_credential_not_connected","stepfun_not_authenticated",
                      "volcengine_not_authenticated","volcengine_ark_key_not_supported",
                      "dreamina_cli_not_available","dreamina_not_authenticated","design_gateway_not_ready",
                      "design_billing_scope_unavailable","design_personal_scope_required",
                      "zcode_db_not_found","opencode_db_not_found","workbuddy_projects_not_found",
                      "qoder_sessions_not_found",
                      "codex_sessions_not_found","claude_projects_not_found","gemini_chats_not_found","mcode_db_not_found",
                      "agy_conversations_not_found","design_opencode_db_not_found",
                      "dsh_sessions_not_found","zstd_unavailable",
                      "kimi_desktop_sessions_not_found","kimi_legacy_sessions_not_found",
                      "mimocode_db_not_found","deveco_db_not_found",
                      "claude_not_logged_in","claude_subscription_login_missing","claude_token_expired","claude_keychain_denied","claude_keychain_timeout",
                      "claude_keychain_unavailable","web_session_missing","disabled_by_user","disabled_in_config","local_only_mode","skipped_low_resource",
                      "history_store_not_found"}
        return failed_source(source_id,scope,now,e.code,"not_connected" if e.code in disconnected else "error")
    except Exception:
        # No raw exception text: it can contain paths, request URLs or secrets.
        return failed_source(source_id,scope,now,"unexpected_source_error")


def coverage_summary(coverage):
    return {"applications":len(coverage),
            "installed_applications":sum(r["application"]["installed"] for r in coverage),
            "application_groups":len({r["application"].get("application_id",r["application"]["provider"]) for r in coverage}),
            "available_fields":sum(f["status"]=="available" for r in coverage for f in r["fields"].values()),
            "partial_fields":sum(f["status"]=="partial" for r in coverage for f in r["fields"].values()),
            "missing_fields":sum(f["status"] not in {"available","partial"} for r in coverage for f in r["fields"].values())}


def collect_antigravity(config,now):
    """One Antigravity source: local token ledgers plus the running app's quota.

    The token roots and the desktop language server fail independently. A
    missing quota server must not hide token history, and a machine without
    conversation databases can still show the signed-in account's windows.
    """
    try:
        out=collect_antigravity_sessions(config["agy_conversations_dir"],now,
                                         desktop_root=config.get("agy_desktop_conversations_dir"))
    except SourceError as e:
        out=source("antigravity","account",now,status="partial",reason=e.code)
        out["metrics"]["tokens"]=metric(status="not_connected",reason=e.code)
    try:
        out["metrics"]["quota"]=metric(collect_antigravity_quota(now))
    except SourceError as e:
        out["metrics"]["quota"]=metric(
            status="not_connected" if e.code=="antigravity_language_server_not_running" else "error",
            reason=e.code)
        out["diagnostics"]["quota_error"]=e.code
        if out["status"]=="available":
            out["status"]="partial"
            out["diagnostics"]["reason"]=e.code
    if (out["metrics"]["tokens"]["status"] not in {"available","partial","stale"}
            and out["metrics"]["quota"]["status"] not in {"available","stale"}):
        out["status"]="not_connected"
    return out


def collect_qoder_route(config,web_session,runtime,now,timeout):
    """Web console login first; an expired website session must not hide a
    working local Qoder SDK login, so the SDK route is the fallback."""
    web_error=None
    if web_session:
        try:
            return collect_qoder_web(web_session,now,timeout)
        except SourceError as e:
            web_error=e
    try:
        return collect_qoder(config["qoder_app"],config["node_binary"],runtime,now,timeout)
    except SourceError as e:
        raise (web_error or e)


def collect_zcode_route(config,web_session,now,timeout):
    """Web console login keeps priority for quota; the desktop login adds the
    reset cards it alone can read, and stands in when no web session exists.
    Either route failing never discards the other's data."""
    desktop=None
    try:
        desktop=collect_zcode_desktop(config["zcode_v2_dir"],config.get("node_binary"),now,timeout)
    except SourceError:
        pass
    web_error=None
    if web_session:
        try:
            out=collect_zcode(web_session,now,timeout)
            if desktop and desktop["metrics"]["reset_cards"]["status"]=="available":
                out["metrics"]["reset_cards"]=desktop["metrics"]["reset_cards"]
                out["diagnostics"]["cards_transport"]="zcode_desktop_login"
            return out
        except SourceError as e:
            web_error=e
    if desktop:
        return desktop
    raise web_error or SourceError("zcode_credential_not_connected")


def collect_dreamina_route(config,now,timeout):
    if not config.get("enable_dreamina_cli"):
        raise SourceError("web_session_missing")
    override=config["billing_overrides"].get("dreamina")
    if config.get("dreamina_binary"):
        return collect_dreamina(config["dreamina_binary"],now,timeout,override)
    if config.get("dreamina_canvas_binary"):
        return collect_dreamina_canvas(config["dreamina_canvas_binary"],now,timeout,override)
    raise SourceError("dreamina_cli_not_available")


def collect(config=None,now=None):
    config=dict(default_config(),**(config or {}))
    now=time.time() if now is None else now
    runtime=Path(config["runtime_dir"])
    runtime.mkdir(mode=0o700,parents=True,exist_ok=True)
    timeout=config["timeout_seconds"]
    history_store=config.get("history_store") or str(runtime/"imported-history.json")
    config["history_store"]=history_store
    # In-memory only (set through the local API); never part of the snapshot.
    # The first account per provider keeps the plain source id; others are "id#2"...
    accounts=as_account_lists(config.get("web_sessions"))
    web={p:lst[0] for p,lst in accounts.items()}
    # Switches from the app (e.g. Claude off), also in memory only.
    preferences=config.get("preferences") or {}
    user_off=set(preferences.get("disabled_sources") or [])
    # Low-resource mode: longer cache TTL and an opt-in list of heavy ledgers
    # to skip; skipped sources stay visible with their own reason.
    low_resource=bool(preferences.get("low_resource_mode"))
    skip_ledgers=set(preferences.get("skip_ledgers_low_resource") or []) if low_resource else set()
    # Optional API-equivalent price table for every local token ledger.
    from .prices import estimate_daily_cost, estimate_source_cost, load_prices
    table=load_prices(config["runtime_dir"])
    jobs={
      # Project-owned history written once by the legacy migration.
      "imported_history":("local_imported_history",lambda:collect_imported_history(history_store,now)),
      "codex":("account",lambda:collect_codex(config["codex_binary"],now,max(timeout,config.get("codex_timeout_seconds",45)),str(runtime))),
      # claude.ai web login (shared with the desktop app) first, else Claude Code's Keychain login.
      "claude":("account",lambda:collect_claude_web(web["claude"],now,timeout) if "claude" in web
                else collect_claude(config["home"],now,timeout)),
      "kimi":("account",lambda:collect_kimi(config["home"],config["kimi_binary"],now,timeout,
          url=config.get("kimi_url"),start_server=config["start_kimi_server"],cwd=str(runtime))),
      # A website login (if connected) replaces the Qoder SDK route.
      "qoder":("account",lambda:collect_qoder_route(config,web.get("qoder"),runtime,now,timeout)),
      "workbuddy":("account",lambda:collect_workbuddy(web.get("workbuddy"),now,timeout)),
      "trae_cn":("account",lambda:collect_trae(web.get("trae_cn"),now,timeout)),
      "minimax_code":("account",lambda:collect_minimax(str(runtime),now,timeout,(web.get("minimax_code") or {}).get("api_key"))),
      "dreamina":("creative_account",lambda:collect_dreamina_route(config,now,timeout)),
      "minimax_design":("creative_personal_account",lambda:collect_design(config["design_gateway_url"],now,timeout,
          config["billing_overrides"].get("minimax_design"),config["node_binary"],config["design_mcp_entry"],config["design_probe_mcp"])),
      "deepseek_api":("api_account",lambda:collect_deepseek(now,timeout,(web.get("deepseek_api") or {}).get("api_key"),
          (web.get("deepseek_api") or {}).get("user_token"))),
      "zcode":("account",lambda:collect_zcode_route(config,web.get("zcode"),now,timeout)),
      "mimo":("api_account",lambda:collect_mimo(web.get("mimo"),now,timeout) if "mimo" in web
              else _raise(SourceError("web_session_missing"))),
      "stepfun":("account",lambda:collect_stepfun(web.get("stepfun"),now,timeout)),
      "volcengine":("account",lambda:collect_volcengine(web.get("volcengine"),now,timeout)),
      # Local token history; ZCode's own local usage db attaches to its
      # account source below (kimi pattern).
      "opencode":("local_session_history",lambda:collect_opencode_tokens(config["opencode_db"],now)),
      "gemini":("local_session_history",lambda:collect_gemini_sessions(config["gemini_dir"],now)),
      "antigravity":("account",lambda:collect_antigravity_sessions(config["agy_conversations_dir"],now,
                     desktop_root=config.get("agy_desktop_conversations_dir")) if config["local_only"]
                     else collect_antigravity(config,now)),
      "deepseek_harness":("local_session_history",lambda:collect_dsh_sessions(config["dsh_sessions_dir"],now,zstd_binary=config["zstd_binary"])),
      "kimi_desktop":("local_session_history",lambda:collect_kimi_desktop_tokens(config["kimi_desktop_sessions_dir"],now)),
      "kimi_legacy":("local_session_history",lambda:collect_kimi_legacy_tokens(config["kimi_legacy_sessions_dir"],now)),
      "mimo_code":("local_session_history",lambda:collect_mimocode_tokens(config["mimocode_db"],now)),
      "deveco":("local_session_history",lambda:collect_deveco_tokens(config["deveco_db"],now)),
      # Global-reset forecasts: third-party wording, never an account clock.
      "reset_forecast":("external_forecast",lambda:collect_reset_forecast(
          now=now,cache_path=str(runtime/CACHE_NAME),
          refresh_minutes=config["reset_forecast_refresh_minutes"])
          if config.get("enable_reset_forecast") else _raise(SourceError("disabled_in_config"))),
    }
    web_collectors={"claude":collect_claude_web,"qoder":collect_qoder_web,"workbuddy":collect_workbuddy,"trae_cn":collect_trae,
                    "mimo":collect_mimo,"zcode":collect_zcode,"volcengine":collect_volcengine,
                    "stepfun":collect_stepfun}
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
    def local_job(key, scope):
        return scope.startswith("local_") or key == "antigravity"

    sources=[]
    with ThreadPoolExecutor(max_workers=min(16,max(4,len(jobs)))) as pool:
        futures={key:pool.submit(safe_collect,key,scope,now,fn) for key,(scope,fn) in jobs.items()
                 if not switched_off(key) and key.split("#",1)[0] not in skip_ledgers
                 and (not config["local_only"] or local_job(key, scope))}
        # Parse the local session logs alongside the network jobs. submit()
        # runs immediately, so the user switches must gate each one.
        token_futures={}
        for provider, fn in (
            ("kimi",lambda:collect_kimi_tokens(config["home"],now)),
            ("workbuddy",lambda:collect_workbuddy_tokens(config["workbuddy_projects_dir"],now)),
            ("codex",lambda:codex_tokens_metric(config["codex_sessions_dir"],config["codex_archives_dir"],
                                                now,zstd_binary=config["zstd_binary"])),
            ("claude",lambda:claude_tokens_metric(config["claude_projects_dir"],now,
                                                  desktop_root=config["claude_desktop_sessions_dir"])),
            ("minimax_code",lambda:mcode_tokens_metric(config["mcode_db"],now)),
            ("zcode",lambda:zcode_tokens_metric(config["zcode_usage_db"],now)),
            # Design's agent ledger attaches to its account source (mcode
            # pattern) and is gated by the same source switch.
            ("minimax_design",lambda:collect_design_tokens(config["design_opencode_db"],config["opencode_db"],now)),
        ):
            # Claude's switch only stops the quota/keychain route; its local
            # token ledger (CLI + desktop) stays independent of that toggle.
            if (provider == "claude" or not switched_off(provider)) and provider not in skip_ledgers:
                token_futures[provider]=pool.submit(fn)
        # Codex 内置生图的按张统计（文件 + 历史库调用数），与账户网络无关。
        image_futures={}
        if not switched_off("codex") and "codex" not in skip_ledgers:
            image_futures["codex"]=pool.submit(
                lambda:codex_image_metric(config["codex_images_dir"],config["codex_history_db"],now,
                                          currency=table.currency,
                                          quality=config.get("codex_image_quality","high")))
        # Qoder CN's local credits ledger is account-page statistics, never a
        # tokens metric: it must not enter the local-consumption sum.
        credits_futures={}
        if not switched_off("qoder") and "qoder" not in skip_ledgers:
            credits_futures["qoder"]=pool.submit(lambda:collect_qoder_credits(config["qoder_projects_dir"],now))
        for key in jobs:
            if key not in futures:
                base=key.split("#",1)[0]
                reason=("disabled_by_user" if base in user_off else
                        "disabled_in_config" if switched_off(key) else
                        "skipped_low_resource" if base in skip_ledgers else "local_only_mode")
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
        if src["id"] == "codex":
            # Account RPC usage and rollout usage have different scopes.
            src["metrics"]["account_tokens"] = src["metrics"]["tokens"]
        try:src["metrics"]["tokens"]=future.result()
        except SourceError as e:
            status="not_connected" if e.code.endswith("_not_found") or e.code=="zstd_unavailable" else "error"
            src["metrics"]["tokens"]=metric(status=status,reason=e.code)
        except Exception:src["metrics"]["tokens"]=metric(status="error",reason="local_token_parse_failed")
    # Codex 内置生图（文件张数 + 历史库调用数）；本地读失败只影响该指标。
    for src in sources:
        future=image_futures.get(src["id"])
        if future is None:
            continue
        try:src["metrics"]["image_generation"]=future.result()
        except SourceError as e:src["metrics"]["image_generation"]=metric(status="not_connected",reason=e.code)
        except Exception:src["metrics"]["image_generation"]=metric(status="error",reason="codex_image_parse_failed")
    # Qoder CN local credits: folded into the account source's credits metric
    # (wallets stay under "rows"), never into tokens, so the local-consumption
    # tab cannot sum credits as tokens. Attached even when the account query
    # failed; a ledger error never discards web/SDK wallet rows.
    for src in sources:
        future=credits_futures.get(src["id"])
        if future is None:
            continue
        try:ledger=future.result()
        except SourceError as e:
            src["diagnostics"]["credits_ledger_error"]=e.code
            if src["metrics"]["credits"]["value"] is None:
                src["metrics"]["credits"]=metric(status="not_connected",reason=e.code)
        except Exception:
            src["diagnostics"]["credits_ledger_error"]="local_credits_parse_failed"
        else:
            src["metrics"]["credits"]=merge_credits_metric(src["metrics"]["credits"],ledger)
    # Web-page observations (即梦 membership / credit split) from the app.
    if not config["local_only"] and not switched_off("dreamina"):
        sources=merge_dreamina(sources,config.get("observations"),now)
    # Optional API-equivalent cost estimates from the local price table.
    # CodexBar keeps its own estimate; a provider-billed cost (DeepSeek web
    # usage) is never overwritten.
    for src in sources:
        if src["id"] in {"deepseek_api"} or src["id"].startswith("codexbar:"):continue
        tokens=src["metrics"]["tokens"]
        if tokens["status"] not in {"available","partial"} or src["metrics"]["cost"]["value"] is not None:continue
        estimated=estimate_source_cost(tokens,table)
        if estimated is not None:
            # Day-level amounts feed the collection's spending medals.
            estimated["value"]["daily"]=estimate_daily_cost(tokens,table)
            src["metrics"]["cost"]=estimated
    apps=discover(config["app_roots"])
    dreamina_cli=config.get("dreamina_binary") or config.get("dreamina_canvas_binary")
    if config.get("enable_dreamina_cli") and dreamina_cli:
        apps.append({"name":"即梦 CLI","provider":"dreamina","installed":True,"path":dreamina_cli,
                     "version":None,"bundle_id":None,"discovery_kind":"configured_cli"})
    usage=application_usage(sources)
    coverage=coverage_matrix(apps,sources,usage)
    return {"schema_version":SCHEMA_VERSION,"collected_at":timestamp(now),"display_timezone":"Asia/Shanghai",
            "sources":sources,"coverage":coverage,"application_usage":usage,
            "coverage_summary":coverage_summary(coverage),
            "aggregation_policy":"No cross-account balance sums. Each local ledger is counted independently; account usage remains separate."}


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
        self.snapshot_accounts={}
        self.generation=0
        # Activity endpoint: an independent lightweight scan with its own
        # short cache; it must never wait behind a full snapshot collection.
        self.activity_lock=threading.Lock()
        self._activity=None
        self._activity_at=0
        self._activity_generation=-1
        # Desktop pet: interprets data this service already holds, never collects.
        self.pet=PetMind(clock)
        # Daily free-credit rewards (status always, claiming opt-in).
        self.rewards=None
        # Card binder and medals built from the snapshot (no network).
        self.collection=None

    def activity(self,now=None):
        """Recent session/turn activity, cached for a few seconds.

        The cache also invalidates on any config change (generation bump),
        so price edits re-cost the rows on the next read.
        """
        from .activity import collect_activity
        from .prices import load_prices
        current=self.clock() if now is None else float(now)
        ttl=min(3,max(1,int(self.config.get("cache_ttl_seconds",120))//40))
        with self.lock:
            generation=self.generation
            if self._activity is not None and generation==self._activity_generation \
                    and current-self._activity_at<ttl:
                return copy.deepcopy(self._activity)
        with self.activity_lock:
            with self.lock:
                generation=self.generation
                current=self.clock() if now is None else float(now)
                if self._activity is not None and generation==self._activity_generation \
                        and current-self._activity_at<ttl:
                    return copy.deepcopy(self._activity)
                config=self.config.copy()
            try:
                table=load_prices(config["runtime_dir"],"USD")
            except Exception:
                table=None
            payload=collect_activity(config,now=current,table=table)
            with self.lock:
                self._activity=payload
                self._activity_at=current
                self._activity_generation=generation
            return copy.deepcopy(payload)

    def peek(self):
        """The last collected snapshot, or None; never starts a collection.

        Returned by reference for cheap polling: stored snapshots are replaced, never
        mutated, so readers must treat the result as read-only.
        """
        with self.lock:
            return self.snapshot

    def pet_frame(self,now=None,offline=False):
        """One PetFrame from cached data. Activity is scanned at most every 5 s (30 s when idle)."""
        current=self.clock() if now is None else float(now)
        activity=self.pet.poll_activity(lambda:self.activity(current),current)
        return self.pet.frame(self.peek(),activity,current,offline=offline)

    def pet_event(self,body):
        return self.pet.add_event(body)

    def set_pet_preferences(self,values):
        return self.pet.set_preferences(values)

    def _rewards_tick(self,config,now,only=None):
        """Reward status and opt-in claims; a failure never breaks the snapshot."""
        from .rewards import RewardsService
        try:
            if self.rewards is None:
                self.rewards=RewardsService(config["runtime_dir"])
            preferences=config.get("preferences") or {}
            disabled=set(config.get("disabled_sources") or [])|set(preferences.get("disabled_sources") or [])
            return self.rewards.tick(config.get("web_sessions"),now,auto_claim=set(preferences.get("auto_claim") or []),
                                     disabled=disabled,timeout=config["timeout_seconds"],only=only,
                                     local_only=config["local_only"],
                                     claim_time=preferences.get("claim_time") or "00:05",
                                     desktop={"qoder":config.get("qoder_app")})
        except Exception:
            return {"schema_version":1,"timezone":"Asia/Shanghai","accounts":[],"error":"rewards_failed"}

    def _collection(self,config,snapshot,now):
        from .collection import CollectionService
        try:
            if self.collection is None:
                self.collection=CollectionService(config["runtime_dir"])
            return self.collection.update(snapshot,self.rewards.ledger if self.rewards else None,now)
        except Exception:
            return {"schema_version":1,"error":"collection_failed"}

    def claim_now(self,slot):
        """The user's "claim now": reads and claims one account immediately."""
        with self.collect_lock:
            with self.lock:
                config,now=self.config.copy(),self.clock()
            rewards=self._rewards_tick(config,now,only=slot)
            with self.lock:
                snapshot=self.snapshot
            if snapshot is not None:
                updated=dict(snapshot,rewards=rewards)
                updated["collection"]=self._collection(config,updated,now)
                with self.lock:
                    if self.snapshot is snapshot:
                        self.snapshot=updated
            return rewards

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

    def set_prices(self,currency,models,aliases=None,peak_multipliers=None):
        """Persist prices, preview bindings and peak multipliers; then re-estimate."""
        from .prices import save_prices
        saved=save_prices(self.config["runtime_dir"],currency,models,aliases,peak_multipliers)
        self.reload_prices()
        return saved

    def reload_prices(self):
        """Invalidate snapshots after a catalogue sync without rewriting edits."""
        with self.lock:
            self._invalidate()

    def _ttl(self):
        base=self.config.get("cache_ttl_seconds",120)
        return base*3 if (self.config.get("preferences") or {}).get("low_resource_mode") else base

    def _cached(self,now):
        if self.snapshot is None or now-self.last_refresh>=self._ttl():
            return None
        out=copy.deepcopy(self.snapshot)
        out["served_from_cache"]=True
        return refresh_forecast_countdowns(refresh_countdowns(out,now),now)

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
                config,generation=self.config.copy(),self.generation
            fresh=self.collect_fn(config,now=now)
            accounts=config.get("web_sessions") or {}
            old={s["id"]:s for s in (self.snapshot or {}).get("sources",[])}
            replaced=False
            for index,src in enumerate(fresh["sources"]):
                provider=src["id"].split("#",1)[0]
                if src["scope"].startswith("local_"):
                    continue  # historical windows cannot be reused at a new cutoff
                previous=old.get(src["id"]) if accounts.get(provider)==self.snapshot_accounts.get(provider) else None
                if src["diagnostics"].get("reason") not in {"dreamina_not_authenticated","not_authenticated",
                        "design_account_changed_during_query","design_personal_scope_required","web_session_missing","disabled_by_user","disabled_in_config","local_only_mode",
                        "mimo_not_authenticated","volcengine_not_authenticated","volcengine_ark_key_not_supported",
                        "stepfun_not_authenticated","stepfun_credential_not_connected"} and src["status"] in {"error","not_connected"} and previous and previous["status"] in {"available","partial","stale"}:
                    cached=copy.deepcopy(previous)
                    cached["status"]="stale"
                    cached["diagnostics"]["last_attempt_at"]=timestamp(now)
                    cached["diagnostics"]["last_error"]=src["diagnostics"]["reason"]
                    for m in cached["metrics"].values():
                        if m["value"] is not None:m["status"]="stale"
                    # Local token history does not depend on the account network:
                    # keep the fresh measurement instead of the stale one.
                    previous_tokens=cached["metrics"]["tokens"].get("value") or {}
                    if "periods" in previous_tokens or src["metrics"]["tokens"]["status"] in {"available","partial"}:
                        cached["metrics"]["tokens"]=src["metrics"]["tokens"]
                        old_cost=(cached["metrics"]["cost"].get("value") or {})
                        if (isinstance(old_cost,dict) and old_cost.get("basis")=="local_price_table") or src["metrics"]["cost"]["value"] is not None:
                            cached["metrics"]["cost"]=src["metrics"]["cost"]
                    # Codex 内置生图同样来自本地文件，不随账户超时变 stale。
                    image=src["metrics"].get("image_generation") or {}
                    if src["id"]=="codex" and image:
                        cached["metrics"]["image_generation"]=image
                    if src["id"]=="qoder":
                        credits=src["metrics"]["credits"].get("value") or {}
                        if isinstance(credits,dict) and "usage" in credits:
                            recovered=merge_credits_metric(cached["metrics"]["credits"],credits["usage"])
                            if recovered["value"]["rows"]:
                                recovered["status"]="stale"
                            cached["metrics"]["credits"]=recovered
                    fresh["sources"][index]=cached
                    replaced=True
            if replaced:
                # Rebuild coverage after stale recovery so the UI can't show a
                # fresh-looking field attached to an old source.
                fresh["application_usage"]=application_usage(fresh["sources"])
                fresh["coverage"]=coverage_matrix([r["application"] for r in fresh["coverage"] if r["application"]["installed"]],fresh["sources"])
                fresh["coverage_summary"]=coverage_summary(fresh["coverage"])
            refresh_forecast_countdowns(refresh_countdowns(fresh,now),now)
            fresh["rewards"]=self._rewards_tick(config,now)
            fresh["collection"]=self._collection(config,fresh,now)
            fresh["served_from_cache"]=False
            with self.lock:
                self.snapshot_accounts=accounts
                self.snapshot=fresh
                self.last_refresh=now if generation==self.generation else 0
            atomic_json(Path(self.config["runtime_dir"])/"snapshot.json",fresh)
            return copy.deepcopy(fresh)
