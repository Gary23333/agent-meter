"""Claude desktop session reuse: claude.ai quota without a browser login.

The desktop app's Chromium cookie jar (~/Library/Application Support/Claude/
Cookies) is decrypted in memory and replayed against the same read-only
usage endpoint as collect_claude_web, whose output contract is reused
verbatim. Chain verified end-to-end on 2026-10-15, see
docs/research/claude-desktop-session-reuse-2026-10-15.md: Keychain
"Claude Safe Storage"/"Claude Key" -> PBKDF2-HMAC-SHA1(value, "saltysalt",
1003, 16) -> AES-128-CBC(IV=16 spaces, blob[3:]); cookie DB version >= 24
prepends sha256(host_key) to the plaintext. Only the full jar plus the real
UA authenticates; sessionKey alone answers 401.

Unlike Qoder, Claude's Electron binary ships the RunAsNode fuse disabled
(verified statically in the fuse wire), so it must never be spawned as a
node runtime — that would launch the app. Decryption runs on plain node
(the zcode_desktop pattern). The real UA is assembled statically from the
bundle: the macOS main session sends Electron's default UA (the app only
alters it for Windows MSIX builds and preview partitions).

The password and cookies travel only over stdin/stdout pipes; nothing is
written to disk, logged, or put into snapshots.
"""
import base64
import json
import os
import plistlib
import re
import sqlite3
import subprocess
from collections import Counter
from pathlib import Path

from .claude_code import collect_claude_web
from .model import SourceError
from .transport import MAX_BODY

APP_PATH = "/Applications/Claude.app"
KEYCHAIN_SERVICE = "Claude Safe Storage"
KEYCHAIN_ACCOUNT = "Claude Key"
SECURITY_ITEM_NOT_FOUND = 44
CHROMIUM_EPOCH = 11644473600  # seconds between 1601-01-01 and 1970-01-01
COOKIE_HOSTS = ("claude.ai", ".claude.ai")
CHROME_VERSION = re.compile(rb"Chrome/(\d+\.\d+\.\d+\.\d+)")
HELPER_REASONS = {"invalid_format": "claude_desktop_helper_failed",
                  "unsupported_format": "claude_desktop_cookies_unsupported",
                  "decrypt_failed": "claude_desktop_decrypt_failed",
                  "helper_protocol": "claude_desktop_helper_failed"}
_BUNDLE_CACHE = {}


def app_bundle(app=APP_PATH):
    """(name, app_version, electron_version, chrome_version), read statically.

    The framework binary is large, so the result is cached until the binary
    changes (an app update moves both mtime and size).
    """
    root = Path(app)
    try:
        info = plistlib.loads((root / "Contents/Info.plist").read_bytes())
    except (OSError, ValueError):
        raise SourceError("claude_desktop_not_installed") from None
    name = info.get("CFBundleName") or info.get("CFBundleExecutable")
    version = info.get("CFBundleShortVersionString")
    if not isinstance(name, str) or not name or not isinstance(version, str) or not version:
        raise SourceError("claude_desktop_not_installed")
    versions = root / "Contents/Frameworks/Electron Framework.framework/Versions"
    for variant in ("A", "Current"):
        binary = versions / variant / "Electron Framework"
        if binary.is_file():
            break
    else:
        raise SourceError("claude_desktop_not_installed")
    try:
        stat = binary.stat()
        key = (stat.st_mtime_ns, stat.st_size)
        cached = _BUNDLE_CACHE.get(str(app))
        if cached and cached[0] == key:
            return cached[1]
        framework = plistlib.loads((binary.parent / "Resources/Info.plist").read_bytes())
        data = binary.read_bytes()
    except (OSError, ValueError):
        raise SourceError("claude_desktop_not_installed") from None
    electron = framework.get("CFBundleVersion") or framework.get("CFBundleShortVersionString")
    found = Counter(CHROME_VERSION.findall(data))
    if not isinstance(electron, str) or not electron or not found:
        raise SourceError("claude_desktop_not_installed")
    bundle = (name, version, electron, found.most_common(1)[0][0].decode("ascii"))
    _BUNDLE_CACHE[str(app)] = (key, bundle)
    return bundle


def user_agent(bundle):
    """Electron's default UA, which the desktop's main session sends."""
    name, version, electron, chrome = bundle
    return ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) %s/%s Chrome/%s Electron/%s Safari/537.36"
            % (name, version, chrome, electron))


def keychain_password(timeout=30, security="/usr/bin/security"):
    """The Safe Storage password; macOS asks the user once for this item.

    The secret only travels over this pipe and is never logged or stored.
    """
    attempts = [[security, "find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", KEYCHAIN_ACCOUNT, "-w"],
                [security, "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"]]
    last = None
    for command in attempts:
        try:
            result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                    stdin=subprocess.DEVNULL, timeout=timeout, check=False)
        except subprocess.TimeoutExpired:
            raise SourceError("claude_desktop_keychain_timeout") from None
        except OSError:
            raise SourceError("claude_desktop_keychain_unavailable") from None
        if result.returncode == 0:
            password = result.stdout.decode("utf-8", "replace").strip()
            if password:
                return password
            last = "claude_desktop_keychain_denied"
            continue
        if result.returncode == SECURITY_ITEM_NOT_FOUND:
            last = "claude_desktop_not_logged_in"
            continue
        raise SourceError("claude_desktop_keychain_denied")
    raise SourceError(last or "claude_desktop_keychain_unavailable")


