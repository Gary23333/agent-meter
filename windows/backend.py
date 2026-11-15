"""Windows 适配层：复用上游只读采集器，仅输出指标，不输出会话内容或凭据。"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from agent_meter.cli_sessions import claude_tokens_metric, codex_tokens_metric, collect_gemini_sessions, mcode_tokens_metric
from agent_meter.activity import collect_activity
from agent_meter.claude_code import collect_claude
from agent_meter.codex import normalize_limits
from agent_meter.model import DISPLAY_ZONE, SourceError, metric
from agent_meter.transport import CodexRPC, get_json
from agent_meter.workbuddy_tokens import collect_workbuddy_tokens
from agent_meter.zcode_local import zcode_tokens_metric
from agent_meter.dsh_tokens import collect_dsh_sessions
from agent_meter.record_cache import records_cache
from agent_meter.prices import PriceTable, estimate_source_cost, normalize_model
from agent_meter.kimi_tokens import collect_kimi_tokens
from agent_meter.kimi import collect_kimi
from agent_meter.kimi_legacy_tokens import collect_kimi_legacy_tokens
from agent_meter.opencode_tokens import collect_opencode_tokens, readonly_database as opencode_database
from agent_meter.mimocode_tokens import collect_mimocode_tokens, collect_deveco_tokens
from agent_meter.minimax import collect_minimax, normalize_minimax
from agent_meter.qoder_tokens import collect_qoder_credits
from agent_meter.reset_forecast import collect_reset_forecast, default_fetchers
from windows.forecast import forecast_summary
from agent_meter.collection import CARDS, LEDGER_SCHEMA, load_ledger, medals, save_ledger, track_windows
from agent_meter.deepseek import collect_deepseek
from agent_meter.web_sources import collect_workbuddy
from agent_meter.zcode import collect_zcode
from agent_meter.volcengine import collect_volcengine
from agent_meter.mimo import collect_mimo


def codex_binary():
    # 优先使用真实可执行文件，避免把 .cmd 包装器拼入 shell 命令。
    found = shutil.which("codex.exe")
    if found:
        return found
    base = Path(os.environ.get("LOCALAPPDATA", "")) / "OpenAI" / "Codex" / "bin"
    candidates = list(base.glob("*/codex.exe")) if base.is_dir() else []
    return str(max(candidates, key=lambda p: p.stat().st_mtime)) if candidates else None


def quota(binary, now):
    with CodexRPC(binary, timeout=25) as rpc:
        result = rpc.call("account/rateLimits/read", {"excludeResetCreditDetails": False, "supportsLunaReserve": False})
    source = normalize_limits(result, now)
    return {"status": source["status"], "quota": source["metrics"]["quota"],
            "credits": source["metrics"]["credits"], "reset_cards": source["metrics"]["reset_cards"]}


def kimi_quota(home, now):
    root = Path(os.environ.get("KIMI_CODE_HOME") or home / ".kimi-code")
    # 只连接已运行的本地服务，不启动辅助进程、不发送提示词。
    source = collect_kimi(home, None, now, timeout=3, start_server=False, server_root=root)
    return {"status": source["status"], "quota": source["metrics"]["quota"],
            "credits": source["metrics"]["credits"]}


def claude_quota(home, now):
    root = Path(os.environ.get("CLAUDE_CONFIG_DIR") or home / ".claude")
    credentials = root / ".credentials.json"
    # Windows 只尝试 Claude Code 已有的本地凭据文件，不调用 macOS 钥匙串，也不刷新令牌。
    if not credentials.is_file():
        raise SourceError("claude_subscription_login_missing")
    source = collect_claude(home, now, timeout=12, credential_path=credentials)
    return {"status": source["status"], "quota": source["metrics"]["quota"], "subscription": source.get("subscription")}


def minimax_quota(home, now):
    # 仅在用户启用时读取已有环境变量；不保存密钥，也不执行外部脚本。
    key = os.environ.get("MINIMAX_TOKEN_PLAN_KEY")
    if not key:
        raise SourceError("minimax_credential_not_connected")
    source = collect_minimax(home, now, timeout=12, app_key=key)
    return {"status": source["status"], "quota": source["metrics"]["quota"]}


def deepseek_balance(key, now):
    """仅查询用户明确提供的 API 密钥，不回退读取进程环境变量。"""
    if key is None:
        raise SourceError("deepseek_credential_not_connected")
    if not isinstance(key, str) or not 0 < len(key) <= 1280 or any(not '!' <= c <= '~' for c in key):
        raise SourceError("deepseek_credential_invalid")
    source = collect_deepseek(now, timeout=12, key=key)
    return {"status": source["status"], "credits": source["metrics"]["credits"]}


def zcode_quota(key, now):
    """只使用用户主动提供的 Coding Plan 密钥，不读取桌面或浏览器登录。"""
    if key is None:
        raise SourceError("zcode_credential_not_connected")
    if not isinstance(key, str) or not 0 < len(key) <= 1280 or any(not '!' <= c <= '~' for c in key):
        raise SourceError("zcode_credential_invalid")
    source = collect_zcode({"api_key": key}, now, timeout=12)
    return {"status": source["status"], "quota": source["metrics"]["quota"],
            "subscription": {"plan": source.get("subscription", {}).get("plan")}}


def volcengine_quota(credentials, now):
    """只使用用户主动提供的 AccessKey 对，只调用上游固定的额度接口。"""
    if credentials is None:
        raise SourceError("volcengine_credential_not_connected")
    if not isinstance(credentials, dict) or set(credentials) != {"access_key_id", "secret_access_key"}:
        raise SourceError("volcengine_credential_invalid")
    ak, sk = credentials["access_key_id"], credentials["secret_access_key"]
    if (not isinstance(ak, str) or not ak.startswith("AK") or not 2 <= len(ak) <= 240 or
            not isinstance(sk, str) or not 0 < len(sk) <= 512 or any(not '!' <= c <= '~' for c in ak + sk)):
        raise SourceError("volcengine_credential_invalid")
    source = collect_volcengine({"access_key_id": ak, "secret_access_key": sk}, now, timeout=12)
    return {"status": source["status"], "quota": source["metrics"]["quota"],
            "subscription": {"plan": source.get("subscription", {}).get("plan")}}


def workbuddy_balance(session, now):
    """只使用应用专用登录窗口提供的会话，不访问用户浏览器资料。"""
    if session is None:
        raise SourceError("workbuddy_session_missing")
    if not isinstance(session, dict) or set(session) != {"cookie", "user_agent"}:
        raise SourceError("workbuddy_session_invalid")
    cookie, user_agent = session["cookie"], session["user_agent"]
    if (not isinstance(cookie, str) or not 0 < len(cookie) <= 16000 or
            not isinstance(user_agent, str) or not 0 < len(user_agent) <= 1024 or
            any(not ' ' <= c <= '~' for c in cookie + user_agent)):
        raise SourceError("workbuddy_session_invalid")
    source = collect_workbuddy(session, now, timeout=12)
    return {"status": source["status"], "quota": source["metrics"]["quota"],
            "credits": source["metrics"]["credits"], "subscription": source.get("subscription")}


def mimo_account(session, now):
    """只接收应用内独立网页资料；上游只发送允许的 MiMo Cookie。"""
    if session is None:
        raise SourceError("mimo_session_missing")
    if not isinstance(session, dict) or set(session) != {"cookie", "user_agent"}:
        raise SourceError("mimo_session_invalid")
    cookie, user_agent = session["cookie"], session["user_agent"]
    if (not isinstance(cookie, str) or not 0 < len(cookie) <= 16000 or
            not isinstance(user_agent, str) or not 0 < len(user_agent) <= 1024 or
            any(not ' ' <= c <= '~' for c in cookie + user_agent)):
        raise SourceError("mimo_session_invalid")
    source = collect_mimo({"cookie": cookie, "user_agent": user_agent}, now, timeout=12)
    quota = source["metrics"]["quota"]
    quota_error = quota.get("status") == "error"
    partial = quota_error or quota.get("reason") == "mimo_token_plan_usage_unrecognized"
    return {"status": "partial" if partial else source["status"], "reason": "mimo_quota_unavailable" if partial else None,
            "quota": quota, "credits": source["metrics"]["credits"],
            "subscription": None if quota_error else source.get("subscription")}


def validate_account_input(data):
    """只接受本进程标准输入中的受限账户数据，不记录或返回密钥。"""
    if not isinstance(data, dict) or set(data) != {"minimax_accounts"} or not isinstance(data["minimax_accounts"], list):
        raise ValueError("invalid account input")
    accounts = data["minimax_accounts"]
    if len(accounts) > 5:
        raise ValueError("too many accounts")
    seen = set()
    for item in accounts:
        if not isinstance(item, dict) or set(item) != {"label", "region", "key"}:
            raise ValueError("invalid account")
        label, region, key = item["label"], item["region"], item["key"]
        if (not isinstance(label, str) or not 0 < len(label.strip()) <= 32 or any(ord(c) < 32 or ord(c) == 127 for c in label)
                or label.casefold() in seen or region not in {"cn", "global"}
                or (key is not None and (not isinstance(key, str) or not 0 < len(key) <= 1280 or any(ord(c) < 32 or ord(c) == 127 for c in key)))):
            raise ValueError("invalid account")
        seen.add(label.casefold())
    return accounts


def minimax_saved_quota(account, now):
    key = account["key"]
    if key is None:
        raise SourceError("minimax_vault_credential_missing")
    domain = "www.minimax.cn" if account["region"] == "cn" else "www.minimax.io"
    source = normalize_minimax(get_json("https://" + domain + "/v1/token_plan/remains", key, timeout=12), now)
    return {"status": source["status"], "quota": source["metrics"]["quota"]}


def account_sources(home, now, disabled_accounts=frozenset(), enable_minimax=False, saved_accounts=None):
    with ThreadPoolExecutor(max_workers=4) as executor:
        jobs = {"codex": lambda: quota(codex_binary(), now),
                "kimi": lambda: kimi_quota(home, now), "claude": lambda: claude_quota(home, now),
                "minimax": lambda: minimax_quota(home, now)}
        futures = {name: executor.submit(guarded, job) for name, job in jobs.items()
                   if name not in disabled_accounts and (name != "minimax" or (enable_minimax and saved_accounts is None))}
        saved = [(item["label"], executor.submit(guarded, lambda account=item: minimax_saved_quota(account, now)))
                 for item in (saved_accounts or [])] if enable_minimax else []
        def result(name):
            return futures[name].result() if name in futures else {"status": "disabled", "reason": "disabled_by_user"}
        minimax = ([{"label": label, **future.result()} for label, future in saved] if saved else
                   {"status": "unavailable", "reason": "minimax_no_saved_accounts"}) if enable_minimax and saved_accounts is not None else result("minimax")
        return result("codex"), {"Kimi Code": result("kimi"), "Claude Code": result("claude"), "MiniMax Code": minimax}


def histories(home, now):
    codex = Path(os.environ.get("CODEX_HOME") or home / ".codex")
    claude = Path(os.environ.get("CLAUDE_CONFIG_DIR") or home / ".claude")
    kimi_root = Path(os.environ.get("KIMI_CODE_HOME") or home / ".kimi-code")
    xdg = os.environ.get("XDG_DATA_HOME")
    data_root = Path(xdg) if xdg and Path(xdg).is_absolute() else home / ".local" / "share"
    opencode_override = os.environ.get("OPENCODE_DB")
    opencode_path = (data_root / "opencode" / "opencode.db" if not opencode_override else
                     Path(opencode_override) if Path(opencode_override).is_absolute() else data_root / "opencode" / opencode_override)
    def opencode():
        if opencode_override == ":memory:":
            raise SourceError("opencode_memory_database")
        result = collect_opencode_tokens(opencode_path, now)["metrics"]["tokens"]
        # 上游解析器尚不读取 OpenCode v2 消息；发现新版记录时标记不完整。
        with opencode_database(opencode_path) as connection:
            has_v2 = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='session_message'").fetchone()
            if has_v2 and connection.execute("SELECT 1 FROM session_message LIMIT 1").fetchone():
                result["status"] = "partial"
                result["reason"] = "opencode_v2_unread"
        return result
    return {
        "Codex": lambda: codex_tokens_metric(codex / "sessions", codex / "archived_sessions", now),
        "Claude Code": lambda: claude_tokens_metric(claude / "projects", now),
        "Gemini CLI": lambda: collect_gemini_sessions(home / ".gemini", now)["metrics"]["tokens"],
        "WorkBuddy": lambda: collect_workbuddy_tokens(home / ".workbuddy" / "projects", now),
        "ZCode": lambda: zcode_tokens_metric(home / ".zcode" / "cli" / "db" / "db.sqlite", now),
        "DeepSeek Harness": lambda: collect_dsh_sessions(Path(os.environ.get("DSH_HOME") or home / ".dsh") / "sessions", now)["metrics"]["tokens"],
        "Kimi Code": lambda: collect_kimi_tokens(home, now, sessions_root=kimi_root / "sessions"),
        "Kimi CLI (旧版)": lambda: collect_kimi_legacy_tokens(home / ".kimi" / "sessions", now)["metrics"]["tokens"],
        "OpenCode": opencode,
        "MiniMax Code": lambda: mcode_tokens_metric(home / ".minimax" / "v2" / "sqlite" / "runtime-state.sqlite", now),
        "MiMo Code": lambda: collect_mimocode_tokens(data_root / "mimocode" / "mimocode.db", now)["metrics"]["tokens"],
        "DevECo": lambda: collect_deveco_tokens(data_root / "deveco" / "deveco-stable.db", now)["metrics"]["tokens"],
    }


def activity_config(home):
    """为 Windows 本机活动读取器设置路径；未适配的桌面端路径保持缺省。"""
    codex = Path(os.environ.get("CODEX_HOME") or home / ".codex")
    claude = Path(os.environ.get("CLAUDE_CONFIG_DIR") or home / ".claude")
    kimi = Path(os.environ.get("KIMI_CODE_HOME") or home / ".kimi-code")
    xdg = os.environ.get("XDG_DATA_HOME")
    data = Path(xdg) if xdg and Path(xdg).is_absolute() else home / ".local" / "share"
    override = os.environ.get("OPENCODE_DB")
    opencode = (data / "opencode" / "opencode.db" if not override or override == ":memory:" else
                Path(override) if Path(override).is_absolute() else data / "opencode" / override)
    if override == ":memory:":
        opencode = home / ".agent-meter-no-opencode-db"
    return {"home": str(home), "codex_state_db": str(codex / "state_5.sqlite"),
            "codex_history_db": str(codex / "thread_history_1.sqlite"),
            "zcode_usage_db": str(home / ".zcode" / "cli" / "db" / "db.sqlite"),
            "kimi_code_sessions_dir": str(kimi / "sessions"),
            "kimi_desktop_sessions_dir": str(home / ".agent-meter-unavailable" / "kimi-desktop"),
            "kimi_legacy_sessions_dir": str(home / ".kimi" / "sessions"),
            "dsh_sessions_dir": str(Path(os.environ.get("DSH_HOME") or home / ".dsh") / "sessions"),
            "zstd_binary": shutil.which("zstd"), "claude_projects_dir": str(claude / "projects"),
            "claude_desktop_sessions_dir": None, "gemini_dir": str(home / ".gemini"),
            "opencode_db": str(opencode), "mimocode_db": str(data / "mimocode" / "mimocode.db"),
            "deveco_db": str(data / "deveco" / "deveco-stable.db"),
            "activity_window_hours": 24, "activity_idle_minutes": 15}


def compact_activity(payload, now):
    """只输出各应用的计数和更新时间，不传递会话标识、项目路径或内容。"""
    names = {"codex": "Codex", "codex_images": "Codex 生图", "zcode": "ZCode", "kimi": "Kimi Code",
             "kimi_desktop": "Kimi 桌面端", "kimi_legacy": "Kimi CLI（旧版）", "deepseek_harness": "DeepSeek Harness",
             "claude": "Claude Code", "gemini": "Gemini CLI", "opencode": "OpenCode", "mimo_code": "MiMo Code", "deveco": "DevECo"}
    groups = {}
    invalid_sources = set()
    for row in payload.get("activities", []):
        if not isinstance(row, dict) or row.get("app") not in names:
            continue
        stamp = row.get("last_event_at")
        stamp = stamp.get("epoch_seconds") if isinstance(stamp, dict) else None
        if isinstance(stamp, bool) or not isinstance(stamp, (int, float)) or not math.isfinite(stamp) or not 0 <= stamp <= now:
            invalid_sources.add(row["app"])
            continue
        item = groups.setdefault(row["app"], {"name": names[row["app"]], "sessions": 0, "recent_updates": 0, "last_updated": 0})
        item["sessions"] += 1
        item["recent_updates"] += int(now - stamp <= 15 * 60)
        item["last_updated"] = max(item["last_updated"], int(stamp))
    meta = payload.get("sources_meta")
    incomplete = bool(invalid_sources) or not isinstance(meta, dict) or any(isinstance(item, dict) and
        (item.get("status") == "error" or (item.get("status") == "not_connected" and item.get("reason") and
         not str(item.get("reason")).endswith("_not_found") and item.get("reason") != "disabled_by_user")) for item in meta.values())
    sources = {}
    if isinstance(meta, dict):
        for key, name in names.items():
            item = meta.get(key)
            if not isinstance(item, dict):
                continue
            status, reason = item.get("status"), item.get("reason")
            if status == "available":
                sources[name] = "partial" if key in invalid_sources else "available"
            elif status == "not_connected" and reason == "disabled_by_user":
                sources[name] = "disabled"
            elif status == "not_connected" and isinstance(reason, str) and reason.endswith("_not_found"):
                sources[name] = "not_found"
            else:
                sources[name] = "unavailable"
    return {"status": "partial" if incomplete else "available", "window_hours": 24, "idle_minutes": 15, "observed_at": int(now),
            "sources": sources,
            "apps": sorted(groups.values(), key=lambda item: (-item["recent_updates"], -item["last_updated"], item["name"]))}


def guarded(fn):
    try:
        return fn()
    except SourceError as exc:
        return {"status": "unavailable", "reason": exc.code, "value": None}
    except (OSError, ValueError, TypeError, KeyError, OverflowError):
        return {"status": "error", "reason": "read_failed", "value": None}


def forecast_only(directory):
    """调用前必须由用户主动启用；仅缓存公开预测，不读取本机账本或凭据。"""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    # 历史跟随预测的缓存周期更新，避免第二次联网刷新把已有历史覆盖为空。
    return forecast_summary(collect_reset_forecast(cache_path=directory / "reset-forecast.json",
                                                 fetchers=default_fetchers(with_history=True)))


def collect(local_only=False, home=None, account_only=False, disabled_accounts=frozenset(), enable_minimax=False, saved_accounts=None):
    now = time.time()
    home = Path(home) if home else Path.home()
    if account_only:
        codex, other_accounts = account_sources(home, now, disabled_accounts, enable_minimax, saved_accounts)
        return {"version": 1, "observed_at": int(now),
                "account": codex, "other_accounts": other_accounts, "history": {}}
    jobs = histories(home, now)
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {name: executor.submit(guarded, fn) for name, fn in jobs.items()}
        qoder = executor.submit(guarded, lambda: metric(collect_qoder_credits(home / ".qoder-cn" / "projects", now)))
        account = None if local_only else executor.submit(account_sources, home, now, disabled_accounts, enable_minimax, saved_accounts)
        account_values = None if account is None else account.result()
        return {"version": 1, "observed_at": int(now),
                "account": {"status": "disabled", "reason": "local_only"} if account is None else account_values[0],
                "other_accounts": {} if account_values is None else account_values[1],
                "history": {name: future.result() for name, future in futures.items()},
                "local_credits": {"Qoder CN": qoder.result()}}


def recent_daily_trend(result):
    """汇总北京时间最近七个自然日；缺失日只对可读取的账本视作零。"""
    today = datetime.fromtimestamp(result["observed_at"], DISPLAY_ZONE).date()
    days = [(today - timedelta(days=offset)).isoformat() for offset in range(6, -1, -1)]
    totals = dict.fromkeys(days, 0)
    sources = 0
    incomplete = False
    for item in result["history"].values():
        status = item.get("status")
        reason = item.get("reason") or ""
        if status in {"error", "partial"} or (status == "unavailable" and reason and not reason.endswith("_not_found")):
            incomplete = True
        value = item.get("value")
        if not isinstance(value, dict):
            continue
        periods = value.get("periods", {})
        all_totals = periods.get("all", {}).get("totals", {})
        if all_totals.get("requests") == 0:
            continue
        rows = value.get("daily_buckets")
        if not isinstance(rows, list):
            incomplete = True
            continue
        sources += 1
        for row in rows:
            if not isinstance(row, dict):
                incomplete = True
                continue
            day, count = row.get("date"), row.get("tokens")
            if not isinstance(day, str) or not isinstance(count, int) or isinstance(count, bool) or count < 0:
                incomplete = True
                continue
            if day in totals:
                totals[day] += count
    return {"days": [{"date": day, "tokens": totals[day]} for day in days],
            "sources": sources, "incomplete": incomplete} if sources else None


def source_daily_trend(item, observed_at):
    """只传递单个账本最近 30 个北京时间自然日的汇总，不传项目或会话字段。"""
    value = item.get("value")
    rows = value.get("daily_buckets") if isinstance(value, dict) else None
    if not isinstance(rows, list) or not rows:
        return None
    today = datetime.fromtimestamp(observed_at, DISPLAY_ZONE).date()
    days = [(today - timedelta(days=offset)).isoformat() for offset in range(29, -1, -1)]
    totals = dict.fromkeys(days, 0)
    incomplete = item.get("status") != "available"
    valid_rows = 0
    for row in rows:
        if not isinstance(row, dict):
            incomplete = True
            continue
        day, count = row.get("date"), row.get("tokens")
        if not isinstance(day, str) or not isinstance(count, int) or isinstance(count, bool) or count < 0:
            incomplete = True
            continue
        try:
            if date.fromisoformat(day).isoformat() != day:
                raise ValueError()
        except ValueError:
            incomplete = True
            continue
        valid_rows += 1
        if day in totals:
            totals[day] += count
    if not valid_rows:
        return None
    return {"days": [{"date": day, "tokens": totals[day]} for day in days], "incomplete": incomplete}


def calendar_report(result):
    """汇总北京时间自然周和自然月；当前周期为截至采集时的部分周期。"""
    today = datetime.fromtimestamp(result["observed_at"], DISPLAY_ZONE).date()
    week = today - timedelta(days=today.weekday())
    month = today.replace(day=1)
    last_month = (month - timedelta(days=1)).replace(day=1)
    bounds = {"week": (week - timedelta(days=7), week), "month": (last_month, month)}
    out = {}
    for kind, (previous, current) in bounds.items():
        # 按完整自然日对齐，当前日期仍在进行中；上月天数不足时两边都截到共同长度。
        completed = min((today - current).days, (current - previous).days)
        out[kind] = {"previous_start": previous.isoformat(), "current_start": current.isoformat(),
                     "current_end": today.isoformat(), "previous_tokens": 0, "current_tokens": 0,
                     "comparable_days": completed, "current_comparable_tokens": 0, "previous_comparable_tokens": 0}
    sources = 0
    incomplete = False
    for item in result["history"].values():
        status, reason = item.get("status"), item.get("reason") or ""
        if status in {"error", "partial"} or (status == "unavailable" and reason and not reason.endswith("_not_found")):
            incomplete = True
        value = item.get("value")
        if not isinstance(value, dict):
            continue
        all_totals = value.get("periods", {}).get("all", {}).get("totals", {})
        if all_totals.get("requests") == 0:
            continue
        rows = value.get("daily_buckets")
        if not isinstance(rows, list):
            incomplete = True
            continue
        sources += 1
        for row in rows:
            if not isinstance(row, dict):
                incomplete = True
                continue
            try:
                day = date.fromisoformat(row.get("date", ""))
            except (TypeError, ValueError):
                incomplete = True
                continue
            count = row.get("tokens")
            if isinstance(count, bool) or not isinstance(count, int) or count < 0:
                incomplete = True
                continue
            for kind, (previous, current) in bounds.items():
                if current <= day <= today:
                    out[kind]["current_tokens"] += count
                elif previous <= day < current:
                    out[kind]["previous_tokens"] += count
                elapsed = out[kind]["comparable_days"]
                if current <= day < current + timedelta(days=elapsed):
                    out[kind]["current_comparable_tokens"] += count
                elif previous <= day < previous + timedelta(days=elapsed):
                    out[kind]["previous_comparable_tokens"] += count
    return {"periods": out, "sources": sources, "incomplete": incomplete, "timezone": "Asia/Shanghai"} if sources else None


def local_medals(result):
    """按上游规则计算可由本机逐日账本支持的徽章，不推断缺失来源。"""
    today = datetime.fromtimestamp(result["observed_at"], DISPLAY_ZONE).date()
    sources, incomplete = [], False
    for name, item in result.get("history", {}).items():
        status, reason = item.get("status"), item.get("reason") or ""
        if status in {"error", "partial"} or (status == "unavailable" and reason and not reason.endswith("_not_found")):
            incomplete = True
        if status not in {"available", "partial", "stale"}:
            continue
        value = item.get("value")
        if not isinstance(value, dict):
            continue
        totals = value.get("periods", {}).get("all", {}).get("totals", {})
        if totals.get("requests") == 0:
            continue
        rows = value.get("daily_buckets")
        if not isinstance(rows, list):
            incomplete = True
            continue
        valid = []
        for row in rows:
            if not isinstance(row, dict):
                incomplete = True
                continue
            try:
                day = date.fromisoformat(row.get("date", ""))
            except (TypeError, ValueError):
                incomplete = True
                continue
            count = row.get("tokens")
            if day > today or isinstance(count, bool) or not isinstance(count, int) or not 0 <= count <= 2**63 - 1:
                incomplete = True
                continue
            valid.append({"date": day.isoformat(), "tokens": count})
        expected = totals.get("total_tokens")
        if isinstance(expected, int) and not isinstance(expected, bool) and expected >= 0 and sum(row["tokens"] for row in valid) != expected:
            incomplete = True
        if not any(row["tokens"] > 0 for row in valid):
            continue
        sources.append({"id": name, "metrics": {"tokens": {"status": "available", "value": {"daily_buckets": valid}}}})
    if not sources:
        return {"medals": [], "sources": 0, "incomplete": True} if incomplete else None
    all_medals, stats = medals(sources, None, result["observed_at"])
    available = {"day_peak", "lifetime", "streak", "apps", "record"}
    rows = [{key: medal[key] for key in ("id", "name", "category", "category_name", "target", "unit", "tier", "value", "progress", "earned", "earned_on")}
            for medal in all_medals if medal["category"] in available]
    return {"medals": rows, "sources": len(sources), "incomplete": incomplete,
            "earned": sum(item["earned"] for item in rows), "total": len(rows),
            "active_days": stats["active_days"], "timezone": "Asia/Shanghai"}


def quota_card_sources(snapshot, now):
    """只投影可信额度窗口；多账户名称不会写入卡册账本。"""
    if not isinstance(snapshot, dict):
        raise ValueError("invalid account snapshot")
    others = snapshot.get("other_accounts") if isinstance(snapshot.get("other_accounts"), dict) else {}
    accounts = [("codex", snapshot.get("account")), ("kimi", others.get("Kimi Code")),
                ("claude", others.get("Claude Code"))]
    minimax = others.get("MiniMax Code")
    if isinstance(minimax, list):
        for item in minimax[:5]:
            if not isinstance(item, dict):
                continue
            label = item.get("label")
            if not isinstance(label, str) or not 0 < len(label.strip()) <= 32 or any(ord(c) < 32 or ord(c) == 127 for c in label):
                continue
            identity = hashlib.sha256(label.casefold().encode("utf-8")).hexdigest()[:24]
            accounts.append(("minimax#" + identity, item))
    else:
        accounts.append(("minimax", minimax))
    sources = []
    for identity, account in accounts:
        if not isinstance(account, dict) or account.get("status") not in {"available", "partial"}:
            continue
        quota = account.get("quota")
        rows = quota.get("value") if isinstance(quota, dict) else None
        if not isinstance(rows, list) or quota.get("status") not in {None, "available", "partial"}:
            continue
        safe = []
        for row in rows[:50]:
            if not isinstance(row, dict):
                continue
            bucket, remaining = row.get("bucket"), row.get("remaining_percent")
            reset = row.get("resets_at")
            reset = reset.get("epoch_seconds") if isinstance(reset, dict) else None
            if (not isinstance(bucket, str) or not 0 < len(bucket) <= 80 or
                    not all(c.isascii() and (c.isalnum() or c in "_-.") for c in bucket) or
                    isinstance(remaining, bool) or not isinstance(remaining, (int, float)) or
                    not math.isfinite(remaining) or not 0 <= remaining <= 100 or
                    isinstance(reset, bool) or not isinstance(reset, (int, float)) or
                    not math.isfinite(reset) or not now < reset <= now + 400 * 86400):
                continue
            out = {"bucket": bucket, "used_percent": 100 - remaining, "resets_at": {"epoch_seconds": int(reset)}}
            minutes = row.get("window_minutes")
            if not isinstance(minutes, bool) and isinstance(minutes, (int, float)) and math.isfinite(minutes) and 0 < minutes <= 525600:
                out["window_minutes"] = minutes
            elif bucket in {"limit5h", "limit7d"}:
                out["window_minutes"] = 300 if bucket == "limit5h" else 10080
            window = row.get("window")
            if isinstance(window, dict) and window.get("unit") in {"minute", "minutes", "hour", "hours", "day", "days", "week", "weeks"}:
                duration = window.get("duration")
                if not isinstance(duration, bool) and isinstance(duration, (int, float)) and math.isfinite(duration) and 0 < duration <= 525600:
                    out["window"] = {"unit": window["unit"], "duration": duration}
            safe.append(out)
        if safe:
            sources.append({"id": identity, "scope": "account", "status": "available",
                            "metrics": {"quota": {"status": "available", "value": safe}}})
    return sources


def update_quota_cards(directory, snapshot, now):
    """复用上游阈值规则并原子保存额度卡片进度；不保存账户密钥或会话。"""
    path = Path(directory) / "collection.json"
    if path.exists():
        try:
            if path.stat().st_size > 8 * 1024 * 1024:
                raise ValueError("ledger_too_large")
            existing = json.loads(path.read_text(encoding="utf-8"))
            required = {"windows": dict, "drops": list}
            optional = {"inventory": dict, "cards": dict, "creative": dict}
            if not isinstance(existing, dict) or existing.get("schema") != LEDGER_SCHEMA or any(
                    not isinstance(existing.get(key), kind) for key, kind in required.items()) or any(
                    key in existing and not isinstance(existing[key], kind) for key, kind in optional.items()):
                raise ValueError("ledger_invalid")
            for state in existing["windows"].values():
                if not isinstance(state, dict) or state.get("kind") not in {"five_hour", "seven_day"} or not isinstance(state.get("source"), str):
                    raise ValueError("ledger_invalid")
                for field in ("resets_at", "peak", "first_at", "last_at"):
                    number = state.get(field)
                    if isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number):
                        raise ValueError("ledger_invalid")
                if not 0 <= state["peak"] <= 100 or ("granted" in state and not isinstance(state["granted"], list)):
                    raise ValueError("ledger_invalid")
            for item in existing.get("cards", {}).values():
                if not isinstance(item, dict) or isinstance(item.get("count"), bool) or not isinstance(item.get("count"), int) or item["count"] < 0:
                    raise ValueError("ledger_invalid")
        except (OSError, ValueError, TypeError):
            return {"status": "error", "reason": "collection_ledger_unreadable", "cards": []}
    ledger = load_ledger(path)
    if track_windows(ledger, quota_card_sources(snapshot, now), now):
        save_ledger(path, ledger)
    definitions = [item for item in CARDS if item[2] in {"five_hour", "seven_day"}]
    cards = []
    for card_id, name, series, rarity, _symbol, description in definitions:
        owned = ledger["cards"].get(card_id, {})
        count = owned.get("count", 0) if isinstance(owned, dict) else 0
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            return {"status": "error", "reason": "collection_ledger_unreadable", "cards": []}
        cards.append({"id": card_id, "name": name, "series": series, "rarity": rarity,
                      "description": description, "count": count})
    return {"status": "available", "cards": cards, "distinct": sum(card["count"] > 0 for card in cards)}


_DEFAULT_PRICE_TABLE = object()


def load_price_table(directory):
    """读取可选的美元自定义价格；损坏时不显示估算，绝不回退成看似有效的值。"""
    if directory is None:
        return PriceTable("USD", {}, set())
    path = Path(directory) / "prices.json"
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate price field")
            result[key] = value
        return result
    try:
        if path.stat().st_size > 1024 * 1024:
            return None
        data = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_object)
        rows = data.get("models") if isinstance(data, dict) and set(data) == {"currency", "models"} and data.get("currency") == "USD" else None
        if not isinstance(rows, dict) or len(rows) > 200:
            return None
        models, seen = {}, set()
        for pattern, values in rows.items():
            if (not isinstance(pattern, str) or not 0 < len(pattern.strip()) <= 120 or not isinstance(values, dict)
                    or set(values) != {"input", "cache_read", "cache_write", "output"}):
                return None
            normalized = normalize_model(pattern)
            if not normalized or normalized in seen:
                return None
            seen.add(normalized)
            rates = []
            for key in ("input", "cache_read", "cache_write", "output"):
                rate = values.get(key)
                if isinstance(rate, bool) or not isinstance(rate, (int, float)) or not math.isfinite(rate) or not 0 <= rate <= 1_000_000:
                    return None
                rates.append(rate)
            models[pattern] = tuple(rates)
        return PriceTable("USD", models, set())
    except FileNotFoundError:
        return PriceTable("USD", {}, set())
    except (OSError, ValueError, TypeError, OverflowError):
        return None


def compact_history(result, price_table=_DEFAULT_PRICE_TABLE):
    """仅向面板传递显示字段；模型明细按用量排序并限制数量。"""
    compact = {"version": result["version"], "observed_at": result["observed_at"],
               "account": result["account"], "history": {}}
    # 使用上游内置美元价格和固定回退汇率，不联网更新价格或把估算当作账单。
    table = PriceTable("USD", {}, set()) if price_table is _DEFAULT_PRICE_TABLE else price_table
    compact["price_status"] = "available" if table is not None else "invalid"
    for name, item in result["history"].items():
        value = item.get("value")
        periods = value.get("periods", {}) if isinstance(value, dict) else {}
        all_period = periods.get("all", {})
        all_totals = all_period.get("totals", {}) if isinstance(all_period, dict) else {}
        # 目录存在但没有用量记录，不能据此认定实际消耗为零。
        if isinstance(all_totals, dict) and all_totals.get("requests") == 0:
            partial = item.get("status") == "partial"
            compact["history"][name] = {"status": "partial" if partial else "not_provided",
                                        "reason": item.get("reason") if partial else "history_no_usage_records", "value": None}
            continue
        selected = {}
        for period in ("today", "7d", "30d", "all"):
            bucket = periods.get(period)
            totals = bucket.get("totals") if isinstance(bucket, dict) else None
            if isinstance(totals, dict) and "total_tokens" in totals:
                keys = ("total_tokens", "requests", "fresh_input", "output", "reasoning", "cache_read", "cache_write", "unclassified")
                selected[period] = {"totals": {key: totals[key] for key in keys if key in totals}}
                if period == "7d" and isinstance(bucket.get("groups"), list):
                    groups = []
                    for row in bucket["groups"]:
                        if not isinstance(row, dict):
                            continue
                        model, count = row.get("model"), row.get("total_tokens")
                        if (isinstance(model, str) and 0 < len(model) < 120 and
                                isinstance(count, int) and not isinstance(count, bool) and count >= 0):
                            groups.append({"model": model, "total_tokens": count})
                    groups.sort(key=lambda row: row["total_tokens"], reverse=True)
                    selected[period]["groups"] = groups[:20]
                    selected[period]["groups_truncated"] = len(groups) > 20
        compact_value = {"periods": selected} if selected else None
        if compact_value is not None:
            compact_value["daily_trend"] = source_daily_trend(item, result["observed_at"])
        compact["history"][name] = {"status": item.get("status"), "reason": item.get("reason"),
                                    "value": compact_value}
        try:
            estimated = estimate_source_cost(item, table) if table is not None else None
        except (TypeError, ValueError, KeyError, InvalidOperation, OverflowError):
            # 价格估算失败不影响本机用量显示，也不把未知价格当作零。
            estimated = None
        estimates = {}
        for period in ("today", "7d", "30d", "all"):
            try:
                cost = (estimated or {}).get("value", {}).get("periods", {}).get(period, {})
                bucket = periods.get(period, {})
                total = bucket.get("totals", {}).get("total_tokens") if isinstance(bucket, dict) else None
                groups = bucket.get("groups") if isinstance(bucket, dict) else None
                amount = Decimal(str(cost.get("amount")))
                if not (isinstance(total, int) and not isinstance(total, bool) and total > 0 and
                        isinstance(groups, list) and groups and amount.is_finite() and amount >= 0):
                    continue
                grouped = sum(row.get("total_tokens", 0) for row in groups if isinstance(row, dict)
                              and isinstance(row.get("total_tokens"), int) and not isinstance(row.get("total_tokens"), bool))
                peak_missing = any(table.peak_multipliers.get(table.match(model), 1) != 1
                                   for model in cost.get("unsplit_models", []))
                estimates[period] = {"amount_usd": format(amount, "f"),
                    "partial": bool(item.get("status") == "partial" or cost.get("unmatched_models") or
                                    grouped != total or peak_missing)}
            except (TypeError, ValueError, KeyError, InvalidOperation, OverflowError):
                continue
        if estimates:
            compact["history"][name]["estimates"] = estimates
            if "today" in estimates: compact["history"][name]["estimate"] = estimates["today"]
    compact["daily_trend"] = recent_daily_trend(result)
    compact["calendar_report"] = calendar_report(result)
    try:
        compact["local_medals"] = local_medals(result)
    except (TypeError, ValueError, OverflowError, KeyError, AttributeError):
        # 收集册属于附加展示，异常时不应阻断账户和本机用量页面。
        compact["local_medals"] = {"medals": [], "sources": 0, "incomplete": True}
    compact["local_credits"] = {}
    for name, item in result.get("local_credits", {}).items():
        value = item.get("value")
        periods = value.get("periods", {}) if isinstance(value, dict) else {}
        all_totals = periods.get("all", {}).get("totals", {})
        selected = {}
        if all_totals.get("requests", 0) > 0:
            for period in ("today", "7d", "30d", "all"):
                totals = periods.get(period, {}).get("totals", {})
                if isinstance(totals.get("credits"), str):
                    selected[period] = {"totals": {"credits": totals["credits"],
                                                   "billable_credits": totals.get("billable_credits")}}
        status = item.get("status")
        compact["local_credits"][name] = {"status": status if selected or status in {"error", "unavailable", "partial"} else "not_provided",
                                          "reason": item.get("reason") or (None if selected else "history_no_usage_records"),
                                          "value": {"periods": selected} if selected else None}
    return compact


def history_worker(home=None, prices_dir=None):
    """在刷新之间保留内存缓存；源文件变化时失效，不落盘会话或凭据。"""
    records_cache.max_bytes = 128 * 1024 * 1024
    records_cache.max_entries = 50000
    for line in sys.stdin:
        if len(line) > 1024:
            print('{"error":"invalid_request"}', flush=True)
            continue
        try:
            request = json.loads(line.lstrip("\ufeff"))
            if request != {"command": "refresh"}:
                raise ValueError("invalid request")
            result = compact_history(collect(local_only=True, home=home), load_price_table(prices_dir))
            try:
                root = Path(home) if home else Path.home()
                result["activity"] = compact_activity(collect_activity(activity_config(root), now=result["observed_at"]), result["observed_at"])
            except Exception:
                result["activity"] = {"status": "error", "apps": []}
            print(json.dumps(result, ensure_ascii=False, separators=(",", ":")), flush=True)
        except (ValueError, TypeError, KeyError):
            print('{"error":"invalid_request"}', flush=True)
        except Exception:
            # 不返回异常原文、路径、原始数据或凭据。
            print('{"error":"history_scan_failed"}', flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--local-only", action="store_true")
    parser.add_argument("--account-only", action="store_true")
    parser.add_argument("--history-worker", action="store_true")
    parser.add_argument("--forecast-only", action="store_true", help="查询第三方公开重置预测")
    parser.add_argument("--cards-update", action="store_true", help="使用标准输入中的额度更新本地卡册")
    parser.add_argument("--deepseek-only", action="store_true", help="使用标准输入中的密钥查询 DeepSeek 余额")
    parser.add_argument("--zcode-only", action="store_true", help="使用标准输入中的密钥查询 GLM Coding Plan 额度")
    parser.add_argument("--volcengine-only", action="store_true", help="使用标准输入中的 AccessKey 对查询火山方舟 Coding Plan")
    parser.add_argument("--workbuddy-only", action="store_true", help="使用标准输入中的应用专用会话查询 WorkBuddy")
    parser.add_argument("--mimo-only", action="store_true", help="使用标准输入中的应用专用会话查询小米 MiMo")
    parser.add_argument("--activity-only", action="store_true", help="只读取本机活动汇总，不查询账户")
    parser.add_argument("--prices-dir", type=Path, help="本地价格配置目录")
    for provider in ("codex", "kimi", "claude"):
        parser.add_argument("--disable-" + provider + "-account", action="store_true")
    parser.add_argument("--enable-minimax-account", action="store_true")
    parser.add_argument("--account-input", action="store_true")
    parser.add_argument("--home", type=Path, help="Override home for isolated testing")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    if args.activity_only:
        if (args.mimo_only or args.workbuddy_only or args.deepseek_only or args.zcode_only or args.volcengine_only or args.cards_update or args.forecast_only or args.history_worker
                or args.account_only or args.local_only or args.account_input or args.enable_minimax_account
                or any(getattr(args, "disable_" + provider + "_account") for provider in ("codex", "kimi", "claude"))):
            raise SystemExit(2)
        try:
            observed_at = time.time()
            root = args.home if args.home else Path.home()
            result = compact_activity(collect_activity(activity_config(root), now=observed_at), observed_at)
        except Exception:
            # 不输出异常原文或本机路径。
            result = {"status": "error", "apps": [], "sources": {}}
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
        return
    if args.workbuddy_only or args.mimo_only:
        if args.workbuddy_only and args.mimo_only:
            raise SystemExit(2)
        if args.volcengine_only or args.zcode_only or args.deepseek_only or args.cards_update or args.forecast_only or args.history_worker or args.account_only or args.local_only or args.account_input:
            raise SystemExit(2)
        try:
            sys.stdin.reconfigure(encoding="utf-8")
            raw = sys.stdin.read(65537)
            if len(raw) > 65536:
                raise ValueError("session input too large")
            data = json.loads(raw.lstrip("\ufeff"))
            if not isinstance(data, dict) or set(data) != {"session"}:
                raise ValueError("invalid session input")
            session = data["session"]
        except (ValueError, TypeError, RecursionError):
            raise SystemExit(2) from None
        fetch = mimo_account if args.mimo_only else workbuddy_balance
        print(json.dumps(guarded(lambda: fetch(session, time.time())), ensure_ascii=False))
        return
    if args.volcengine_only:
        if args.zcode_only or args.deepseek_only or args.cards_update or args.forecast_only or args.history_worker or args.account_only or args.local_only or args.account_input:
            raise SystemExit(2)
        try:
            sys.stdin.reconfigure(encoding="utf-8")
            raw = sys.stdin.read(65537)
            if len(raw) > 65536: raise ValueError("credential input too large")
            data = json.loads(raw.lstrip("\ufeff"))
            if not isinstance(data, dict) or set(data) != {"credentials"}: raise ValueError("invalid credential input")
            credentials = data["credentials"]
        except (ValueError, TypeError, RecursionError):
            raise SystemExit(2) from None
        print(json.dumps(guarded(lambda: volcengine_quota(credentials, time.time())), ensure_ascii=False))
        return
    if args.deepseek_only or args.zcode_only:
        if args.deepseek_only and args.zcode_only:
            raise SystemExit(2)
        if args.cards_update or args.forecast_only or args.history_worker or args.account_only or args.local_only or args.account_input:
            raise SystemExit(2)
        try:
            sys.stdin.reconfigure(encoding="utf-8")
            raw = sys.stdin.read(65537)
            if len(raw) > 65536:
                raise ValueError("credential input too large")
            data = json.loads(raw.lstrip("\ufeff"))
            if not isinstance(data, dict) or set(data) != {"key"}:
                raise ValueError("invalid credential input")
            key = data["key"]
        except (ValueError, TypeError, RecursionError):
            raise SystemExit(2) from None
        fetch = zcode_quota if args.zcode_only else deepseek_balance
        print(json.dumps(guarded(lambda: fetch(key, time.time())), ensure_ascii=False))
        return
    if args.cards_update:
        if args.forecast_only or args.history_worker or args.account_only or args.local_only or args.account_input:
            raise SystemExit(2)
        local_data = os.environ.get("LOCALAPPDATA")
        if not local_data or not Path(local_data).is_absolute():
            print(json.dumps({"status": "error", "reason": "collection_directory_unavailable", "cards": []}))
            return
        try:
            sys.stdin.reconfigure(encoding="utf-8")
            raw = sys.stdin.read(65537)
            if len(raw) > 65536:
                raise ValueError("account snapshot too large")
            snapshot = json.loads(raw.lstrip("\ufeff"))
            if not isinstance(snapshot, dict) or set(snapshot) != {"account", "other_accounts"}:
                raise ValueError("invalid account snapshot")
        except (ValueError, TypeError, RecursionError):
            raise SystemExit(2) from None
        print(json.dumps(guarded(lambda: update_quota_cards(Path(local_data) / "AgentMeter", snapshot, time.time())), ensure_ascii=False))
        return
    if args.forecast_only:
        if args.history_worker or args.account_only or args.local_only or args.account_input:
            raise SystemExit(2)
        local_data = os.environ.get("LOCALAPPDATA")
        if not local_data or not Path(local_data).is_absolute():
            print(json.dumps({"status": "error", "reason": "forecast_cache_directory_unavailable", "sources": []}))
            return
        print(json.dumps(guarded(lambda: forecast_only(Path(local_data) / "AgentMeter")), ensure_ascii=False))
        return
    if args.history_worker:
        sys.stdin.reconfigure(encoding="utf-8")
        history_worker(args.home, args.prices_dir)
        return
    disabled = frozenset(provider for provider in ("codex", "kimi", "claude")
                         if getattr(args, "disable_" + provider + "_account"))
    saved_accounts = None
    if args.account_input:
        if not args.account_only or not args.enable_minimax_account:
            raise SystemExit(2)
        try:
            sys.stdin.reconfigure(encoding="utf-8")
            raw = sys.stdin.read(65537)
            if len(raw) > 65536:
                raise ValueError("account input too large")
            saved_accounts = validate_account_input(json.loads(raw.lstrip("\ufeff")))
        except (ValueError, TypeError):
            # 不输出输入数据、密钥或异常原文。
            raise SystemExit(2) from None
    print(json.dumps(collect(args.local_only, args.home, args.account_only, disabled, args.enable_minimax_account, saved_accounts), ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
