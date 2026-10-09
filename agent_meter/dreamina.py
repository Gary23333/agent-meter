"""Only the official CLI's no-generation user_credit operation is invoked."""
import json
import subprocess

from .billing import apply_billing_override
from .model import SourceError, account_key, decimal_string, metric, source
from .transport import MAX_BODY


def normalize_dreamina(payload,now):
    if not isinstance(payload,dict) or 'total_credit' not in payload:
        raise SourceError('unsupported_dreamina_contract')
    identity=payload.get('user_id')
    if isinstance(identity,bool) or not isinstance(identity,(str,int)) or not str(identity):
        raise SourceError('dreamina_account_missing')
    out=source('dreamina','creative_account',now)
    out['account_key']=account_key('dreamina',str(identity))
    out['metrics']['credits']=metric({'balance':decimal_string(payload['total_credit']),'unit':'dreamina_credits'})
    level=payload.get('vip_level')
    if isinstance(level,str) and len(level)<80:out['subscription']={'plan':level}
    for name in ('renewal_time','renewal_countdown','renewal_amount'):
        out['metrics'][name]=metric(reason='dreamina_cli_does_not_return_subscription_billing')
    for name in ('credit_refresh_time','credit_refresh_countdown'):
        out['metrics'][name]=metric(reason='dreamina_cli_does_not_return_credit_refresh_time')
    out['diagnostics']['transport']='official_cli_user_credit'
    return out


def collect_dreamina(binary,now,timeout=20,override=None):
    if not binary:raise SourceError('dreamina_cli_not_available')
    try:
        result=subprocess.run([binary,'user_credit'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                              timeout=timeout,check=False)
    except subprocess.TimeoutExpired:raise SourceError('dreamina_cli_timeout') from None
    except OSError:raise SourceError('dreamina_cli_not_available') from None
    if len(result.stdout)>MAX_BODY or len(result.stderr)>MAX_BODY:raise SourceError('response_too_large')
    if result.returncode:
        if '未检测到有效登录态'.encode() in result.stderr+result.stdout:
            raise SourceError('dreamina_not_authenticated')
        raise SourceError('dreamina_cli_failed')
    try:payload=json.loads(result.stdout)
    except (ValueError,UnicodeDecodeError):raise SourceError('invalid_dreamina_json') from None
    return apply_billing_override(normalize_dreamina(payload,now),override,now)
