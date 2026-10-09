"""Renewal dates are not quota resets; date-only observations stay date-only."""
import copy
import re
from datetime import date, datetime
from zoneinfo import ZoneInfo

from .model import SourceError, decimal_string, metric, timestamp


def renewal_date(value, zone='Asia/Shanghai', origin='provider'):
    try:
        day=date.fromisoformat(value)
        ZoneInfo(zone)
    except (ValueError, TypeError, KeyError):
        raise SourceError('invalid_renewal_date') from None
    return {'date':day.isoformat(),'precision':'day','timezone':zone,'event':'renewal','origin':origin}


def countdown(target, now):
    zone=ZoneInfo(target['timezone'])
    days=(date.fromisoformat(target['date'])-datetime.fromtimestamp(now,zone).date()).days
    return {'target_date':target['date'],'timezone':target['timezone'],'precision':'day','event':target['event'],
            'days_remaining':max(0,days),'days_overdue':max(0,-days),
            'seconds_remaining':None,'state':'overdue' if days<0 else 'today' if days==0 else 'upcoming',
            'calculated_at':timestamp(now),'origin':target['origin']}


def credit_refresh_date(value, zone='Asia/Shanghai', origin='provider'):
    try:
        out=renewal_date(value,zone,origin)
    except SourceError:
        raise SourceError('invalid_credit_refresh_date') from None
    out['event']='credit_refresh'
    return out


def refresh_countdowns(snapshot, now):
    for src in snapshot.get('sources',[]):
        for date_name,countdown_name in [('renewal_time','renewal_countdown'),('credit_refresh_time','credit_refresh_countdown')]:
            m=src['metrics'].get(date_name,{})
            if m.get('value') is not None:
                status=m['status']
                src['metrics'][countdown_name]=metric(countdown(m['value'],now),status=status,reason=m.get('reason'))
    return snapshot


def apply_billing_override(src, override, now):
    """User-entered data is bound to a stable billing account, never a provider alone."""
    if not override:return src
    allowed={'account_key','renewal_date','credit_refresh_date','timezone','amount','currency'}
    if not isinstance(override,dict) or set(override)-allowed or not override.get('account_key'):
        raise SourceError('invalid_billing_override')
    if not src.get('account_key') or override['account_key']!=src['account_key']:
        src['diagnostics']['billing_override']='account_mismatch'
        return src
    out=copy.deepcopy(src)
    if 'renewal_date' in override:
        # Do not replace the provider's current subscription date with old manual data.
        if out['metrics']['renewal_time']['value'] is None:
            out['metrics']['renewal_time']=metric(renewal_date(override['renewal_date'],override.get('timezone','Asia/Shanghai'),'user'))
    if 'credit_refresh_date' in override:
        if out['metrics']['credit_refresh_time']['value'] is None:
            out['metrics']['credit_refresh_time']=metric(credit_refresh_date(override['credit_refresh_date'],override.get('timezone','Asia/Shanghai'),'user'))
    if 'amount' in override:
        currency=override.get('currency')
        if not isinstance(currency,str) or not re.fullmatch('[A-Z]{3}',currency):
            raise SourceError('invalid_billing_currency')
        if out['metrics']['renewal_amount']['value'] is None:
            out['metrics']['renewal_amount']=metric({'amount':decimal_string(override['amount']),
                'currency':currency,'origin':'user','basis':'next_renewal','confirmed_by_provider':False})
    elif 'currency' in override:
        raise SourceError('invalid_billing_override')
    out['diagnostics']['billing_override']='applied'
    return refresh_countdowns({'sources':[out]},now)['sources'][0]
