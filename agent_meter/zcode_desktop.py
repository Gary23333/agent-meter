"""ZCode desktop login: reset cards and quota from the app's own credential
store (read-only). ~/.zcode/v2/credentials.json keeps enc:v1 envelopes:
base64url(iv).base64url(tag).base64url(ciphertext), AES-256-GCM under
SHA-256(secret); secret is ZCODE_CREDENTIAL_SECRET or the machine-local
fallback "zcode-credential-fallback:<platform>:<home>:<username>" (contract
verified against UsageBar-tauri 2605fd5 and token-monitor c62544e, the same
references as the 2026-10-09 live probe).

Decryption needs AES, which the stdlib does not provide, so a node helper
does it in memory: envelopes and secret go in through stdin, plaintext
comes back through stdout, nothing touches disk or logs. The reset query
is a read, never a redemption; the full card list is kept (the reference
implementation's six-card truncation is deliberately not copied).
"""
import getpass
import json
import os
import subprocess
import sys
from pathlib import Path

from .model import SourceError, account_key, metric, source, timestamp
from .transport import MAX_BODY, get_json
from .zcode import DEFAULT_ORIGIN, QUOTA_PATH, normalize_quota

RESET_URL = "https://zcode.z.ai/api/v1/coding-plan/reset/status"
EXPIRY_FIELDS = ("expires_at", "expiresAt", "expire_at", "expireAt",
                 "expireTime", "expire_time", "validTo", "valid_to")

_NODE_DECRYPT = """
let raw='';process.stdin.on('data',d=>raw+=d);process.stdin.on('end',()=>{
const crypto=require('crypto');
const {secret,entries}=JSON.parse(raw);
const key=crypto.createHash('sha256').update(secret).digest();
const out={};
for(const [name,env] of Object.entries(entries)){
  try{
    if(typeof env!=='string'||!env.startsWith('enc:v1:')){out[name]=env||null;continue;}
    const parts=env.slice(7).split('.');
    if(parts.length!==3){out[name]=null;continue;}
    const iv=Buffer.from(parts[0],'base64url'),tag=Buffer.from(parts[1],'base64url'),ct=Buffer.from(parts[2],'base64url');
    if(iv.length!==12||tag.length!==16){out[name]=null;continue;}
    const d=crypto.createDecipheriv('aes-256-gcm',key,iv);d.setAuthTag(tag);
    out[name]=Buffer.concat([d.update(ct),d.final()]).toString('utf8');
  }catch(e){out[name]=null;}
}
process.stdout.write(JSON.stringify(out));
});
"""


def credential_secret(home):
    explicit = os.environ.get("ZCODE_CREDENTIAL_SECRET", "").strip()
    if explicit:
        return explicit
    platform = {"darwin": "darwin", "win32": "win32"}.get(sys.platform, sys.platform)
    return "zcode-credential-fallback:%s:%s:%s" % (platform, home, getpass.getuser())


