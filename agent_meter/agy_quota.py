"""Antigravity desktop 5-hour/weekly quota via the local language_server RPC.

The desktop app runs a ``language_server`` process that listens on localhost.
Its command line carries ``--app_data_dir antigravity``, a CSRF token and two
ports (one HTTPS, one HTTP). Only the HTTP port answers the protobuf JSON RPC
used here, and only with the ``x-codeium-csrf-token`` header. Requests are
POSTed to ``/exa.language_server_pb.LanguageServerService/<Method>`` on
127.0.0.1. Nothing outside localhost is contacted and no credential is ever
returned, logged or stored: GetUserStatus also carries the signed-in person's
name and email, so those fields are never read into rows.
"""
import json
import re
import shlex
import subprocess
import urllib.error
import urllib.request

from .model import SourceError, number, timestamp

SERVICE = "exa.language_server_pb.LanguageServerService"
WINDOW_MINUTES = {"5h": 300, "weekly": 10080}
MAX_RESPONSE = 4 * 1024 * 1024
_PORT = re.compile(r"\bTCP\s+\S*:(\d+)\s+\(LISTEN\)")


def _command_argument(tokens, name):
    """Value of ``--name value`` or ``--name=value`` in a process command."""
    for index, token in enumerate(tokens):
        if token == name and index + 1 < len(tokens):
            return tokens[index + 1]
        prefix = name + "="
        if token.startswith(prefix):
            return token[len(prefix):]
    return None


def _server_candidates(text):
    """Desktop language_server candidates first, then CLI, from `ps` output."""
    desktop, cli = [], []
    for line in text.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) != 2 or not parts[0].isdigit():
            continue
        pid, command = int(parts[0]), parts[1]
        try:
            tokens = shlex.split(command)
        except ValueError:
            continue
        if not tokens or tokens[0].rsplit("/", 1)[-1] != "language_server":
            continue
        token = _command_argument(tokens, "--csrf_token")
        app_data_dir = _command_argument(tokens, "--app_data_dir")
        if not token or app_data_dir not in {"antigravity", "antigravity-cli"}:
            continue
        candidate = {"pid": pid, "csrf_token": token, "app_data_dir": app_data_dir,
                     "ide_version": _command_argument(tokens, "--override_ide_version")}
        (desktop if app_data_dir == "antigravity" else cli).append(candidate)
    return desktop + cli


def _parse_listening_ports(text):
    return sorted({int(match.group(1)) for match in _PORT.finditer(text)})


def _run(command, timeout):
    return subprocess.run(command, capture_output=True, text=True, timeout=timeout)


def _find_server(timeout):
    try:
        proc = _run(["ps", "-axo", "pid=,command="], timeout)
    except (OSError, subprocess.SubprocessError):
        raise SourceError("antigravity_quota_unreadable") from None
    if proc.returncode != 0:
        raise SourceError("antigravity_quota_unreadable")
    candidates = _server_candidates(proc.stdout or "")
    if not candidates:
        raise SourceError("antigravity_language_server_not_running")
    return candidates[0]


def _listening_ports(pid, timeout):
    try:
        proc = _run(["lsof", "-a", "-nP", "-p", str(pid), "-iTCP", "-sTCP:LISTEN"], timeout)
    except (OSError, subprocess.SubprocessError):
        return []
    if proc.returncode != 0 and not proc.stdout:
        return []
    return _parse_listening_ports(proc.stdout or "")


def _call_rpc(port, method, csrf_token, timeout):
    url = "http://127.0.0.1:%d/%s/%s" % (port, SERVICE, method)
    request = urllib.request.Request(url, data=b"{}", method="POST", headers={
        "Content-Type": "application/json", "x-codeium-csrf-token": csrf_token})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read(MAX_RESPONSE)
    payload = json.loads(body)
    if not isinstance(payload, dict):
        raise SourceError("antigravity_quota_unreadable")
    return payload


def _try_rpc(port, method, csrf_token, timeout):
    """Successful JSON payload or None. HTTPS/other ports simply fail here."""
    try:
        return _call_rpc(port, method, csrf_token, timeout)
    except (OSError, ValueError, urllib.error.URLError, SourceError):
        return None


