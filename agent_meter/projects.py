"""Project attribution for local consumption (E2, read-only).

Only ledgers that expose a real project path or session->directory mapping
are attributed: ZCode / OpenCode / MiMo Code / DevECo (session.directory) and
dsh v3/v4 sessions (header cwd). Everything else stays "unattributed" —
never guessed from conversation text or encoded directory names. The view
is a projection of the same ledgers: attributed + unattributed equals the
local-consumption total, no new counting. Paths are sensitive; sharing must
use user aliases (handled by the frontend).
"""
from pathlib import Path

from .applications import app_id, application_usage
from .model import SourceError
from .opencode_tokens import _tokens, readonly_database, validate_schema
from .record_cache import records_cache as _cache

FAMILY = (("opencode", "opencode_db", "opencode_db_not_found", "opencode_db_read_failed", "unsupported_opencode_schema"),
          ("mimo_code", "mimocode_db", "mimocode_db_not_found", "mimocode_db_read_failed", "unsupported_mimocode_schema"),
          ("deveco", "deveco_db", "deveco_db_not_found", "deveco_db_read_failed", "unsupported_deveco_schema"))
TOKEN_FIELDS = ("fresh_input", "output", "reasoning", "cache_read", "cache_write")


def _add(projects, directory, app, model, tokens, requests=1):
    if not isinstance(directory, str) or not directory:
        return False
    row = projects.setdefault(directory, {"tokens": 0, "requests": 0, "apps": {}, "models": {}})
    row["tokens"] += tokens
    row["requests"] += requests
    a = row["apps"].setdefault(app, {"tokens": 0, "requests": 0})
    a["tokens"] += tokens
    a["requests"] += requests
    m = row["models"].setdefault(model, {"tokens": 0, "requests": 0})
    m["tokens"] += tokens
    m["requests"] += requests
    return True


def _family_projects(path, app, missing_code, read_code, schema_code):
    projects = {}
    with readonly_database(path, missing_code=missing_code, read_code=read_code) as conn:
        validate_schema(conn, schema_code=schema_code)
        columns = {r[1] for r in conn.execute("PRAGMA table_info(message)")}
        if "session_id" not in columns:
            raise SourceError(schema_code)
        directories = {}
        if {"id", "directory"} <= {r[1] for r in conn.execute("PRAGMA table_info(session)")}:
            directories = {r[0]: r[1] for r in conn.execute("SELECT id, directory FROM session")
                           if isinstance(r[1], str) and r[1]}
        for session_id, data in conn.execute("SELECT session_id, data FROM message"):
            parsed = _tokens(data)
            if parsed is None:
                continue
            model, fresh, output, reasoning, read, write = parsed
            _add(projects, directories.get(session_id), app, model,
                 fresh + output + reasoning + read + write)
    return projects


def _zcode_projects(path):
    projects = {}
    with readonly_database(path, missing_code="zcode_db_not_found", read_code="zcode_db_read_failed") as conn:
        columns = {r[1] for r in conn.execute("PRAGMA table_info(model_usage)")}
        need = {"session_id", "provider_id", "model_id", "input_tokens", "output_tokens",
                "reasoning_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"}
        if not need <= columns:
            raise SourceError("unsupported_zcode_usage_schema")
        directories = {}
        if {"id", "directory"} <= {r[1] for r in conn.execute("PRAGMA table_info(session)")}:
            directories = {r[0]: r[1] for r in conn.execute("SELECT id, directory FROM session")
                           if isinstance(r[1], str) and r[1]}
        for session_id, provider, model, fresh, output, reasoning, write, read in conn.execute(
                "SELECT session_id, provider_id, model_id, input_tokens, output_tokens,"
                " reasoning_tokens, cache_creation_input_tokens, cache_read_input_tokens FROM model_usage"):
            values = (fresh, output, reasoning, write, read)
            if any(not isinstance(v, int) or isinstance(v, bool) or v < 0 for v in values):
                raise SourceError("invalid_zcode_token_counts")
            name = "%s/%s" % (provider or "unknown", model or "unknown")
            _add(projects, directories.get(session_id), "zcode", name, sum(values))
    return projects


