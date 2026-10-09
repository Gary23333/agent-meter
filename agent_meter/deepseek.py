import os
from .model import SourceError, decimal_string, metric, source
from .transport import get_json


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


def collect_deepseek(now,timeout=15,key=None):
    # Key from the app (Keychain → memory) first, else the environment.
    key=key or os.environ.get('DEEPSEEK_API_KEY')
    if not key:raise SourceError('deepseek_credential_not_connected')
    return normalize_balance(get_json('https://api.deepseek.com/user/balance',key,timeout),now)
