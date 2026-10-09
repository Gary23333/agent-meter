"""MiniMax quota parsing adapted from CC Switch v4.0.5 coding_plan.rs.

Copyright (c) 2025 Jason Young, MIT. See THIRD_PARTY_NOTICES.md.
Read credentials in memory only; never execute provider usage scripts.
"""
import json
import os
import sqlite3
from pathlib import Path
from urllib.parse import urlsplit

from .model import SourceError, metric, number, source, timestamp
from .transport import get_json


def normalize_minimax(payload,now):
    if not isinstance(payload,dict) or payload.get('base_resp',{}).get('status_code') not in (None,0):
        raise SourceError('minimax_api_error')
    values=payload.get('model_remains')
    if not isinstance(values,list):raise SourceError('unsupported_minimax_contract')
    general=next((x for x in values if isinstance(x,dict) and x.get('model_name')=='general'),None)
    out=source('minimax_code','account',now)
    if general is None:return out
    rows,resets=[],[]
    for bucket,field,expiry,enabled in [
        ('5h','current_interval_remaining_percent','end_time',True),
        ('week','current_weekly_remaining_percent','weekly_end_time',general.get('current_weekly_status')==1),
    ]:
        if not enabled or general.get(field) is None:continue
        remaining=number(general[field])
        if remaining>100:raise SourceError('invalid_minimax_percentage')
        reset=timestamp(general.get(expiry),unit='milliseconds')
        rows.append({'bucket':bucket,'used_percent':100-remaining,'remaining_percent':remaining,'resets_at':reset})
        if reset:resets.append({'bucket':bucket,'resets_at':reset})
    out['metrics']['quota']=metric(rows or None)
    out['metrics']['reset_time']=metric(resets or None)
    return out


def credential_from_ccswitch(path):
    """Select a unique current MiniMax endpoint/key, without running scripts."""
    path=Path(path).expanduser()
    if not path.is_file():return None,None
    conn=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=3)
    try:
        conn.execute('PRAGMA query_only=ON')
        keys=set()
        for (text,) in conn.execute('SELECT settings_config FROM providers WHERE is_current=1'):
            try:
                config=json.loads(text)
                env=config.get('env',{})
                base=env.get('ANTHROPIC_BASE_URL')
                key=env.get('ANTHROPIC_AUTH_TOKEN') or env.get('ANTHROPIC_API_KEY')
                host=urlsplit(base or '').hostname
                if host in {'api.minimaxi.com','api.minimax.cn','api.minimax.io'} and isinstance(key,str) and key:
                    keys.add((key,'global' if host=='api.minimax.io' else 'cn'))
            except (ValueError,AttributeError,TypeError):continue
        if len(keys)>1:raise SourceError('multiple_minimax_accounts_require_selection')
        return next(iter(keys)) if keys else (None,None)
    finally:conn.close()


def collect_minimax(ccswitch_db,now,timeout=15,app_key=None):
    key=app_key or os.environ.get('MINIMAX_TOKEN_PLAN_KEY')
    region=os.environ.get('MINIMAX_REGION','cn')
    origin=('menubar_app' if app_key else 'environment') if key else 'ccswitch_current_provider'
    if not key:key,region=credential_from_ccswitch(ccswitch_db)
    if not key:raise SourceError('minimax_credential_not_connected')
    if region not in {'cn','global'}:raise SourceError('invalid_minimax_region')
    # Current official FAQ endpoint; strictly validate the response contract.
    domain='www.minimax.cn' if region=='cn' else 'www.minimax.io'
    out=normalize_minimax(get_json('https://'+domain+'/v1/token_plan/remains',key,timeout),now)
    out['diagnostics'].update({'region':region,'credential_origin':origin})
    return out
