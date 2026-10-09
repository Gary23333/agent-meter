"""Claude Code subscription windows through its own OAuth login, read-only.

The access token comes from Claude Code's Keychain item (or the Linux-style
~/.claude/.credentials.json) and is used only in memory. It is never
refreshed here: refreshing would rotate Claude Code's own login. An expired
token is reported as not connected until Claude Code itself renews it.
Contract follows CodexBar b0aa7fe ClaudeOAuthUsageFetcher (MIT).
"""
import json
import re
import subprocess
from pathlib import Path

from .model import SourceError, account_key, metric, number, source, timestamp
from .transport import MAX_BODY, get_json

KEYCHAIN_SERVICE = "Claude Code-credentials"
USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
WEB_API = "https://claude.ai/api"
ORG_ID = re.compile(r"^[0-9a-fA-F-]{8,64}$")
# Window keys in the usage response and their lengths in minutes.
WINDOWS = [("five_hour", 300), ("seven_day", 10080), ("seven_day_opus", 10080),
           ("seven_day_sonnet", 10080), ("seven_day_oauth_apps", 10080)]
SECURITY_ITEM_NOT_FOUND = 44


def read_credentials(home, timeout, security="/usr/bin/security"):
    path = Path(home) / ".claude/.credentials.json"
    if path.is_file():
        if path.stat().st_size > MAX_BODY:
            raise SourceError("invalid_claude_credentials")
        raw = path.read_bytes()
    else:
        try:
            # macOS asks the user once; the secret only travels over this pipe.
            result = subprocess.run([security, "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],
                                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                    stdin=subprocess.DEVNULL, timeout=timeout, check=False)
        except subprocess.TimeoutExpired:
            raise SourceError("claude_keychain_timeout") from None
        except OSError:
            raise SourceError("claude_keychain_unavailable") from None
        if result.returncode == SECURITY_ITEM_NOT_FOUND:
            # No claude.ai login: e.g. Claude Code runs on API keys / CC Switch providers.
            raise SourceError("claude_subscription_login_missing")
        if result.returncode:
            raise SourceError("claude_keychain_denied")
        raw = result.stdout
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise SourceError("invalid_claude_credentials") from None
    oauth = data.get("claudeAiOauth") if isinstance(data, dict) else None
    if not isinstance(oauth, dict) or not isinstance(oauth.get("accessToken"), str) or not oauth["accessToken"]:
        raise SourceError("claude_not_logged_in")
    return oauth


def normalize_claude(payload, oauth, now):
    if not isinstance(payload, dict):
        raise SourceError("unsupported_claude_usage_contract")
    out = source("claude", "account", now)
    quotas, resets = [], []
    for key, minutes in WINDOWS:
        window = payload.get(key)
        if window is None:
            continue
        if not isinstance(window, dict):
            raise SourceError("invalid_claude_window")
        if window.get("utilization") is None:
            continue
        used = number(window["utilization"])
        reset = timestamp(window["resets_at"]) if window.get("resets_at") else None
        quotas.append({"bucket": key, "used_percent": used, "remaining_percent": max(0, 100 - used),
                       "window_minutes": minutes, "resets_at": reset})
        if reset is not None:
            resets.append({"bucket": key, "resets_at": reset})
    if not quotas:
        raise SourceError("claude_usage_windows_missing")
    out["metrics"]["quota"] = metric(quotas)
    out["metrics"]["reset_time"] = metric(resets or None)
    plan = oauth.get("subscriptionType")
    if isinstance(plan, str) and len(plan) < 40:
        out["subscription"] = {"plan": plan}
    extra = payload.get("extra_usage")
    # Units of extra-usage credits are not established; expose only the switch.
    out["diagnostics"]["extra_usage_enabled"] = extra.get("is_enabled") if isinstance(extra, dict) else None
    out["diagnostics"]["transport"] = "claude_code_oauth_usage"
    return out


def collect_claude(home, now, timeout=20):
    oauth = read_credentials(home, max(timeout, 30))
    expires = oauth.get("expiresAt")
    if isinstance(expires, (int, float)) and not isinstance(expires, bool) and expires / 1000 <= now:
        raise SourceError("claude_token_expired")
    payload = get_json(USAGE_URL, oauth["accessToken"], timeout,
                       headers={"anthropic-beta": "oauth-2025-04-20", "User-Agent": "claude-code/2.1.0"})
    return normalize_claude(payload, oauth, now)


def pick_organization(orgs):
    """Personal chat organization first, as the claude.ai app does."""
    if not isinstance(orgs, list):
        raise SourceError("unsupported_claude_web_contract")
    valid = [o for o in orgs if isinstance(o, dict) and isinstance(o.get("uuid"), str) and ORG_ID.match(o["uuid"])]
    caps = lambda o: {str(c).lower() for c in o.get("capabilities") or [] if isinstance(c, str)}
    chosen = (next((o for o in valid if "chat" in caps(o)), None)
              or next((o for o in valid if caps(o) != {"api"}), None))
    if chosen is None:
        raise SourceError("claude_web_no_organization")
    return chosen


def collect_claude_web(session, now, timeout=20):
    """claude.ai website login (the same account the Claude desktop app uses)."""
    cookie = (session or {}).get("cookie")
    if not cookie or "sessionKey=" not in cookie:
        raise SourceError("web_session_missing")
    headers = {"Cookie": cookie, "User-Agent": session.get("user_agent") or "Mozilla/5.0",
               "Referer": "https://claude.ai/settings/usage"}
    org = pick_organization(get_json(WEB_API + "/organizations", timeout=timeout, headers=headers))
    payload = get_json(WEB_API + "/organizations/" + org["uuid"] + "/usage", timeout=timeout, headers=headers)
    out = normalize_claude(payload, {}, now)
    out["account_key"] = account_key("claude", org["uuid"])
    out["diagnostics"]["transport"] = "claude_ai_web_session"
    return out
