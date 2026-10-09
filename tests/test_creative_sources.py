import copy
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch

from agent_meter.billing import apply_billing_override, countdown, refresh_countdowns, renewal_date
from agent_meter.collector import SnapshotService, coverage_matrix
from agent_meter.design_mcp import probe_design_mcp
from agent_meter.dreamina import collect_dreamina, normalize_dreamina
from agent_meter.minimax_design import collect_design, design_query, normalize_design
from agent_meter.model import SourceError, failed_source, source, timestamp

NOW=datetime(2026,10,9,2,0,tzinfo=timezone.utc).timestamp()
DREAM={'total_credit':6086,'user_id':1234567890,'user_name':'PRIVATE_NAME','vip_level':'maestro','access_token':'PRIVATE_TOKEN'}
WALLET={'wallets':[{'source':1,'total_credit':'211021','sub_credits':[
 {'credit_type':1,'credit':'210930','end_time':'1792511999999','records':[{'secret':'PRIVATE_RECORD'}]},
 {'credit_type':0,'credit':'91','end_time':'1817473315894'}],
 'subscription_state_known':True,'plan_name':'Design Pro 年会员','cycle_type':3,'privilege_type':103003,
 'next_renewal_time':'08/26/2027','end_time':'08/26/2027','next_credit_refresh_time':'10/20/2026',
 'url':'https://design.minimax.cn/?auth=PRIVATE_TOKEN'}]}

class DreaminaTests(unittest.TestCase):
    def test_real_contract_and_redaction(self):
        out=normalize_dreamina(DREAM,NOW)
        self.assertEqual(out['metrics']['credits']['value']['balance'],'6086')
        for s in ('1234567890','PRIVATE_NAME','PRIVATE_TOKEN'):self.assertNotIn(s,json.dumps(out))
        self.assertIsNone(out['metrics']['renewal_time']['value'])
        self.assertIsNone(out['metrics']['renewal_amount']['value'])

    def test_zero_and_missing_are_different(self):
        self.assertEqual(normalize_dreamina(dict(DREAM,total_credit=0),NOW)['metrics']['credits']['value']['balance'],'0')
        for v in [None,True,-1,'NaN']:
            with self.assertRaises(SourceError):normalize_dreamina(dict(DREAM,total_credit=v),NOW)
        with self.assertRaises(SourceError):normalize_dreamina({'user_id':1},NOW)

    def test_only_readonly_official_command(self):
        with patch('agent_meter.dreamina.subprocess.run',return_value=subprocess.CompletedProcess([],0,json.dumps(DREAM).encode(),b'')) as run:
            collect_dreamina('/fake/dreamina',NOW)
        self.assertEqual(run.call_args.args[0],['/fake/dreamina','user_credit'])
        self.assertFalse(run.call_args.kwargs.get('shell',False))

    def test_login_not_retried_and_stderr_private(self):
        with patch('agent_meter.dreamina.subprocess.run',return_value=subprocess.CompletedProcess([],1,b'',('未检测到有效登录态 PRIVATE_TOKEN').encode())) as run:
            with self.assertRaises(SourceError) as ctx:collect_dreamina('/fake/dreamina',NOW)
        self.assertEqual(ctx.exception.code,'dreamina_not_authenticated');self.assertEqual(run.call_count,1)
        self.assertNotIn('PRIVATE_TOKEN',str(ctx.exception))

    def test_missing_cli_and_timeout(self):
        with self.assertRaises(SourceError):collect_dreamina(None,NOW)
        with patch('agent_meter.dreamina.subprocess.run',side_effect=subprocess.TimeoutExpired('x',1)):
            with self.assertRaises(SourceError) as ctx:collect_dreamina('x',NOW)
        self.assertEqual(ctx.exception.code,'dreamina_cli_timeout')

