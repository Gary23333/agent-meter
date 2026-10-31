"""Adapted from CC Switch v4.0.22 usage_stats.rs and sql_helpers.rs.

Copyright (c) 2025 Jason Young. MIT, see THIRD_PARTY_NOTICES.md.
The source database is never migrated or written by this module.
"""


def fresh_input_sql(alias):
    p = alias + "."
    return f"""CASE
      WHEN {p}input_token_semantics = 2 THEN {p}input_tokens
      WHEN {p}app_type IN ('codex','gemini','grokbuild')
           AND {p}input_token_semantics = 1
           AND {p}input_tokens >= ({p}cache_read_tokens + {p}cache_creation_tokens)
        THEN {p}input_tokens - {p}cache_read_tokens - {p}cache_creation_tokens
      WHEN {p}app_type IN ('codex','gemini','grokbuild')
           AND {p}input_token_semantics = 0 AND {p}input_tokens >= {p}cache_read_tokens
        THEN {p}input_tokens - {p}cache_read_tokens
      ELSE {p}input_tokens END"""


def effective_filter(alias="l"):
    # Same as upstream, except the dedup subquery keeps its own table alias
    # name (`p`) instead of `proxy_dedup`.
    return f"""NOT (
      COALESCE({alias}.data_source,'proxy') IN ('session_log','codex_session','gemini_session','opencode_session')
      AND EXISTS (SELECT 1 FROM proxy_request_logs p
        WHERE COALESCE(p.data_source,'proxy') = 'proxy'
          AND p.app_type IN ({alias}.app_type, CASE WHEN {alias}.app_type='claude' THEN 'claude-desktop' ELSE {alias}.app_type END)
          AND p.status_code >= 200 AND p.status_code < 300
          AND p.input_tokens = {alias}.input_tokens AND p.output_tokens = {alias}.output_tokens
          AND p.cache_read_tokens = {alias}.cache_read_tokens
          AND (
              p.cache_creation_tokens = {alias}.cache_creation_tokens
              OR ({alias}.cache_creation_tokens=0 AND COALESCE({alias}.data_source,'proxy') IN ('codex_session','gemini_session','opencode_session'))
              OR (p.cache_creation_tokens=0 AND p.input_token_semantics=0 AND COALESCE({alias}.data_source,'proxy')='codex_session')
          )
          AND p.created_at BETWEEN {alias}.created_at - 600 AND {alias}.created_at + 600
          AND (LOWER(p.model)=LOWER({alias}.model) OR LOWER(p.model)='unknown' OR LOWER({alias}.model)='unknown')
      ))"""


def folded_app(alias):
    # Upstream folds only claude-desktop into claude. The agy/dsh folds are
    # this project's display/merge mapping, not upstream behaviour.
    return (f"CASE WHEN {alias}.app_type='claude-desktop' THEN 'claude' "
            f"WHEN {alias}.app_type='agy' THEN 'antigravity' "
            f"WHEN {alias}.app_type='dsh' THEN 'deepseek_harness' "
            f"ELSE {alias}.app_type END")
