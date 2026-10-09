import sqlite3
from pathlib import Path


def database(path):
    c=sqlite3.connect(path)
    c.executescript("""
    PRAGMA user_version=20;
    CREATE TABLE proxy_request_logs (
        request_id TEXT PRIMARY KEY, provider_id TEXT DEFAULT 'p', app_type TEXT DEFAULT 'codex',
        model TEXT DEFAULT 'm', pricing_model TEXT, input_tokens INTEGER DEFAULT 0, output_tokens INTEGER DEFAULT 0,
        cache_read_tokens INTEGER DEFAULT 0, cache_creation_tokens INTEGER DEFAULT 0,
        input_token_semantics INTEGER DEFAULT 0,total_cost_usd TEXT DEFAULT '0',
        status_code INTEGER DEFAULT 200,cost_multiplier TEXT DEFAULT '1',created_at INTEGER DEFAULT 0,
        data_source TEXT DEFAULT 'proxy');
    CREATE TABLE usage_daily_rollups (
        date TEXT,provider_id TEXT DEFAULT 'p',app_type TEXT DEFAULT 'codex',model TEXT DEFAULT 'm',pricing_model TEXT,
        input_tokens INTEGER DEFAULT 0,output_tokens INTEGER DEFAULT 0,cache_read_tokens INTEGER DEFAULT 0,
        cache_creation_tokens INTEGER DEFAULT 0,input_token_semantics INTEGER DEFAULT 2,
        total_cost_usd TEXT DEFAULT '0',request_count INTEGER DEFAULT 1,success_count INTEGER DEFAULT 1);
    CREATE TABLE session_log_sync (last_synced_at INTEGER);
    """)
    c.commit()
    return c


def insert(c,request_id,**fields):
    fields=dict(request_id=request_id,**fields)
    c.execute("INSERT INTO proxy_request_logs ("+",".join(fields)+") VALUES ("+",".join("?" for _ in fields)+")",list(fields.values()))
    c.commit()