class DesignTests(unittest.TestCase):
    def test_live_wallet_contract_dates_buckets_and_redaction(self):
        out=normalize_design(WALLET,NOW,'PRIVATE_GROUP')
        self.assertEqual(out['metrics']['credits']['value']['balance'],'211021')
        self.assertEqual(out['metrics']['renewal_countdown']['value']['days_remaining'],321)
        self.assertIsNone(out['metrics']['renewal_countdown']['value']['seconds_remaining'])
        self.assertEqual(out['metrics']['renewal_time']['value']['date'],'2027-08-26')
        self.assertEqual(out['metrics']['reset_time']['value'][0]['date'],'2026-10-20')
        self.assertNotEqual(out['metrics']['renewal_time']['value']['date'],out['metrics']['reset_time']['value'][0]['date'])
        for s in ['PRIVATE_TOKEN','PRIVATE_RECORD','PRIVATE_GROUP']:self.assertNotIn(s,json.dumps(out))

    def test_bad_renewal_date_preserves_balance(self):
        d=copy.deepcopy(WALLET);d['wallets'][0]['next_renewal_time']='02/30/2027'
        out=normalize_design(d,NOW)
        self.assertEqual(out['metrics']['credits']['status'],'available')
        self.assertEqual(out['metrics']['renewal_time']['status'],'error')
        self.assertIsNone(out['subscription']['auto_renew'])

    def test_bad_refill_date_not_used_as_renewal(self):
        d=copy.deepcopy(WALLET);d['wallets'][0]['next_credit_refresh_time']='invalid'
        out=normalize_design(d,NOW)
        self.assertEqual(out['metrics']['reset_time']['status'],'error')
        self.assertEqual(out['metrics']['renewal_time']['value']['date'],'2027-08-26')

    def test_credit_expiry_boolean_not_an_epoch(self):
        d=copy.deepcopy(WALLET);d['wallets'][0]['sub_credits'][0]['end_time']=True
        with self.assertRaises(SourceError):normalize_design(d,NOW)

    def test_op_wallet_not_summed_with_legacy_wallet(self):
        d=copy.deepcopy(WALLET);d['wallets'].append({'source':0,'total_credit':'99999999'})
        self.assertEqual(normalize_design(d,NOW)['metrics']['credits']['value']['balance'],'211021')

    def test_ambiguous_empty_and_bad_wallet_do_not_mean_zero(self):
        for d in [{'wallets':[]},{'wallets':WALLET['wallets']*2},{'wallets':None},{}]:
            with self.assertRaises(SourceError):normalize_design(d,NOW)
        for value in [None,True,'NaN','-1']:
            d=copy.deepcopy(WALLET);d['wallets'][0]['total_credit']=value
            with self.assertRaises(SourceError):normalize_design(d,NOW)

    def test_large_decimal_credit_remains_exact(self):
        d=copy.deepcopy(WALLET);d['wallets'][0]['total_credit']='9223372036854775807'
        self.assertEqual(normalize_design(d,NOW)['metrics']['credits']['value']['balance'],'9223372036854775807')

    def test_unknown_subscription_does_not_invent_renewal(self):
        d=copy.deepcopy(WALLET);d['wallets'][0]['subscription_state_known']=False
        out=normalize_design(d,NOW)
        self.assertIsNone(out['metrics']['renewal_time']['value']);self.assertIsNone(out['subscription']['auto_renew'])
        self.assertEqual(out['metrics']['credits']['status'],'available')

    def test_cancelled_renewal_keeps_expiry_separate(self):
        d=copy.deepcopy(WALLET);d['wallets'][0]['next_renewal_time']=''
        out=normalize_design(d,NOW)
        self.assertFalse(out['subscription']['auto_renew'])
        self.assertEqual(out['subscription']['ends_on'],'2027-08-26')
        self.assertIsNone(out['metrics']['renewal_time']['value'])

    def test_gateway_allowlist_rejects_nonlocal_and_write_paths(self):
        for origin,path in [('https://remote.test', '/api/v1/credit/wallet'),('http://127.0.0.1/a','/api/v1/credit/wallet'),
                            ('http://user:secret@localhost','/api/v1/credit/wallet'),('http://localhost','/api/v1/credit/migrate')]:
            with self.assertRaises(SourceError):design_query(origin,path,1)

    def collector_responses(self,after=None,account_type='PERSONAL'):
        before={'group_id':'PRIVATE_GROUP','mode':'canonical'}
        return [{'status':'ok'},before,{'items':[{'group_id':'PRIVATE_GROUP','account_type':account_type}]},WALLET,after or before]

    def test_scope_verified_and_no_mutating_query(self):
        with patch('agent_meter.minimax_design.design_query',side_effect=self.collector_responses()) as query:
            out=collect_design('http://127.0.0.1:8001',NOW,probe_mcp=False)
        self.assertEqual(out['metrics']['credits']['status'],'available')
        self.assertEqual(query.call_args_list[3].kwargs['headers'],{'x-group-id':'PRIVATE_GROUP'})
        self.assertTrue(all('migrate' not in str(c) and 'pay' not in str(c) for c in query.call_args_list))

    def test_account_switch_discards_result(self):
        with patch('agent_meter.minimax_design.design_query',side_effect=self.collector_responses({'group_id':'OTHER','mode':'canonical'})):
            with self.assertRaises(SourceError) as ctx:collect_design('http://127.0.0.1',NOW,probe_mcp=False)
        self.assertEqual(ctx.exception.code,'design_account_changed_during_query')

    def test_team_scope_not_treated_as_personal_wallet(self):
        with patch('agent_meter.minimax_design.design_query',side_effect=self.collector_responses(account_type='TEAM')) as query:
            with self.assertRaises(SourceError):collect_design('http://127.0.0.1',NOW,probe_mcp=False)
        self.assertEqual(query.call_count,3)

    def test_mcp_failure_does_not_erase_wallet(self):
        with patch('agent_meter.minimax_design.design_query',side_effect=self.collector_responses()),patch('agent_meter.design_mcp.probe_design_mcp',return_value={'connected':False}):
            self.assertEqual(collect_design('http://127.0.0.1',NOW)['metrics']['credits']['status'],'available')

