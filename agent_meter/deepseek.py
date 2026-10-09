import os
from decimal import Decimal
from .model import SourceError, decimal_string, metric, source, timestamp
from .transport import get_json

PLATFORM = "https://platform.deepseek.com"
# Undocumented console endpoints, contract from the MIT-licensed
# deepseek-harness-usage-dashboard probe (2026-09): by_api_key buckets are
# the same source as the official usage page; time+tz(=28800) marks the
# GMT+8 calendar day. Read-only, Bearer userToken, never persisted.
USAGE_WINDOW_DAYS = 30


def normalize_balance(payload,now):
    rows=payload.get('balance_infos')
    if not isinstance(rows,list):raise SourceError('invalid_deepseek_balance')
    balances=[]
    for row in rows:
        if row.get('currency') not in {'CNY','USD'}:raise SourceError('unknown_balance_currency')
        balances.append({'unit':row['currency'],'total':decimal_string(row.get('total_balance'),allow_negative=True),
                         'granted':decimal_string(row.get('granted_balance')),'topped_up':decimal_string(row.get('topped_up_balance')),
                         'grant_expiry':None})
    out=source('deepseek_api','api_account',now)
    out['metrics']['credits']=metric(balances)
    return out


def _num(value):
    return value if isinstance(value,(int,float)) and not isinstance(value,bool) and value>=0 else None


def normalize_web_usage(amount,cost,now):
    """by_api_key amount+cost payloads -> {currency, daily, totals}."""
    import datetime as _dt
    amount_biz=(amount.get('data') or {}).get('biz_data') if isinstance(amount,dict) else None
    cost_data=(cost.get('data') or {}).get('biz_data') if isinstance(cost,dict) else None
    cost_groups=cost_data.get('data') if isinstance(cost_data,dict) else None
    if not isinstance(amount_biz,dict) or not isinstance(amount_biz.get('series'),list) \
            or not isinstance(cost_groups,list):
        raise SourceError('unsupported_deepseek_usage_contract')
    group=next((g for g in cost_groups if isinstance(g,dict) and g.get('currency')=='CNY'),
               next((g for g in cost_groups if isinstance(g,dict)),None))
    currency=group.get('currency') if isinstance(group,dict) and group.get('currency') in {'CNY','USD'} else 'CNY'
    tz=28800
    days={}
    def day_of(time):
        value=_num(time)
        if value is None:return None
        return _dt.datetime.fromtimestamp(value+tz,_dt.timezone.utc).date().isoformat()
    for entry in amount_biz['series']:
        if not isinstance(entry,dict) or not isinstance(entry.get('buckets'),list):continue
        for bucket in entry['buckets']:
            usage=bucket.get('usage') if isinstance(bucket,dict) else None
            day=day_of(bucket.get('time') if isinstance(bucket,dict) else None)
            if day is None or not isinstance(usage,dict):continue
            tokens=sum(_num(usage.get(k)) or 0 for k in
                       ('PROMPT_TOKEN','PROMPT_CACHE_HIT_TOKEN','PROMPT_CACHE_MISS_TOKEN','RESPONSE_TOKEN'))
            row=days.setdefault(day,{'date':day,'tokens':0,'requests':0,'amount':'0'})
            row['tokens']+=tokens
            row['requests']+=_num(usage.get('REQUEST')) or 0
    charged=False
    for entry in ((group or {}).get('series') or []):
        if not isinstance(entry,dict) or not isinstance(entry.get('buckets'),list):continue
        for bucket in entry['buckets']:
            day=day_of(bucket.get('time') if isinstance(bucket,dict) else None)
            value=_num(bucket.get('cost') if isinstance(bucket,dict) else None)
            if day is None or value is None or day not in days:continue
            days[day]['amount']=format(Decimal(days[day]['amount'])+Decimal(str(value)),'f')
            charged=True
    if not days:
        raise SourceError('deepseek_usage_empty')
    daily=sorted(days.values(),key=lambda d:d['date'])
    return {'currency':currency,'daily':daily,'total_amount':format(sum((Decimal(d['amount']) for d in daily),Decimal(0)),'f'),
            'total_tokens':sum(d['tokens'] for d in daily),
            'cost_buckets_seen':charged}


def collect_deepseek(now,timeout=15,key=None,user_token=None):
    # Key from the app (Keychain → memory) first, else the environment.
    key=key or os.environ.get('DEEPSEEK_API_KEY')
    if not key:raise SourceError('deepseek_credential_not_connected')
    out=normalize_balance(get_json('https://api.deepseek.com/user/balance',key,timeout),now)
    # Console usage is display-only: it never enters the local-consumption sum.
    if user_token:
        try:
            tz=28800;end=int(now)+tz;start=end-USAGE_WINDOW_DAYS*86400
            query=f"?start={start}&end={end}&tz={tz}"
            usage=normalize_web_usage(
                get_json(PLATFORM+"/api/v0/usage/by_api_key/amount"+query,user_token,timeout),
                get_json(PLATFORM+"/api/v0/usage/by_api_key/cost"+query,user_token,timeout),now)
            out['metrics']['cost']=metric(usage,status='partial' if not usage['cost_buckets_seen'] else 'available')
            out['diagnostics']['usage_transport']='platform_web_session'
        except SourceError as e:
            out['metrics']['cost']=metric(reason=e.code)
    return out
