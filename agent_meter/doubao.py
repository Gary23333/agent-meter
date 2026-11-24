"""豆包（Doubao）会员额度：网页登录 Cookie 只读查询。

两条接口都只读：额度汇总（quota/summary）与额度余额（quota_balance/detail）。
Cookie 来自 App 登录窗口（内存）或本机豆包客户端的 Chromium Cookie 库
（经 node 在内存里解密），都不落盘、不写日志。

该账号只返回月窗口，所以没有 start_time 时不猜测 5 小时 / 7 天；
也不输出 tokens 指标——豆包不按 token 计量。
"""
import base64
import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

from .sqlite_ro import readonly_uri
from .model import DISPLAY_ZONE, SourceError, account_key, decimal_string, metric, source, timestamp
from .transport import MAX_BODY, post_json

BASE = "https://www.doubao.com"
SUMMARY_PATH = "/alice/commerce/sale/subscription/quota/summary/"
BALANCE_PATH = "/alice/commerce/sale/subscription/quota_balance/detail/"
PRODUCT_LINE = "membership"
# 豆包 Web 的公共查询参数；缺了 aid 会退到未登录产品线（general 0%）。
QUERY = {"aid": "582478"}
QUOTA_PAGE = BASE + "/member/quota-management"
SAFARI_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
             "(KHTML, like Gecko) Version/18.0 Safari/605.1.15")
# 豆包客户端的 Safe Storage 条目名还没稳定，按可能性依次尝试。
KEYCHAIN_SERVICES = ("Doubao Safe Storage", "Doubao Browser Safe Storage", "Chrome Safe Storage")
SECURITY_ITEM_NOT_FOUND = 44
HELPER_REASONS = {"no_cookies": "doubao_app_cookies_not_found",
                  "decrypt_failed": "unsupported_doubao_cookie_format",
                  "unsupported_format": "unsupported_doubao_cookie_format",
                  "invalid_format": "doubao_app_cookies_unreadable",
                  "helper_protocol": "doubao_app_cookies_unreadable"}


def _headers(session):
    return {"Cookie": session["cookie"], "Content-Type": "application/json",
            "Agw-Js-Conv": "str", "Origin": BASE, "Referer": QUOTA_PAGE,
            "User-Agent": session.get("user_agent") or SAFARI_UA,
            "Accept": "application/json, text/plain, */*"}


def _data(payload):
    """{code: 0, data: {...}} 统一信封。"""
    if not isinstance(payload, dict):
        raise SourceError("unsupported_doubao_contract")
    if payload.get("code") not in (0, "0"):
        raise SourceError("doubao_quota_unavailable")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise SourceError("unsupported_doubao_contract")
    return data


def _amount(raw):
    if raw in (None, ""):
        return None
    if isinstance(raw, str):
        # 服务端金额带千分位（"18,000"），先去掉分隔符再按 Decimal 解析。
        raw = raw.replace(",", "").strip()
    try:
        return decimal_string(raw, allow_negative=True)
    except SourceError:
        raise SourceError("unsupported_doubao_contract") from None


def _percent(raw):
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value != value or value < 0:
        return None
    return min(100.0, value)


def _millis(raw):
    """时间戳可能是数字、数字字符串或 ISO；0 表示「还没有重置时间」。"""
    if raw in (None, "", 0, "0"):
        return None
    if isinstance(raw, bool):
        raise SourceError("unsupported_doubao_contract")
    if isinstance(raw, str) and raw.strip().lstrip("-").isdigit():
        raw = int(raw.strip())
    try:
        if isinstance(raw, (int, float)):
            if raw <= 0:
                return None
            return timestamp(raw, unit="milliseconds" if raw > 2e10 else "seconds")
        return timestamp(raw)
    except SourceError:
        raise SourceError("unsupported_doubao_contract") from None


def _epoch_millis(raw):
    if isinstance(raw, bool):
        return None
    if isinstance(raw, str) and raw.strip().isdigit():
        raw = int(raw.strip())
    if isinstance(raw, (int, float)) and raw > 0:
        return float(raw)
    return None


def _window_minutes(start, end):
    """只有明确给出了正起点才计算窗口长度。"""
    start, end = _epoch_millis(start), _epoch_millis(end)
    if start is None or end is None or start <= 0 or end <= start:
        return None
    return int((end - start) / 60000)


def _subscription(data):
    sub = data.get("current_subscription")
    if not isinstance(sub, dict):
        return None
    display = sub.get("display") if isinstance(sub.get("display"), dict) else {}
    plan = next((display[k].strip() for k in ("name", "title", "plan_name", "product_name")
                 if isinstance(display.get(k), str) and display[k].strip()), None)
    merchant = sub.get("merchant_user_id")
    end = _millis(sub.get("end_time"))
    return {"merchant_user_id": merchant if isinstance(merchant, str) and merchant else None,
            "plan": plan or "豆包订阅",
            "ends_on": datetime.fromtimestamp(end["epoch_seconds"], DISPLAY_ZONE).date().isoformat()
                       if end else None}