class BillingTests(unittest.TestCase):
    def test_day_countdown_midnight_today_and_overdue(self):
        target=renewal_date('2026-10-10')
        self.assertEqual(countdown(target,NOW)['days_remaining'],1)
        midnight=datetime(2026,10,9,16,tzinfo=timezone.utc).timestamp()
        self.assertEqual(countdown(target,midnight)['state'],'today')
        late=countdown(target,midnight+86400)
        self.assertEqual(late['state'],'overdue');self.assertEqual(late['days_overdue'],1)

    def test_invalid_calendar_date_rejected(self):
        for value in ['2026-02-30','2026-10-10T00:00:00Z',None]:
            with self.assertRaises(SourceError):renewal_date(value)

    def test_manual_amount_and_date_are_account_bound_and_labelled(self):
        src=normalize_dreamina(DREAM,NOW)
        override={'account_key':src['account_key'],'renewal_date':'2026-10-15','amount':'99.90','currency':'CNY'}
        out=apply_billing_override(src,override,NOW)
        self.assertEqual(out['metrics']['renewal_amount']['value']['amount'],'99.90')
        self.assertEqual(out['metrics']['renewal_amount']['value']['origin'],'user')
        self.assertEqual(out['metrics']['renewal_countdown']['value']['days_remaining'],6)
        self.assertIsNone(src['metrics']['renewal_amount']['value'])
        mismatch=apply_billing_override(src,dict(override,account_key='different'),NOW)
        self.assertIsNone(mismatch['metrics']['renewal_amount']['value'])

    def test_provider_date_not_overwritten_by_manual_date(self):
        src=normalize_design(WALLET,NOW,'group')
        out=apply_billing_override(src,{'account_key':src['account_key'],'renewal_date':'2026-10-15'},NOW)
        self.assertEqual(out['metrics']['renewal_time']['value']['date'],'2027-08-26')

    def test_money_currency_and_override_validation(self):
        src=normalize_dreamina(DREAM,NOW)
        for extra in [{'amount':True,'currency':'CNY'},{'amount':'-1','currency':'CNY'},
                      {'amount':'NaN','currency':'CNY'},{'amount':'100'},{'amount':'100','currency':'credits'},
                      {'currency':'CNY'},{'unknown':1}]:
            with self.assertRaises(SourceError):apply_billing_override(src,dict(account_key=src['account_key'],**extra),NOW)
        with self.assertRaises(SourceError):apply_billing_override(src,{'amount':'10','currency':'CNY'},NOW)

    def test_cached_snapshot_countdown_recalculates_across_midnight(self):
        now=[NOW]
        src=normalize_design(WALLET,NOW,'group')
        def fetch(config,now):return {'schema_version':3,'collected_at':timestamp(now),'sources':[src],
            'coverage':coverage_matrix([{'provider':'minimax_design','installed':True}],[src])}
        with tempfile.TemporaryDirectory() as d:
            service=SnapshotService({'runtime_dir':d,'cache_ttl_seconds':999999},fetch,lambda:now[0])
            a=service.get();now[0]+=86400;b=service.get()
        self.assertTrue(b['served_from_cache'])
        self.assertEqual(b['sources'][0]['metrics']['renewal_countdown']['value']['days_remaining'],320)
        self.assertEqual(a['sources'][0]['metrics']['renewal_countdown']['value']['days_remaining'],321)

    def test_auth_failure_does_not_recover_old_account_cache(self):
        now=[NOW];src=normalize_dreamina(DREAM,NOW)
        def fetch(config,now):
            v=src if now==NOW else failed_source('dreamina','creative_account',now,'dreamina_not_authenticated','not_connected')
            return {'sources':[v],'coverage':coverage_matrix([{'provider':'dreamina','installed':True}],[v])}
        with tempfile.TemporaryDirectory() as d:
            service=SnapshotService({'runtime_dir':d},fetch,lambda:now[0]);service.get();now[0]+=121;out=service.get()
        self.assertEqual(out['sources'][0]['status'],'not_connected')
        self.assertIsNone(out['sources'][0]['metrics']['credits']['value'])

