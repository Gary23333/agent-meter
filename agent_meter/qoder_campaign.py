"""Qoder CN daily campaign credits (100 Credits per round) from the desktop
app's own login.

The campaign list and the claim live behind ``openapi.qoder.com.cn`` and want
the desktop client's token, not the website cookie the account card uses: the
campaign service only issues campaigns to requests that identify the app.

macOS keeps that token in
``~/Library/Application Support/com.qodercn.app*/auth.v1.dat``: a "v10"
Chromium envelope (AES-128-CBC, key = PBKDF2-HMAC-SHA1(keychain password,
"saltysalt", 1003 rounds, 16 bytes), IV = 16 spaces). The standard library
has no AES, so the client's own Electron runtime decrypts it in memory: the
keychain password goes in over stdin and the token comes back over stdout, so
neither ever touches disk or a log. The token stays in memory only and is
re-read from the file when it expires.

The endpoint contract follows the public open-source implementation
(88lin/workbuddy-auto-signin, ``qoder_signin.py``) and the official event
page (docs.qoder.com/zh/events/100credits: 100 Credits per round, claimed in
the desktop app, missed rounds do not accumulate). Both were re-verified on
this machine on 2026-11-10 — see
docs/research/qoder-campaigns-recon-2026-11-10.md.
"""
import json
import os
import plistlib
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .model import SourceError, number
from .transport import MAX_BODY, build_opener, clean_headers

CAMPAIGN_BASE = "https://openapi.qoder.com.cn"
CAMPAIGNS_PATH = "/sash/api/v1/me/campaigns"
CLAIM_PATH = "/sash/api/v1/me/campaigns/%s/claim"
# Without this client type the service answers with an empty campaign list.
CLIENT_TYPE = "10"
KEYCHAIN_SERVICE = "Qoder CN App Safe Storage"
KEYCHAIN_ACCOUNT = "Qoder CN App Key"
AUTH_DIR_GLOB = "com.qodercn.app*"
AUTH_FILE = "auth.v1.dat"
MACHINE_ID_FILE = "auth.machine-id"
SECURITY_ITEM_NOT_FOUND = 44
TOKEN_TTL = 300        # seconds; keeps the keychain prompt to one per backend run
RISK_TTL = 1800        # seconds; the device identity is stable
USER_AGENT = "Qoder/claim"

_TOKEN_CACHE = {}
_RISK_CACHE = {}

CN = timezone(timedelta(hours=8))
AUTH_REASONS = {"auth_missing": "qoder_desktop_not_logged_in",
                "unsupported_format": "qoder_desktop_auth_unsupported",
                "decrypt_failed": "qoder_desktop_auth_failed",
                "token_missing": "qoder_desktop_not_logged_in",
                "invalid_format": "qoder_desktop_auth_failed",
                "helper_protocol": "qoder_desktop_auth_failed"}


# --- desktop credentials ----------------------------------------------------

def auth_dirs(home=None):
    """Installed Qoder CN profile directories, newest first."""
    base = Path(home or Path.home()) / "Library" / "Application Support"
    try:
        found = list(base.glob(AUTH_DIR_GLOB))
    except OSError:
        return []
    dated = []
    for path in found:
        if not (path / AUTH_FILE).is_file():
            continue
        try:
            dated.append((path.stat().st_mtime, path))
        except OSError:
            dated.append((0, path))
    return [path for _, path in sorted(dated, key=lambda row: row[0], reverse=True)]


def keychain_password(timeout=10, security="/usr/bin/security"):
    """The Safe Storage password that protects the credential file.

    macOS asks the user once for this item; the secret only travels over this
    pipe and is never logged or stored.
    """
    attempts = [[security, "find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", KEYCHAIN_ACCOUNT, "-w"],
                [security, "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"]]
    last = None
    for command in attempts:
        try:
            result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                    stdin=subprocess.DEVNULL, timeout=timeout, check=False)
        except subprocess.TimeoutExpired:
            raise SourceError("qoder_keychain_timeout") from None
        except OSError:
            raise SourceError("qoder_keychain_unavailable") from None
        if result.returncode == 0:
            password = result.stdout.decode("utf-8", "replace").strip()
            if password:
                return password
            last = "qoder_keychain_denied"
            continue
        if result.returncode == SECURITY_ITEM_NOT_FOUND:
            # A missing item means the desktop app never stored a login here.
            last = "qoder_desktop_not_logged_in"
            continue
        raise SourceError("qoder_keychain_denied")
    raise SourceError(last or "qoder_keychain_unavailable")


def app_executable(app):
    try:
        info = plistlib.loads((Path(app) / "Contents/Info.plist").read_bytes())
    except (OSError, ValueError):
        raise SourceError("qoder_desktop_not_installed") from None
    name = info.get("CFBundleExecutable")
    if not isinstance(name, str) or not name:
        raise SourceError("qoder_desktop_not_installed")
    return Path(app) / "Contents/MacOS" / name