def _text(value):
    return value if isinstance(value, str) and value.strip() else None


def _fraction(value):
    fraction = number(value)
    if fraction > 1:
        raise SourceError("antigravity_quota_unreadable")
    return fraction


def _quota_groups(payload):
    if not isinstance(payload, dict):
        raise SourceError("antigravity_quota_unreadable")
    response = payload.get("response")
    if isinstance(response, dict):
        payload = response
    groups = payload.get("groups")
    if not isinstance(groups, list):
        raise SourceError("antigravity_quota_unreadable")
    return groups


def _quota_rows(payload):
    rows = []
    for group_index, group in enumerate(_quota_groups(payload)):
        if not isinstance(group, dict):
            raise SourceError("antigravity_quota_unreadable")
        group_name = _text(group.get("displayName")) or "group-%d" % group_index
        buckets = group.get("buckets") or []
        if not isinstance(buckets, list):
            raise SourceError("antigravity_quota_unreadable")
        for bucket_index, bucket in enumerate(buckets):
            if not isinstance(bucket, dict):
                raise SourceError("antigravity_quota_unreadable")
            window = _text(bucket.get("window"))
            remaining = _fraction(bucket.get("remainingFraction"))
            rows.append({
                "bucket": _text(bucket.get("bucketId")) or _text(bucket.get("displayName"))
                          or "bucket-%d" % bucket_index,
                "group": group_name,
                "window": window,
                "window_minutes": WINDOW_MINUTES.get(window),
                "used_percent": (1 - remaining) * 100,
                "remaining_percent": remaining * 100,
                "remaining_fraction": remaining,
                "resets_at": timestamp(bucket.get("resetTime")),
                "description": _text(bucket.get("description")),
                "source": "agy_language_server",
            })
    return rows


def quota_rows(payload):
    """Quota summary JSON -> contract rows (pure, no process/network)."""
    try:
        return _quota_rows(payload)
    except SourceError:
        raise SourceError("antigravity_quota_unreadable") from None


def _model_configs(payload):
    if not isinstance(payload, dict):
        return []
    status = payload.get("userStatus")
    if isinstance(status, dict):
        payload = status
    data = payload.get("cascadeModelConfigData")
    configs = data.get("clientModelConfigs") if isinstance(data, dict) else None
    return configs if isinstance(configs, list) else []


def model_quota_rows(payload):
    """Fallback rows from GetUserStatus model quotaInfo (only with resetTime)."""
    rows = []
    for config in _model_configs(payload):
        if not isinstance(config, dict):
            continue
        quota = config.get("quotaInfo")
        if not isinstance(quota, dict) or quota.get("resetTime") is None:
            continue
        try:
            remaining = _fraction(quota.get("remainingFraction"))
            resets_at = timestamp(quota.get("resetTime"))
        except SourceError:
            continue
        bucket = _text(config.get("modelId")) or _text(config.get("label"))
        if not bucket:
            continue
        rows.append({
            "bucket": bucket, "group": "", "window": None, "window_minutes": None,
            "used_percent": (1 - remaining) * 100, "remaining_percent": remaining * 100,
            "remaining_fraction": remaining, "resets_at": resets_at, "description": None,
            "source": "agy_language_server_models",
        })
    return rows


def collect_antigravity_quota(now, timeout=3):
    """Quota metric value (rows) from the running desktop language_server."""
    server = _find_server(timeout)
    ports = _listening_ports(server["pid"], timeout)
    status_payload = None
    summary_payload = None
    for port in ports:
        if status_payload is None:
            status_payload = _try_rpc(port, "GetUserStatus", server["csrf_token"], timeout)
        summary_payload = _try_rpc(port, "RetrieveUserQuotaSummary", server["csrf_token"], timeout)
        if summary_payload is not None:
            break
    if summary_payload is not None:
        try:
            rows = quota_rows(summary_payload)
        except SourceError:
            rows = []
        if rows:
            return rows
    if status_payload is not None:
        rows = model_quota_rows(status_payload)
        if rows:
            return rows
    raise SourceError("antigravity_quota_unreadable")
