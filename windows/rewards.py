"""Windows 每日积分领取：复用 agent_meter.rewards 的规则与账本。

macOS 的网站登录由应用内存里的会话提供；Windows 由应用自己的 WebView2
登录窗口在每次调用时交付一次性会话（走 stdin，不落盘、不写日志）。
Qoder 的每日活动只认桌面客户端凭据（macOS 钥匙串 + Electron 解密），
Windows 没有等价实现，因此只报告「暂不支持」，不猜测、不伪造领取。
"""
import os
import re
from pathlib import Path

from agent_meter.model import timestamp
from agent_meter.rewards import (ADAPTERS, CLAIM_TIME, DEFAULT_CLAIM_TIME,
                                 RewardsService, claim_moments, load_ledger, summarize)

# 当前 Windows 能真实读取/领取的提供方。Qoder 与 MiniMax Code 暂不可用。
SUPPORTED = ("trae_cn", "workbuddy")
UNSUPPORTED = (
    {"provider": "qoder", "reason": "qoder_desktop_credentials_macos_only"},
    {"provider": "minimax_code", "reason": "minimax_code_not_supported"},
)
SLOT = re.compile(r"^(trae_cn|workbuddy)(#[2-5])?$")
SESSION_KEYS = {"trae_cn": {"token", "user_agent", "device_id"},
                "workbuddy": {"cookie", "user_agent"}}
MAX_INPUT = 64 * 1024


def runtime_dir(local_app_data=None):
    """LOCALAPPDATA\\AgentMeter；不可用时返回 None（不猜测路径）。"""
    local = local_app_data if local_app_data is not None else os.environ.get("LOCALAPPDATA")
    if not isinstance(local, str) or not local or not Path(local).is_absolute():
        return None
    return Path(local) / "AgentMeter"


def _text(value, low, high):
    return isinstance(value, str) and low <= len(value) <= high and all(0x20 <= ord(c) <= 0x7e for c in value)


def _validate_session(provider, session):
    if not isinstance(session, dict) or set(session) != SESSION_KEYS[provider]:
        raise ValueError("invalid rewards session")
    if provider == "trae_cn":
        if not _text(session["token"], 20, 4096) or not _text(session["user_agent"], 1, 1024):
            raise ValueError("invalid rewards session")
        device = session["device_id"]
        if device is not None and not _text(device, 1, 256):
            raise ValueError("invalid rewards session")
    elif not _text(session["cookie"], 1, 16000) or not _text(session["user_agent"], 1, 1024):
        raise ValueError("invalid rewards session")


def parse_request(data):
    """校验 stdin 输入；只接受本进程需要的字段，不回显内容。"""
    if not isinstance(data, dict) or set(data) - {"sessions", "auto_claim", "claim_time", "claim_all", "only"}:
        raise ValueError("invalid rewards input")
    sessions = data.get("sessions") or {}
    if not isinstance(sessions, dict) or any(provider not in SUPPORTED for provider in sessions):
        raise ValueError("invalid rewards input")
    clean = {}
    for provider, rows in sessions.items():
        if not isinstance(rows, list) or len(rows) > 5:
            raise ValueError("invalid rewards input")
        for row in rows:
            _validate_session(provider, row)
        if rows:
            clean[provider] = rows
    auto = data.get("auto_claim") or []
    if not isinstance(auto, list) or any(provider not in SUPPORTED for provider in auto):
        raise ValueError("invalid rewards input")
    claim_time = data.get("claim_time") or DEFAULT_CLAIM_TIME
    if not isinstance(claim_time, str) or not CLAIM_TIME.match(claim_time):
        raise ValueError("invalid rewards input")
    claim_all = data.get("claim_all") or False
    if not isinstance(claim_all, bool):
        raise ValueError("invalid rewards input")
    only = data.get("only")
    if only is not None and (not isinstance(only, str) or not SLOT.match(only)):
        raise ValueError("invalid rewards input")
    return {"sessions": clean, "auto_claim": sorted(set(auto)), "claim_time": claim_time,
            "claim_all": claim_all, "only": only}


def _claim_meta(summary, auto, claim_time, now):
    today_at, next_at = claim_moments(now, claim_time)
    summary["claim_time"] = claim_time
    summary["next_claim_at"] = timestamp(next_at) if auto else None
    return summary


def ledger_summary(runtime, now, auto_claim, claim_time):
    """只读已保存的领取账本：不发请求、不触发写操作。"""
    ledger = load_ledger(Path(runtime) / "rewards.json")
    summaries, seen = [], set()
    for provider in SUPPORTED:
        slots = [slot for slot, account in ledger["accounts"].items()
                 if isinstance(account, dict) and account.get("provider") == provider]
        for slot in sorted(slots, key=lambda name: (name != provider, name)):
            seen.add(slot)
            account = ledger["accounts"][slot]
            checked = bool(account.get("checked_at"))
            summary = summarize(slot, provider, account, now, provider in auto_claim, None,
                                "available" if checked else "not_connected",
                                None if checked else "not_checked_yet")
            summaries.append(_claim_meta(summary, provider in auto_claim, claim_time, now))
    for provider in SUPPORTED:
        if provider not in seen:
            summary = summarize(provider, provider, {}, now, provider in auto_claim, None,
                                "not_connected", "not_checked_yet")
            summaries.append(_claim_meta(summary, provider in auto_claim, claim_time, now))
    summaries.sort(key=lambda row: (SUPPORTED.index(row["provider"]), row["id"]))
    return {"schema_version": 1, "timezone": "Asia/Shanghai", "accounts": summaries,
            "unsupported": list(UNSUPPORTED), "source": "ledger"}


def claim(runtime, data, now, adapters=None):
    """读取状态并按需领取；规则与 macOS 共用 RewardsService。"""
    adapters = adapters or {provider: ADAPTERS[provider] for provider in SUPPORTED}
    service = RewardsService(runtime, adapters=adapters)
    result = service.tick(data["sessions"], now, auto_claim=set(data["auto_claim"]), disabled=frozenset(),
                          timeout=15, only=data["only"], claim_time=data["claim_time"],
                          claim_all=data["claim_all"])
    for row in result.get("accounts", []):
        _claim_meta(row, row.get("provider") in data["auto_claim"], data["claim_time"], now)
    result["unsupported"] = list(UNSUPPORTED)
    return result


def status(runtime, data, now):
    return ledger_summary(runtime, now, set(data["auto_claim"]), data["claim_time"])
