"""Installed Design MCP discovery + allowlisted local wallet queries, never purchases."""
from datetime import datetime
import re
from urllib.parse import urlsplit

from .billing import apply_billing_override, countdown, credit_refresh_date, renewal_date
from .model import SourceError, account_key, decimal_string, integer, metric, source, timestamp
from .transport import get_json

SCOPE='/api/internal/sessions/billing-current-scope'
CONTEXTS='/api/v1/team/contexts'
WALLET='/api/v1/credit/wallet'
ALLOWED={SCOPE,CONTEXTS,WALLET,'/api/health/live'}


def design_query(origin,path,timeout,headers=None):
    parsed=urlsplit(origin)
    if (parsed.scheme!='http' or parsed.hostname not in {'127.0.0.1','localhost','::1'}
        or parsed.path not in {'','/'} or parsed.query or parsed.fragment or parsed.username or parsed.password
        or path not in ALLOWED):raise SourceError('invalid_design_endpoint')
    return get_json(origin.rstrip('/')+path,timeout=timeout,local=True,headers=headers)


def parse_plan_day(value):
    if not isinstance(value,str) or not value.strip():return None
    if not re.fullmatch(r'\d{2}/\d{2}/\d{4}',value.strip()):
        raise SourceError('invalid_design_subscription_date')
    try:return datetime.strptime(value.strip(),'%m/%d/%Y').date().isoformat()
    except ValueError:raise SourceError('invalid_design_subscription_date') from None


def normalize_design(payload,now,identity=None):
    if not isinstance(payload,dict) or not isinstance(payload.get('wallets'),list):
        raise SourceError('unsupported_design_wallet_contract')
    wallets=payload['wallets']
    # OP is the active Media Plan; legacy HILO wallet is a different ledger.
    active=[w for w in wallets if isinstance(w,dict) and w.get('source')==1 and not isinstance(w.get('source'),bool)]
    if len(active)!=1:raise SourceError('design_active_wallet_ambiguous')
    w=active[0]
    out=source('minimax_design','creative_personal_account',now)
    out['account_key']=account_key('minimax_design',identity)
    sub=[]
    rows=w.get('sub_credits')
    if rows is not None and not isinstance(rows,list):raise SourceError('invalid_design_subcredits')
    for row in rows or []:
        if not isinstance(row,dict):raise SourceError('invalid_design_subcredits')
        end=row.get('end_time')
        if end not in (None,'',0,'0'):
            if isinstance(end,bool) or not isinstance(end,(str,int)) or not str(end).isdigit():
                raise SourceError('invalid_design_credit_expiry')
            try:end=timestamp(int(end),unit='milliseconds')
            except (ValueError,TypeError):raise SourceError('invalid_design_credit_expiry') from None
        else:end=None
        sub.append({'type':integer(row.get('credit_type')),'balance':decimal_string(row.get('credit')),'expires_at':end})
    out['metrics']['credits']=metric({'balance':decimal_string(w.get('total_credit')),
         'unit':'minimax_design_media_credits','wallet_source':1,'buckets':sub})
    known=w.get('subscription_state_known') is True
    privilege=w.get('privilege_type')
    paid=known and isinstance(privilege,int) and not isinstance(privilege,bool) and privilege>0
    out['subscription']={'state_known':known,'plan':w.get('plan_name') if isinstance(w.get('plan_name'),str) else None,
                         'cycle_type':w.get('cycle_type') if isinstance(w.get('cycle_type'),int) else None,
                         'auto_renew':None,'ends_on':None}
    out['metrics']['renewal_amount']=metric(reason='design_wallet_does_not_return_renewal_amount')
    if known:
        try:out['subscription']['ends_on']=parse_plan_day(w.get('end_time'))
        except SourceError:out['diagnostics']['subscription_end']='invalid_design_subscription_date'
        target=None
        renewal_error=False
        try:target=parse_plan_day(w.get('next_renewal_time')) if paid else None
        except SourceError:renewal_error=True
        out['subscription']['auto_renew']=None if renewal_error else bool(target) if paid else False
        if target:
            value=renewal_date(target)
            out['metrics']['renewal_time']=metric(value)
            out['metrics']['renewal_countdown']=metric(countdown(value,now))
        else:
            for name in ('renewal_time','renewal_countdown'):
                out['metrics'][name]=metric(status='error' if renewal_error else 'not_provided',
                    reason='invalid_design_subscription_date' if renewal_error else 'no_scheduled_automatic_renewal')
    else:
        for name in ('renewal_time','renewal_countdown'):
            out['metrics'][name]=metric(reason='design_subscription_state_unknown')
    refresh=None
    try:refresh=parse_plan_day(w.get('next_credit_refresh_time')) if known else None
    except SourceError:
        out['metrics']['reset_time']=metric(status='error',reason='invalid_design_subscription_date')
        for name in ('credit_refresh_time','credit_refresh_countdown'):
            out['metrics'][name]=metric(status='error',reason='invalid_design_subscription_date')
    if refresh:
        # A credit refill is separate from subscription renewal.
        value=credit_refresh_date(refresh)
        out['metrics']['credit_refresh_time']=metric(value)
        out['metrics']['credit_refresh_countdown']=metric(countdown(value,now))
        out['metrics']['reset_time']=metric([{'bucket':'membership_credit_refill','date':refresh,
                                             'precision':'day','timezone':'Asia/Shanghai'}])
    elif out['metrics']['credit_refresh_time']['status']!='error':
        for name in ('credit_refresh_time','credit_refresh_countdown'):
            out['metrics'][name]=metric(reason='design_subscription_state_unknown' if not known else 'design_wallet_does_not_return_credit_refresh_time')
    out['diagnostics']['transport']='design_local_gateway_wallet'
    return out


def collect_design(origin,now,timeout=20,override=None,node=None,mcp_entry=None,probe_mcp=True):
    health=design_query(origin,'/api/health/live',timeout)
    if not isinstance(health,dict) or health.get('status')!='ok':raise SourceError('design_gateway_not_ready')
    before=design_query(origin,SCOPE,timeout)
    if not isinstance(before,dict) or not isinstance(before.get('group_id'),str) or not before['group_id']:
        raise SourceError('design_billing_scope_unavailable')
    identity=before['group_id']
    contexts=design_query(origin,CONTEXTS,timeout)
    items=contexts.get('items') if isinstance(contexts,dict) else None
    current=[x for x in items or [] if isinstance(x,dict) and x.get('group_id')==identity]
    if len(current)!=1 or current[0].get('account_type')!='PERSONAL':
        raise SourceError('design_personal_scope_required')
    payload=design_query(origin,WALLET,timeout,headers={'x-group-id':identity})
    after=design_query(origin,SCOPE,timeout)
    if not isinstance(after,dict) or after.get('group_id')!=identity or after.get('mode')!=before.get('mode'):
        raise SourceError('design_account_changed_during_query')
    out=apply_billing_override(normalize_design(payload,now,identity),override,now)
    if probe_mcp:
        from .design_mcp import probe_design_mcp
        out['diagnostics']['mcp']=probe_design_mcp(node,mcp_entry,origin,min(timeout,10))
    return out