class MCPTests(unittest.TestCase):
    def test_only_metadata_methods_invoked(self):
        with tempfile.TemporaryDirectory() as d:
            script=Path(d)/'fake.py';log=Path(d)/'methods.jsonl'
            script.write_text('import sys,json\nfor line in sys.stdin:\n o=json.loads(line)\n with open('+repr(str(log))+',"a") as f:f.write(o["method"]+"\\n")\n if "id" in o:\n  r={"tools":[{"name":"generate_video"}]} if o["method"]=="tools/list" else {}\n  print(json.dumps({"jsonrpc":"2.0","id":o["id"],"result":r}),flush=True)\n')
            result=probe_design_mcp(sys.executable,str(script),'http://127.0.0.1:8001',3)
            self.assertTrue(result['connected']);self.assertFalse(result['financial_tool_names_detected'])
            self.assertEqual(log.read_text().splitlines(),['initialize','notifications/initialized','tools/list'])

    def test_missing_or_failed_mcp_safe(self):
        self.assertFalse(probe_design_mcp(None,None,'http://localhost')['connected'])
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'bad.py';p.write_text('import sys\nsys.exit(1)\n')
            self.assertFalse(probe_design_mcp(sys.executable,str(p),'http://localhost',1)['connected'])


class CreditRefreshTests(unittest.TestCase):
    def test_provider_refresh_is_distinct_from_renewal_and_expiry(self):
        out=normalize_design(WALLET,NOW,'group')
        metrics=out['metrics']
        self.assertEqual(metrics['credit_refresh_time']['value']['date'],'2026-10-20')
        self.assertEqual(metrics['credit_refresh_time']['value']['event'],'credit_refresh')
        self.assertEqual(metrics['credit_refresh_countdown']['value']['days_remaining'],11)
        self.assertIsNone(metrics['credit_refresh_countdown']['value']['seconds_remaining'])
        self.assertNotEqual(metrics['credit_refresh_time']['value']['date'],metrics['renewal_time']['value']['date'])
        self.assertNotIn('expires_at',metrics['credit_refresh_time']['value'])

    def test_missing_refresh_not_derived_from_bucket_expiry_or_plan_end(self):
        d=copy.deepcopy(WALLET);d['wallets'][0].pop('next_credit_refresh_time')
        out=normalize_design(d,NOW)
        self.assertIsNone(out['metrics']['credit_refresh_time']['value'])
        self.assertIsNone(out['metrics']['credit_refresh_countdown']['value'])
        self.assertEqual(out['metrics']['renewal_time']['status'],'available')

    def test_invalid_refresh_only_affects_refresh_fields(self):
        d=copy.deepcopy(WALLET);d['wallets'][0]['next_credit_refresh_time']='02/30/2027'
        out=normalize_design(d,NOW)
        for name in ('credit_refresh_time','credit_refresh_countdown'):
            self.assertEqual(out['metrics'][name]['status'],'error')
        self.assertEqual(out['metrics']['credits']['status'],'available')
        self.assertEqual(out['metrics']['renewal_time']['status'],'available')

    def test_dreamina_refresh_unknown_not_assumed_daily_or_monthly(self):
        out=normalize_dreamina(DREAM,NOW)
        self.assertEqual(out['metrics']['credit_refresh_time']['status'],'not_provided')
        self.assertIsNone(out['metrics']['credit_refresh_countdown']['value'])

    def test_manual_refresh_date_bound_to_account_and_provider_wins(self):
        src=normalize_dreamina(DREAM,NOW)
        override={'account_key':src['account_key'],'credit_refresh_date':'2026-10-15'}
        out=apply_billing_override(src,override,NOW)
        self.assertEqual(out['metrics']['credit_refresh_time']['value']['origin'],'user')
        self.assertEqual(out['metrics']['credit_refresh_countdown']['value']['days_remaining'],6)
        self.assertIsNone(out['metrics']['renewal_time']['value'])
        mismatch=apply_billing_override(src,dict(override,account_key='other'),NOW)
        self.assertIsNone(mismatch['metrics']['credit_refresh_time']['value'])
        design=normalize_design(WALLET,NOW,'group')
        out=apply_billing_override(design,{'account_key':design['account_key'],'credit_refresh_date':'2026-11-01'},NOW)
        self.assertEqual(out['metrics']['credit_refresh_time']['value']['date'],'2026-10-20')

    def test_invalid_manual_date_rejected(self):
        src=normalize_dreamina(DREAM,NOW)
        with self.assertRaises(SourceError) as ctx:
            apply_billing_override(src,{'account_key':src['account_key'],'credit_refresh_date':'2026-02-30'},NOW)
        self.assertEqual(ctx.exception.code,'invalid_credit_refresh_date')

    def test_cached_refresh_countdown_updates_and_does_not_roll_date_forward(self):
        now=[NOW];src=normalize_design(WALLET,NOW,'group')
        def fetch(config,now):
            return {'schema_version':3,'sources':[src],'coverage':coverage_matrix([{'provider':'minimax_design','installed':True}],[src])}
        with tempfile.TemporaryDirectory() as d:
            service=SnapshotService({'runtime_dir':d,'cache_ttl_seconds':9999999},fetch,lambda:now[0]);service.get()
            now[0]+=12*86400;out=service.get()
        value=out['sources'][0]['metrics']['credit_refresh_countdown']['value']
        self.assertEqual(value['target_date'],'2026-10-20')
        self.assertEqual(value['state'],'overdue');self.assertEqual(value['days_overdue'],1)
        self.assertEqual(out['sources'][0]['metrics']['renewal_countdown']['value']['days_remaining'],309)

    def test_failed_refresh_retains_date_as_stale_with_updated_countdown(self):
        now=[NOW];src=normalize_design(WALLET,NOW,'group')
        def fetch(config,now):
            v=src if now==NOW else failed_source('minimax_design','creative_personal_account',now,'connection_failed')
            return {'sources':[v],'coverage':coverage_matrix([{'provider':'minimax_design','installed':True}],[v])}
        with tempfile.TemporaryDirectory() as d:
            service=SnapshotService({'runtime_dir':d},fetch,lambda:now[0]);service.get();now[0]+=86400;out=service.get()
        metric=out['sources'][0]['metrics']['credit_refresh_countdown']
        self.assertEqual(metric['status'],'stale');self.assertEqual(metric['value']['days_remaining'],10)
        self.assertEqual(out['sources'][0]['observed_at']['epoch_seconds'],NOW)
