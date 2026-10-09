import copy
import json
import unittest

from agent_meter.codex import normalize_limits, normalize_usage, collect_codex
from agent_meter.codexbar import normalize_codexbar
from agent_meter.kimi import normalize_kimi
from agent_meter.model import SourceError, decimal_string, metric, timestamp
from agent_meter.qoder import normalize_qoder
from agent_meter.transport import CodexRPC
from agent_meter.minimax import normalize_minimax
from agent_meter.deepseek import normalize_balance

NOW=1791480000
LIMITS={
 'accountId':'private-id',
 'rateLimits':{'limitId':'codex','primary':{'usedPercent':25,'windowDurationMins':300,'resetsAt':1791483600}},
 'rateLimitsByLimitId':{'codex':{'primary':{'usedPercent':25,'windowDurationMins':300,'resetsAt':1791483600},
    'secondary':None,'credits':{'balance':'0','hasCredits':False,'unlimited':False}}},
 'rateLimitResetCredits':{'availableCount':3,'credits':[{'id':'private-card-id','status':'available','resetType':'codexRateLimits',
    'grantedAt':1791000000,'expiresAt':1792000000}]},
}


class SourceTests(unittest.TestCase):
    def test_codex_no_legacy_bucket_double_count(self):
        result=normalize_limits(LIMITS,NOW)
        q=result['metrics']['quota']['value']
        self.assertEqual(len(q),1)
        self.assertEqual(q[0]['remaining_percent'],75)

    def test_card_count_not_detail_length(self):
        cards=normalize_limits(LIMITS,NOW)['metrics']['reset_cards']['value']
        self.assertEqual(cards['available_count'],3)
        self.assertEqual(cards['details_state'],'truncated')

    def test_unknown_details_and_known_empty(self):
        a=copy.deepcopy(LIMITS);a['rateLimitResetCredits']['credits']=None
        self.assertIsNone(normalize_limits(a,NOW)['metrics']['reset_cards']['value']['cards'])
        a['rateLimitResetCredits']={'availableCount':0,'credits':[]}
        m=normalize_limits(a,NOW)['metrics']['reset_cards']
        self.assertEqual(m['status'],'available');self.assertEqual(m['value']['cards'],[])

    def test_no_expiry_and_expired_cards(self):
        a=copy.deepcopy(LIMITS);a['rateLimitResetCredits']['credits'][0]['expiresAt']=None
        self.assertEqual(normalize_limits(a,NOW)['metrics']['reset_cards']['value']['cards'][0]['expiration_state'],'no_expiry_reported')
        a['rateLimitResetCredits']['credits'][0]['expiresAt']=NOW-1
        m=normalize_limits(a,NOW)['metrics']['reset_cards']['value']
        self.assertEqual(m['cards'][0]['expiration_state'],'expired')
        self.assertIsNone(m['next_known_expiry'])

    def test_zero_balance_unknown_and_unlimited_separate(self):
        r=normalize_limits(LIMITS,NOW)['metrics']['credits']
        self.assertEqual(r['status'],'available');self.assertEqual(r['value'][0]['balance'],'0')
        a=copy.deepcopy(LIMITS);a['rateLimitsByLimitId']['codex']['credits']={'balance':None,'hasCredits':True,'unlimited':True}
        r=normalize_limits(a,NOW)['metrics']['credits']['value'][0]
        self.assertIsNone(r['balance']);self.assertIs(r['unlimited'],True)

    def test_null_windows_do_not_become_zero(self):
        a={'rateLimits':{'primary':None,'secondary':None}}
        r=normalize_limits(a,NOW)['metrics']['quota']
        self.assertEqual(r['status'],'not_provided');self.assertIsNone(r['value'])

    def test_over_quota_keeps_raw_percent(self):
        a=copy.deepcopy(LIMITS);a['rateLimitsByLimitId']['codex']['primary']['usedPercent']=125
        q=normalize_limits(a,NOW)['metrics']['quota']['value'][0]
        self.assertEqual((q['used_percent'],q['remaining_percent']),(125,0))

    def test_codex_ids_and_unused_secret_fields_not_published(self):
        a=copy.deepcopy(LIMITS);a['access_token']='secret-value';a['rateLimitResetCredits']['credits'][0]['description']='private'
        rendered=json.dumps(normalize_limits(a,NOW))
        for value in ('private-id','private-card-id','secret-value','private'):
            self.assertNotIn(value,rendered)

    def test_account_tokens_are_not_summed_with_daily_buckets(self):
        r=normalize_usage({'summary':{'lifetimeTokens':100},'dailyUsageBuckets':[{'startDate':'2026-10-09','tokens':20}]})
        self.assertEqual(r['value']['lifetime_tokens'],100)
        self.assertEqual(r['value']['daily_buckets'][0]['tokens'],20)

    def test_account_tokens_unknown_and_zero(self):
        self.assertEqual(normalize_usage({'summary':{'lifetimeTokens':None},'dailyUsageBuckets':None})['status'],'not_provided')
        self.assertEqual(normalize_usage({'summary':{'lifetimeTokens':0},'dailyUsageBuckets':[]})['status'],'available')

    def test_seconds_milliseconds_and_display_timezone(self):
        t=timestamp(NOW)
        self.assertTrue(t['display'].endswith('+08:00'))
        self.assertEqual(timestamp(NOW*1000,unit='milliseconds'),t)
        with self.assertRaises(SourceError):timestamp(NOW*1000)

    def test_naive_timestamp_and_nan_rejected(self):
        with self.assertRaises(SourceError):timestamp('2026-10-09T10:00:00')
        with self.assertRaises(SourceError):decimal_string('NaN')
        with self.assertRaises(SourceError):decimal_string('-1')

    def test_rpc_write_method_rejected(self):
        rpc=CodexRPC('unused')
        with self.assertRaisesRegex(SourceError,'write_method_rejected'):
            rpc.call('account/rateLimitResetCredit/consume',{})

    def test_failed_account_token_read_preserves_quota(self):
        class FakeRPC:
            def __init__(self,*a,**kw):pass
            def __enter__(self):return self
            def __exit__(self,*a):pass
            def call(self,method,params):
                if method=='account/usage/read':raise SourceError('rpc_timeout')
                return LIMITS
        out=collect_codex('unused',NOW,rpc_factory=FakeRPC)
        self.assertEqual(out['status'],'partial')
        self.assertEqual(out['metrics']['quota']['status'],'available')
        self.assertEqual(out['metrics']['tokens']['reason'],'rpc_timeout')

    def test_kimi_ratio_and_cents(self):
        p={'code':0,'data':{'kind':'ok','quota':{'usages':{'limit5h':{'usedRatio':.25,'resetAt':'2026-10-09T03:00:00+08:00'}},
           'extraUsage':{'balanceCents':125,'currency':'CNY','monthlyUsedCents':0}}}}
        out=normalize_kimi(p,NOW)
        self.assertEqual(out['metrics']['quota']['value'][0]['used_percent'],25)
        self.assertEqual(out['metrics']['credits']['value']['amount'],'1.25')
        self.assertEqual(out['metrics']['credits']['value']['monthly_used_amount'],'0')

    def test_kimi_200_transport_inband_error_rejected(self):
        for p in [{'code':50001,'data':{}},{'code':0,'data':{'kind':'error','message':'private upstream message'}}]:
            with self.assertRaises(SourceError):normalize_kimi(p,NOW)

    def test_kimi_installed_summary_limits_contract(self):
        p={'code':0,'data':{'kind':'ok','summary':{'used':20,'limit':100,'window':{'duration':1,'unit':'week'},
             'reset_at':'2026-10-10T00:00:00Z'},'limits':[{'used':0,'limit':100,'window':{'duration':5,'unit':'hour'}}],
             'extra_usage':None}}
        out=normalize_kimi(p,NOW)
        self.assertEqual([q['used_percent'] for q in out['metrics']['quota']['value']],[20,0])
        self.assertEqual(out['diagnostics']['contract'],'summary_limits')
        self.assertEqual(out['metrics']['credits']['status'],'not_provided')

    def test_kimi_zero_limit_percentage_unknown(self):
        p={'code':0,'data':{'kind':'ok','summary':{'used':0,'limit':0,'window':{'duration':1,'unit':'week'}},'limits':[]}}
        self.assertIsNone(normalize_kimi(p,NOW)['metrics']['quota']['value'][0]['used_percent'])

    def test_negative_wallet_is_not_erased_or_clamped(self):
        p={'code':0,'data':{'kind':'ok','quota':{'usages':{},'extraUsage':{'balanceCents':-125,'currency':'CNY'}}}}
        self.assertEqual(normalize_kimi(p,NOW)['metrics']['credits']['value']['amount'],'-1.25')

    def test_qoder_buckets_not_summed_and_session_not_account(self):
        p={'userId':'private','userQuota':{'total':100,'remaining':0,'used':100,'percentage':100,'unit':'Credits'},
           'addOnQuota':{'remaining':20,'unit':'Credits'},'session':{'total_credits':55}}
        out=normalize_qoder(p,NOW)
        self.assertEqual(len(out['metrics']['credits']['value']),2)
        self.assertEqual(out['metrics']['credits']['value'][0]['remaining'],0)
        self.assertNotIn('55',json.dumps(out))
        self.assertEqual(out['metrics']['reset_time']['status'],'not_provided')

    def test_codexbar_card_summary_not_fabricated_details(self):
        out=normalize_codexbar([{'provider':'codex','usage':{'primary':{'usedPercent':10}},
             'resetCredits':{'available':3,'nextExpiresAt':'2026-10-23T00:00:00Z'}}],NOW)[0]
        self.assertIsNone(out['metrics']['reset_cards']['value']['cards'])

    def test_minimax_remaining_percentage_and_millisecond_clock(self):
        p={'base_resp':{'status_code':0},'model_remains':[{'model_name':'video','current_interval_remaining_percent':100},
          {'model_name':'general','current_interval_remaining_percent':98,'current_weekly_status':1,
           'current_weekly_remaining_percent':95,'end_time':1792000000000,'weekly_end_time':1793000000000}]}
        q=normalize_minimax(p,NOW)['metrics']['quota']['value']
        self.assertEqual([x['used_percent'] for x in q],[2,5])
        self.assertEqual(q[0]['resets_at']['epoch_seconds'],1792000000)

    def test_minimax_disabled_week_is_not_full_free_quota(self):
        p={'model_remains':[{'model_name':'general','current_interval_remaining_percent':100,
                           'current_weekly_status':3,'current_weekly_remaining_percent':100}]}
        q=normalize_minimax(p,NOW)['metrics']['quota']['value']
        self.assertEqual(len(q),1)

    def test_minimax_unrecognized_contract_rejected(self):
        with self.assertRaises(SourceError):normalize_minimax({'something_new':[]},NOW)

    def test_deepseek_currencies_separate_and_no_invented_expiry(self):
        p={'balance_infos':[{'currency':'CNY','total_balance':'0','granted_balance':'0','topped_up_balance':'0'},
                           {'currency':'USD','total_balance':'1.25','granted_balance':'0.25','topped_up_balance':'1'}]}
        out=normalize_balance(p,NOW)['metrics']['credits']['value']
        self.assertEqual([x['unit'] for x in out],['CNY','USD'])
        self.assertEqual(out[0]['total'],'0');self.assertIsNone(out[1]['grant_expiry'])