def _window_groups(data):
    """个人额度优先；没有个人窗口时退回企业窗口。"""
    for name in ("window_limit_section", "enterprise_window_limit_section"):
        section = data.get(name)
        if isinstance(section, dict):
            groups = section.get("window_limit_groups")
            if isinstance(groups, list) and groups:
                return groups, name
    # 两个 section 都存在但都是空列表：这是「没有窗口」，不是契约损坏。
    for name in ("window_limit_section", "enterprise_window_limit_section"):
        section = data.get(name)
        if isinstance(section, dict) and isinstance(section.get("window_limit_groups"), list):
            return [], name
    return None, None


def normalize_summary(payload):
    """额度汇总 → {rows, resets, subscription, section}。"""
    data = _data(payload)
    member = data.get("member_info")
    if isinstance(member, dict):
        # 个人 / 企业 / 团队 / 工作订阅任一存在都算有效；全为 false 才是无订阅。
        flags = [member.get(k) for k in ("hasActiveSubscription", "hasEnterpriseSubscription",
                                          "has_business_subscription", "has_team_subscription")]
        if not any(flag is True for flag in flags) and any(flag is False for flag in flags):
            raise SourceError("doubao_no_active_subscription")
    groups, section_name = _window_groups(data)
    if groups is None:
        raise SourceError("unsupported_doubao_contract")
    rows, resets = [], []
    for group in groups:
        limits = group.get("window_limits") if isinstance(group, dict) else None
        if not isinstance(limits, list):
            raise SourceError("unsupported_doubao_contract")
        group_bucket = None
        if isinstance(group, dict):
            group_bucket = group.get("feature_group") or group.get("feature_group_name")
        for limit in limits:
            if not isinstance(limit, dict):
                raise SourceError("unsupported_doubao_contract")
            total, used = _amount(limit.get("total_amount")), _amount(limit.get("used_amount"))
            used_percent = _percent(limit.get("used_percent"))
            if used_percent is None and total is not None and used is not None:
                try:
                    if float(total) > 0:
                        used_percent = min(100.0, max(0.0, float(used) / float(total) * 100))
                except ValueError:
                    used_percent = None
            if used_percent is None:
                continue
            bucket = limit.get("feature_group") or group_bucket
            bucket = bucket.strip() if isinstance(bucket, str) and bucket.strip() else "doubao_quota"
            reset = _millis(limit.get("end_time"))
            row = {"bucket": bucket, "used_percent": used_percent,
                   "remaining_percent": 100 - used_percent, "unit": "doubao_points",
                   "resets_at": reset}
            if used is not None:
                row["used"] = used
            if total is not None:
                row["limit"] = total
            if isinstance(limit.get("less_than_one_percent"), bool):
                row["less_than_one_percent"] = limit["less_than_one_percent"]
            minutes = _window_minutes(limit.get("start_time"), limit.get("end_time"))
            if minutes is not None:
                row["window_minutes"] = minutes
            rows.append(row)
            if reset:
                resets.append({"bucket": bucket, "resets_at": reset})
    return {"rows": rows, "resets": resets, "subscription": _subscription(data),
            "section": section_name}


def normalize_balance(payload):
    """余额明细 → credits 行；优先按 summaries 分桶，否则退回总额。"""
    data = _data(payload)
    rows = []
    summaries = data.get("summaries")
    if isinstance(summaries, list):
        for item in summaries:
            if not isinstance(item, dict):
                continue
            balance = _amount(item.get("remaining_amount"))
            if balance is None:
                continue
            bucket = next((item[k].strip() for k in ("title", "category")
                           if isinstance(item.get(k), str) and item[k].strip()), "doubao")
            rows.append({"bucket": bucket, "unit": "doubao_points", "balance": balance})
    if not rows:
        total = _amount(data.get("total_remaining_amount"))
        if total is not None:
            rows.append({"bucket": "doubao", "unit": "doubao_points", "balance": total})
    return rows


def collect_doubao(session, now, timeout=15):
    session = session or {}
    if not session.get("cookie"):
        raise SourceError("doubao_credential_not_connected")
    headers = _headers(session)

    def query(path):
        try:
            return post_json(BASE + path + "?" + urlencode(QUERY), {"product_line": PRODUCT_LINE},
                             timeout=timeout, headers=headers)
        except SourceError as e:
            # 登录过期通常表现为 401/403 或跳转登录页。
            raise SourceError("doubao_not_authenticated"
                              if e.code in ("not_authenticated", "redirect_rejected") else e.code) from None

    parsed = normalize_summary(query(SUMMARY_PATH))
    out = source("doubao", "account", now)
    info = parsed["subscription"] or {}
    out["account_key"] = account_key("doubao", info.get("merchant_user_id"))
    out["metrics"]["quota"] = metric(parsed["rows"] or None,
                                     reason=None if parsed["rows"] else "doubao_no_quota_windows")
    out["metrics"]["reset_time"] = metric(parsed["resets"] or None)
    out["subscription"] = {"plan": info.get("plan") or "豆包订阅"}
    if info.get("ends_on"):
        out["subscription"]["ends_on"] = info["ends_on"]
    out["diagnostics"]["transport"] = "doubao_web_session"
    out["diagnostics"]["product_line"] = PRODUCT_LINE
    if parsed.get("section"):
        out["diagnostics"]["window_section"] = parsed["section"]
    try:
        balance_rows = normalize_balance(query(BALANCE_PATH))
        out["metrics"]["credits"] = metric(balance_rows or None,
                                           reason=None if balance_rows else "doubao_no_balance_rows")
    except SourceError as e:
        if e.code == "doubao_not_authenticated":
            raise
        # 余额失败不影响已经拿到的额度。
        out["metrics"]["credits"] = metric(status="error", reason=e.code)
    return out