def decrypt_entries(node_binary, secret, entries, timeout=15):
    if not node_binary:
        raise SourceError("zcode_desktop_node_missing")
    try:
        result = subprocess.run([node_binary, "-e", _NODE_DECRYPT],
                                input=json.dumps({"secret": secret, "entries": entries}).encode(),
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        raise SourceError("zcode_desktop_decrypt_failed") from None
    except OSError:
        raise SourceError("zcode_desktop_node_missing") from None
    if result.returncode or len(result.stdout) > MAX_BODY:
        raise SourceError("zcode_desktop_decrypt_failed")
    try:
        out = json.loads(result.stdout)
    except (ValueError, UnicodeDecodeError):
        raise SourceError("zcode_desktop_decrypt_failed") from None
    if not isinstance(out, dict):
        raise SourceError("zcode_desktop_decrypt_failed")
    return out


def load_desktop_credentials(v2_dir, node_binary, timeout=15):
    path = Path(v2_dir).expanduser() / "credentials.json"
    if not path.is_file():
        raise SourceError("zcode_desktop_not_installed")
    try:
        store = json.loads(path.read_text())
    except (OSError, ValueError):
        raise SourceError("zcode_desktop_credentials_unreadable") from None
    if not isinstance(store, dict):
        raise SourceError("zcode_desktop_credentials_unreadable")
    names = ("zcodejwttoken", "oauth:active_provider",
             "oauth:bigmodel:access_token", "oauth:zai:access_token",
             "oauth:bigmodel:user_info", "oauth:zai:user_info")
    entries = {n: store[n] for n in names if isinstance(store.get(n), str)}
    plain = decrypt_entries(node_binary, credential_secret(str(Path.home())), entries, timeout)
    jwt = plain.get("zcodejwttoken")
    if not isinstance(jwt, str) or not jwt.strip():
        raise SourceError("zcode_desktop_credentials_unreadable")
    family = plain.get("oauth:active_provider") or "bigmodel"
    family = family.strip() if isinstance(family, str) else "bigmodel"
    if family not in ("bigmodel", "zai"):
        family = "bigmodel"
    other = "zai" if family == "bigmodel" else "bigmodel"
    coding = plain.get("oauth:%s:access_token" % family) or plain.get("oauth:%s:access_token" % other)
    if not isinstance(coding, str) or not coding.strip():
        raise SourceError("zcode_desktop_credentials_unreadable")
    identity = None
    profile = plain.get("oauth:%s:user_info" % family) or plain.get("oauth:%s:user_info" % other)
    if isinstance(profile, str):
        try:
            doc = json.loads(profile)
            if isinstance(doc, dict):
                raw = doc.get("id") if family != "zai" else doc.get("user_id", doc.get("id"))
                if isinstance(raw, (str, int)) and not isinstance(raw, bool) and str(raw):
                    identity = str(raw)
        except ValueError:
            pass
    return {"jwt": jwt.strip(), "coding": coding.strip(), "family": family, "identity": identity}


def _expiry(item):
    for field in EXPIRY_FIELDS:
        value = item.get(field)
        if value in (None, ""):
            continue
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            return timestamp(value, unit="milliseconds" if value > 1e11 else "seconds")
        if isinstance(value, str):
            try:
                return timestamp(value)
            except SourceError:
                continue
    return None


def parse_reset_status(payload, now):
    if not isinstance(payload, dict):
        raise SourceError("unsupported_zcode_reset_contract")
    code = payload.get("code")
    if code not in (None, 0, 200):
        raise SourceError("not_authenticated" if code in (401, 1000, 1001, 1002)
                          else "zcode_reset_api_error")
    root = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    cards, seen_keys = [], 0
    for key, kind in (("available_five_hour_resets", "five_hour"),
                      ("available_week_resets", "week")):
        if key not in root:
            continue
        seen_keys += 1
        items = root[key]
        if not isinstance(items, list):
            raise SourceError("unsupported_zcode_reset_contract")
        for item in items:
            if not isinstance(item, dict):
                raise SourceError("unsupported_zcode_reset_contract")
            expiry = _expiry(item)
            if expiry is not None and expiry["epoch_seconds"] + 60 <= now:
                continue
            cards.append({"status": "available", "reset_type": kind, "granted_at": None,
                          "expires_at": expiry,
                          "expiration_state": "no_expiry_reported" if expiry is None else "active"})
    if not seen_keys:
        raise SourceError("unsupported_zcode_reset_contract")
    cards.sort(key=lambda c: c["expires_at"]["epoch_seconds"] if c["expires_at"] else float("inf"))
    eligible = [c["expires_at"] for c in cards if c["expires_at"] is not None]
    return {"available_count": len(cards), "cards": cards, "details_state": "returned",
            "next_known_expiry": min(eligible, key=lambda x: x["epoch_seconds"]) if eligible else None}


def collect_zcode_desktop(v2_dir, node_binary, now, timeout=15):
    creds = load_desktop_credentials(v2_dir, node_binary, timeout)
    jwt = creds["jwt"]
    authorization = jwt if jwt.lower().startswith("bearer ") else "Bearer " + jwt
    payload = get_json(RESET_URL, timeout=timeout, headers={
        "Authorization": authorization,
        "X-Bigmodel-Authorization": creds["coding"],
        "Bigmodel-Target-Type": "PERSONAL",
    })
    cards = parse_reset_status(payload, now)
    out = source("zcode", "account", now)
    out["account_key"] = account_key("zcode", creds["identity"]) if creds["identity"] else None
    out["metrics"]["reset_cards"] = metric(cards)
    plan = None
    try:
        quota_payload = get_json(DEFAULT_ORIGIN + QUOTA_PATH, creds["coding"], timeout,
                                 headers={"Accept-Language": "zh-CN,zh",
                                          "Origin": "https://bigmodel.cn",
                                          "Referer": "https://bigmodel.cn/coding-plan/personal/usage"})
        rows, plan = normalize_quota(quota_payload)
        out["metrics"]["quota"] = metric(rows or None)
        resets = [{"bucket": "window_%d" % r["window_minutes"], "resets_at": r["resets_at"]}
                  for r in rows if r.get("window_minutes") and r["resets_at"]]
        out["metrics"]["reset_time"] = metric(resets or None)
    except SourceError as e:
        out["metrics"]["quota"] = metric(status="not_connected", reason="zcode_desktop_quota_unavailable")
        out["diagnostics"]["quota_error"] = e.code
    out["subscription"] = {"plan": "GLM Coding " + plan.capitalize() if plan else "GLM Coding Plan"}
    out["diagnostics"]["transport"] = "zcode_desktop_login"
    out["diagnostics"]["provider_family"] = creds["family"]
    return out