def decrypt_token(app, directory, password, timeout=15):
    """Read the token out of the desktop credential file, in memory only."""
    executable = app_executable(app)
    script = Path(__file__).parent / "helpers/qoder_auth.mjs"
    request = {"password": password, "authFile": str(Path(directory) / AUTH_FILE)}
    # A stray ELECTRON_RUN_AS_NODE=0 in the environment would stop the client
    # from running as plain node, so the child gets a clean slate.
    env = {k: v for k, v in os.environ.items()
           if not k.upper().startswith(("NODE_", "ELECTRON_", "QODER_"))}
    env["ELECTRON_RUN_AS_NODE"] = "1"
    try:
        result = subprocess.run([str(executable), str(script)],
                                input=json.dumps(request).encode("utf-8"),
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                timeout=timeout, env=env, check=False)
    except subprocess.TimeoutExpired:
        raise SourceError("qoder_desktop_auth_timeout") from None
    except OSError:
        raise SourceError("qoder_desktop_not_installed") from None
    try:
        reply = json.loads(result.stdout.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise SourceError("qoder_desktop_auth_unreadable") from None
    if not isinstance(reply, dict) or not reply.get("ok"):
        reason = reply.get("reason") if isinstance(reply, dict) else None
        raise SourceError(AUTH_REASONS.get(reason, "qoder_desktop_auth_failed"))
    session = reply.get("session")
    token = session.get("token") if isinstance(session, dict) else None
    if not isinstance(token, str) or not token:
        raise SourceError("qoder_desktop_not_logged_in")
    return token


def desktop_token(session, timeout=15):
    """The desktop client's bearer token, cached briefly to spare the keychain."""
    app = session.get("desktop_app")
    if not app:
        raise SourceError("qoder_desktop_not_installed")
    directory = session.get("auth_dir")
    if not directory:
        found = auth_dirs()
        if not found:
            raise SourceError("qoder_desktop_not_installed")
        directory = found[0]
    key = str(directory)
    cached = _TOKEN_CACHE.get(key)
    if cached and cached[1] > time.time():
        return cached[0]
    token = decrypt_token(app, directory, keychain_password(timeout=timeout), timeout)
    _TOKEN_CACHE[key] = (token, time.time() + TOKEN_TTL)
    return token


# --- device identity ---------------------------------------------------------

def _manifest_version(app):
    try:
        manifest = json.loads((Path(app) / "Contents/Resources/build-manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    version = manifest.get("productVersion") if isinstance(manifest, dict) else None
    return str(version) if version else None


def _machine_id(directory):
    try:
        value = (Path(directory) / MACHINE_ID_FILE).read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value or None


def _run_umid(app, timeout=10):
    """The client's own machine identity helper; absent on some installs."""
    executable = Path(app) / "Contents/Resources/umid/runtime-info"
    if not executable.is_file():
        return {}
    try:
        result = subprocess.run([str(executable), "--account-stdin"], input=b"",
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError):
        return {}
    for line in reversed(result.stdout.decode("utf-8", "replace").splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except ValueError:
            continue
        return data if isinstance(data, dict) else {}
    return {}


def risk_headers(app, directory, timeout=10):
    """Best-effort device headers.

    The service hands out campaigns more readily when the request identifies
    the machine; every part of it is optional, so a missing piece just means a
    plainer request.
    """
    key = str(directory)
    cached = _RISK_CACHE.get(key)
    if cached and cached[1] > time.time():
        return dict(cached[0])
    headers = {}
    version = _manifest_version(app)
    if version:
        headers["Cosy-Version"] = version
    machine_id = _machine_id(directory)
    if machine_id:
        headers["Cosy-MachineId"] = machine_id
    identity = _run_umid(app, timeout)
    for source, target in (("machineToken", "Cosy-MachineToken"),
                           ("machineCode", "Cosy-MachineCode"),
                           ("machineType", "Cosy-MachineType")):
        value = identity.get(source)
        if isinstance(value, str) and value:
            headers[target] = value
    _RISK_CACHE[key] = (dict(headers), time.time() + RISK_TTL)
    return headers


# --- campaign service --------------------------------------------------------

def _api(path, token, headers, timeout, method="GET"):
    url = CAMPAIGN_BASE + path
    opener = build_opener(url)
    request_headers = clean_headers(headers)
    request_headers.setdefault("Accept", "application/json")
    request_headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request(url, method=method, headers=request_headers,
                                     data=b"" if method == "POST" else None)
    try:
        with opener.open(request, timeout=timeout) as response:
            status = response.status
            raw = response.read(MAX_BODY + 1)
    except urllib.error.HTTPError as error:
        if error.code == 401:
            raise SourceError("qoder_campaigns_unauthorized")
        if error.code == 403:
            raise SourceError("qoder_campaigns_forbidden")
        raise SourceError("qoder_campaigns_http_" + str(error.code)) from None
    except (urllib.error.URLError, OSError):
        raise SourceError("qoder_campaigns_unreachable") from None
    if len(raw) > MAX_BODY:
        raise SourceError("response_too_large")
    try:
        return status, json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise SourceError("invalid_json")


def _amount(source):
    benefit = source.get("benefit") if isinstance(source, dict) else None
    if isinstance(benefit, dict):
        amount = number(benefit.get("amount"), optional=True)
        if amount is not None:
            return amount
    return None


def _within_window(campaign, now):
    start = campaign.get("startAt")
    end = campaign.get("endAt")
    if isinstance(start, (int, float)) and not isinstance(start, bool) and now < start:
        return False
    if isinstance(end, (int, float)) and not isinstance(end, bool) and now >= end:
        return False
    return True


def _daily_refresh(rows):
    """When the daily campaign appears, as Beijing time (the service posts it
    at 10:00 and the window is short)."""
    starts = [row.get("start_at") for row in rows if isinstance(row.get("start_at"), (int, float))]
    if not starts:
        return None
    moment = datetime.fromtimestamp(min(starts), CN).strftime("%H:%M")
    return moment


def normalize_campaigns(payload, now=None):
    """Split the campaign list into claimable, claimed and other benefit rows."""
    if not isinstance(payload, dict):
        raise SourceError("unsupported_qoder_campaign_contract")
    rows = payload.get("campaigns")
    if not isinstance(rows, list):
        raise SourceError("unsupported_qoder_campaign_contract")
    now = time.time() if now is None else float(now)
    campaigns, claimable = [], []
    for row in rows:
        if not isinstance(row, dict) or row.get("actionType") != "CLAIM_BENEFIT":
            continue
        campaign_id = row.get("campaignId")
        if not isinstance(campaign_id, str) or not campaign_id:
            continue
        amount = _amount(row)
        title = row.get("campaignKey") if isinstance(row.get("campaignKey"), str) else None
        status = row.get("claimStatus") if isinstance(row.get("claimStatus"), str) else None
        active = _within_window(row, now)
        start = row.get("startAt")
        end = row.get("endAt")
        campaigns.append({"campaign_id": campaign_id, "title": title or "每日积分",
                          "credits": amount, "status": status, "active": active,
                          "start_at": int(start) if isinstance(start, (int, float)) and not isinstance(start, bool) else None,
                          "end_at": int(end) if isinstance(end, (int, float)) and not isinstance(end, bool) else None})
        if status == "CLAIMABLE" and active:
            claimable.append({"item": "campaign:" + campaign_id,
                              "title": title or "每日积分", "credits": amount})
    return {"kind": "campaign", "enabled": True, "signed_in": None,
            "campaigns": campaigns, "claimable": claimable,
            "daily_refresh": _daily_refresh(campaigns)}


def normalize_campaign_claim(payload, http_status=200, fallback=None):
    """Map the claim response to the shared reward result shape.

    The service answers with a flat body (status, replayed, benefit) and no
    code field, so the HTTP status is what decides success.
    """
    if not isinstance(payload, dict):
        raise SourceError("qoder_campaign_claim_failed")
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    status = data.get("status") if isinstance(data, dict) else None
    if http_status == 200 and isinstance(data, dict) and status == "CLAIMED":
        result = {"result": "ok", "credits": _amount(data)}
        if result["credits"] is None:
            result["credits"] = _amount(fallback) if isinstance(fallback, dict) else None
        if data.get("replayed"):
            # The grant already existed (a repeat call); the credits are still
            # the day's credits, so they are counted once.
            result["replayed"] = True
        return result
    return {"result": "rejected", "code": payload.get("code"), "status": status}


def _session_for(session):
    app = session.get("desktop_app")
    if not app:
        raise SourceError("qoder_desktop_not_installed")
    directory = session.get("auth_dir")
    if not directory:
        found = auth_dirs()
        if not found:
            raise SourceError("qoder_desktop_not_installed")
        directory = found[0]
    return app, directory


def _headers(session, token, timeout):
    app, directory = _session_for(session)
    headers = {"User-Agent": USER_AGENT, "Cosy-ClientType": CLIENT_TYPE}
    headers.update(risk_headers(app, directory, timeout))
    return headers


def qoder_campaigns_status(session, timeout=15):
    token = desktop_token(session, timeout)
    _, payload = _api(CAMPAIGNS_PATH, token, _headers(session, token, timeout), timeout)
    return normalize_campaigns(payload)


def qoder_campaigns_claim(session, item, timeout=15):
    if not isinstance(item, str) or not item.startswith("campaign:"):
        raise SourceError("unknown_reward_item")
    campaign_id = item.split(":", 1)[1]
    if not campaign_id or len(campaign_id) > 128:
        raise SourceError("unknown_reward_item")
    token = desktop_token(session, timeout)
    status, payload = _api(CLAIM_PATH % campaign_id, token, _headers(session, token, timeout), timeout,
                           method="POST")
    return normalize_campaign_claim(payload, http_status=status)