def _dsh_projects(root, zstd_binary):
    from .activity import _parse_dsh_session, _route
    from .zstd_io import ZSTD_ERRORS
    root = Path(root)
    paths = sorted(root.glob("**/session*.jsonl.zstd")) if root.is_dir() else []
    if not paths:
        raise SourceError("dsh_sessions_not_found")
    route = _route(zstd_binary)
    projects, seen = {}, set()
    for path in paths:
        seen.add(str(path))
        try:
            parsed = _cache.read(path, lambda p: _parse_dsh_session(p, route, zstd_binary),
                                 ("projects_dsh", route))
        except (OSError, ZSTD_ERRORS):
            continue
        if not parsed:
            continue
        header, _turns, records = parsed
        cwd = header.get("cwd")
        for record in records:
            # reasoning is a sub-part of output here; the five-field sum would
            # double count it, so total mirrors the ledger's split semantics.
            fresh = record.get("fresh") or 0
            output = record.get("output") or 0
            total = fresh + output + (record.get("cache_read") or 0) + (record.get("cache_write") or 0)
            _add(projects, cwd, "deepseek_harness", record.get("model") or "unknown", total)
    _cache.prune(seen, ("projects_dsh", route))
    return projects


def project_usage(config, snapshot):
    projects, scanned, gaps = {}, [], []
    scanners = [("zcode", lambda: _zcode_projects(config["zcode_usage_db"]))]
    for sid, key, missing, read, schema in FAMILY:
        path = config.get(key)
        if not path:
            continue

        def make(path=path, sid=sid, missing=missing, read=read, schema=schema):
            return lambda: _family_projects(path, sid, missing, read, schema)

        scanners.append((sid, make()))
    scanners.append(("deepseek_harness", lambda: _dsh_projects(config["dsh_sessions_dir"],
                                                               config.get("zstd_binary"))))
    for sid, fn in scanners:
        try:
            part = fn()
        except SourceError as e:
            gaps.append({"source": sid, "reason": e.code})
            continue
        scanned.append(sid)
        for directory, row in part.items():
            target = projects.setdefault(directory, {"tokens": 0, "requests": 0, "apps": {}, "models": {}})
            target["tokens"] += row["tokens"]
            target["requests"] += row["requests"]
            for app, value in row["apps"].items():
                a = target["apps"].setdefault(app, {"tokens": 0, "requests": 0})
                a["tokens"] += value["tokens"]
                a["requests"] += value["requests"]
            for model, value in row["models"].items():
                m = target["models"].setdefault(model, {"tokens": 0, "requests": 0})
                m["tokens"] += value["tokens"]
                m["requests"] += value["requests"]
    usage = application_usage(snapshot.get("sources", []))
    total_tokens = total_requests = 0
    attributed_by_app = {}
    for app, periods in usage.items():
        window = periods.get("all") or {}
        total_tokens += window.get("total_tokens", 0)
        total_requests += window.get("requests", 0)
    for row in projects.values():
        for app, value in row["apps"].items():
            a = attributed_by_app.setdefault(app, {"tokens": 0, "requests": 0})
            a["tokens"] += value["tokens"]
            a["requests"] += value["requests"]
    attributed = sum(row["tokens"] for row in projects.values())
    attributed_requests = sum(row["requests"] for row in projects.values())
    unattributed_by_app = {}
    for app, periods in usage.items():
        window = periods.get("all") or {}
        done = attributed_by_app.get(app, {"tokens": 0, "requests": 0})
        remainder = {"tokens": window.get("total_tokens", 0) - done["tokens"],
                     "requests": window.get("requests", 0) - done["requests"]}
        if remainder["tokens"] or remainder["requests"]:
            unattributed_by_app[app] = remainder
    ranked = sorted(({"project_path": path, **row} for path, row in projects.items()),
                    key=lambda r: -r["tokens"])
    return {
        "schema_version": 1,
        "projects": ranked,
        "attributed_tokens": attributed,
        "attributed_requests": attributed_requests,
        "total_tokens": total_tokens,
        "total_requests": total_requests,
        "unattributed": {"tokens": total_tokens - attributed,
                         "requests": total_requests - attributed_requests,
                         "by_app": unattributed_by_app},
        "sources_scanned": scanned,
        "source_gaps": gaps,
        "note": "Only ledgers with explicit project paths are attributed; the rest stays "
                "unattributed, never guessed. Paths are local-only; share aliases instead.",
    }