def _read_cookie_rows(db_path):
    db = sqlite3.connect(readonly_uri(db_path), uri=True, timeout=5)
    try:
        rows = db.execute("SELECT host_key, name, encrypted_value, expires_utc FROM cookies "
                          "WHERE host_key LIKE '%doubao.com' AND name <> ''").fetchall()
    finally:
        db.close()
    return [{"host": row[0] or "", "name": row[1] or "",
             "value": base64.b64encode(row[2] or b"").decode("ascii"),
             "expires_utc": row[3] or 0} for row in rows]


def _cookie_rows(path):
    try:
        return _read_cookie_rows(path)
    except sqlite3.Error:
        # 豆包运行时可能独占数据库；复制一份只读副本再读，读完立即删除。
        temp = None
        try:
            with tempfile.NamedTemporaryFile(prefix="doubao-cookies-", suffix=".db",
                                             delete=False) as handle:
                temp = Path(handle.name)
            shutil.copy2(path, temp)
            for suffix in ("-wal", "-shm"):
                source = path.with_name(path.name + suffix)
                if source.exists():
                    shutil.copy2(source, temp.with_name(temp.name + suffix))
            return _read_cookie_rows(temp)
        except (OSError, sqlite3.Error):
            raise SourceError("doubao_app_cookies_unreadable") from None
        finally:
            if temp is not None:
                for suffix in ("", "-wal", "-shm"):
                    try:
                        temp.with_name(temp.name + suffix).unlink()
                    except OSError:
                        pass


def _keychain_password(timeout=30, security="/usr/bin/security"):
    for service in KEYCHAIN_SERVICES:
        try:
            result = subprocess.run([security, "find-generic-password", "-s", service, "-w"],
                                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                    stdin=subprocess.DEVNULL, timeout=timeout, check=False)
        except (subprocess.TimeoutExpired, OSError):
            raise SourceError("doubao_keychain_denied") from None
        if result.returncode == 0:
            password = result.stdout.decode("utf-8", "replace").strip()
            if password:
                return password
        elif result.returncode != SECURITY_ITEM_NOT_FOUND:
            raise SourceError("doubao_keychain_denied")
    raise SourceError("doubao_keychain_denied")


def _decrypt_cookies(node, password, rows, timeout=15):
    script = Path(__file__).parent / "helpers/doubao_cookies.mjs"
    # 父环境里的 NODE_OPTIONS 等会改变运行时行为，先剔除。
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith(("NODE_", "ELECTRON_"))}
    env["ELECTRON_RUN_AS_NODE"] = "1"
    try:
        result = subprocess.run([node, str(script)],
                                input=json.dumps({"password": password, "cookies": rows}).encode("utf-8"),
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                timeout=timeout, env=env, check=False)
    except subprocess.TimeoutExpired:
        raise SourceError("doubao_app_cookies_unreadable") from None
    except OSError:
        raise SourceError("doubao_node_missing") from None
    if len(result.stdout) > MAX_BODY:
        raise SourceError("doubao_app_cookies_unreadable")
    try:
        reply = json.loads(result.stdout.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise SourceError("doubao_app_cookies_unreadable") from None
    if not isinstance(reply, dict) or not reply.get("ok"):
        reason = reply.get("reason") if isinstance(reply, dict) else None
        raise SourceError(HELPER_REASONS.get(reason, "doubao_app_cookies_unreadable"))
    cookie = reply.get("cookie")
    if not isinstance(cookie, str) or not cookie or len(cookie) > 16 * 1024:
        raise SourceError("doubao_app_cookies_unreadable")
    return cookie


def import_doubao_app_cookies(config):
    """读取豆包客户端自己的 Chromium Cookie 库，返回 Cookie 头。"""
    home = (config or {}).get("home") or str(Path.home())
    path = Path(home) / "Library/Application Support/Doubao/Default/Cookies"
    if not path.is_file():
        raise SourceError("doubao_app_cookies_not_found")
    rows = _cookie_rows(path)
    if not rows:
        raise SourceError("doubao_app_cookies_not_found")
    node = (config or {}).get("node_binary") or shutil.which("node")
    if not node:
        raise SourceError("doubao_node_missing")
    password = _keychain_password()
    return _decrypt_cookies(node, password, rows)