def cookie_rows(home):
    """(db_version, claude.ai cookie rows) from the Chromium jar, read-only."""
    path = (Path(home) / "Library/Application Support/Claude/Cookies").absolute()
    if not path.is_file():
        raise SourceError("claude_desktop_cookies_missing")
    try:
        db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5)
    except sqlite3.Error:
        raise SourceError("claude_desktop_cookies_unreadable") from None
    try:
        meta = db.execute("SELECT value FROM meta WHERE key='version'").fetchone()
        rows = db.execute("SELECT host_key, name, path, value, encrypted_value, expires_utc "
                          "FROM cookies WHERE host_key IN (?, ?)", COOKIE_HOSTS).fetchall()
    except sqlite3.Error:
        raise SourceError("claude_desktop_cookies_unreadable") from None
    finally:
        db.close()
    try:
        version = int(meta[0]) if meta else 0
    except (TypeError, ValueError):
        version = 0
    return version, [{"host_key": r[0], "name": r[1], "path": r[2] or "/", "value": r[3] or "",
                      "encrypted_value": r[4] or b"", "expires_utc": r[5] or 0} for r in rows]


def _expired(row, now):
    expires = row["expires_utc"]
    return bool(expires) and expires / 1_000_000 - CHROMIUM_EPOCH <= now


def decrypt_session(node_binary, password, rows, db_version, ua, timeout=15):
    """Decrypt the jar through the node helper; credentials stay in memory.

    node_binary must be plain node (or another RunAsNode-enabled runtime),
    never Claude's own executable: its RunAsNode fuse is disabled.
    """
    if not node_binary:
        raise SourceError("claude_desktop_node_missing")
    request = {"password": password, "dbVersion": db_version, "userAgent": ua,
               "cookies": [{"host_key": r["host_key"], "name": r["name"], "value": r["value"],
                            "encrypted_value": base64.b64encode(r["encrypted_value"]).decode("ascii")}
                           for r in rows]}
    script = Path(__file__).parent / "helpers/claude_auth.mjs"
    # A stray NODE_OPTIONS or ELECTRON_RUN_AS_NODE=0 in the parent environment
    # could inject code or change how the runtime starts the script.
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith(("NODE_", "ELECTRON_"))}
    env["ELECTRON_RUN_AS_NODE"] = "1"
    try:
        result = subprocess.run([node_binary, str(script)], input=json.dumps(request).encode("utf-8"),
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                timeout=timeout, env=env, check=False)
    except subprocess.TimeoutExpired:
        raise SourceError("claude_desktop_helper_timeout") from None
    except OSError:
        raise SourceError("claude_desktop_node_missing") from None
    if len(result.stdout) > MAX_BODY:
        raise SourceError("claude_desktop_helper_failed")
    try:
        reply = json.loads(result.stdout.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise SourceError("claude_desktop_helper_failed") from None
    if not isinstance(reply, dict) or not reply.get("ok"):
        reason = reply.get("reason") if isinstance(reply, dict) else None
        raise SourceError(HELPER_REASONS.get(reason, "claude_desktop_helper_failed"))
    cookies, agent = reply.get("cookies"), reply.get("user_agent")
    if not isinstance(cookies, list) or len(cookies) != len(rows) or not isinstance(agent, str) or not agent:
        raise SourceError("claude_desktop_helper_failed")
    pairs = []
    for row, cookie in zip(rows, cookies):
        if (not isinstance(cookie, dict) or cookie.get("name") != row["name"]
                or not isinstance(cookie.get("value"), str)):
            raise SourceError("claude_desktop_helper_failed")
        pairs.append((row["path"], row["name"], cookie["value"]))
    pairs.sort(key=lambda p: len(p[0]), reverse=True)  # browsers send longer paths first
    jar = "; ".join("%s=%s" % (name, value) for _, name, value in pairs)
    if not any(name == "sessionKey" for _, name, _ in pairs):
        raise SourceError("claude_desktop_not_logged_in")
    return {"cookie": jar, "user_agent": agent}


def collect_claude_desktop(home, now, timeout=20, node_binary=None):
    bundle = app_bundle(APP_PATH)
    db_version, rows = cookie_rows(home)
    rows = [r for r in rows if not _expired(r, now)]
    # No sessionKey means no login: fail before asking for the keychain.
    if not any(r["name"] == "sessionKey" for r in rows):
        raise SourceError("claude_desktop_not_logged_in")
    password = keychain_password(timeout=max(timeout, 30))
    session = decrypt_session(node_binary, password, rows, db_version, user_agent(bundle), timeout)
    try:
        out = collect_claude_web(session, now, timeout)
    except SourceError as e:
        if e.code == "not_authenticated":
            raise SourceError("claude_desktop_session_expired") from None
        raise
    out["diagnostics"]["credential_route"] = "desktop_session"
    return out