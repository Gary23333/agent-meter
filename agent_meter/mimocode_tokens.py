"""MiMo Code and DevECo local token usage (read-only).

Both keep an opencode-isomorphic drizzle sqlite ledger: assistant messages
carry data.tokens {total, input, output, reasoning, cache:{write,read}} with
input fresh and cache separate, plus data.modelID and millisecond
time_created. Verified on this machine (2026-11-08): mimocode.db 868
token-bearing assistant rows (writes stopped 2026-09-22), deveco-stable.db
4 rows. Each database is an independent product ledger with no overlap with
the standalone opencode or @hilo Design databases. Only token/model fields
are selected; message text stays in the database.
"""
from zoneinfo import ZoneInfo

from .opencode_tokens import collect_message_db_tokens


def collect_mimocode_tokens(path, now, zone=ZoneInfo("Asia/Shanghai")):
    return collect_message_db_tokens(
        path, now, source_id="mimo_code", app="mimo_code",
        coverage="mimocode_local_message_db",
        missing_code="mimocode_db_not_found", read_code="mimocode_db_read_failed",
        schema_code="unsupported_mimocode_schema", zone=zone)


def collect_deveco_tokens(path, now, zone=ZoneInfo("Asia/Shanghai")):
    return collect_message_db_tokens(
        path, now, source_id="deveco", app="deveco",
        coverage="deveco_local_message_db",
        missing_code="deveco_db_not_found", read_code="deveco_db_read_failed",
        schema_code="unsupported_deveco_schema", zone=zone)