import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from agent_meter.ccswitch import collect_ccswitch, readonly_database, rollup_bounds, summarize, validate_schema
from agent_meter.model import SourceError
from agent_meter.verify import reference_ccswitch
from tests.support import database, insert


class CCSwitchTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=Path(self.tmp.name)/"usage.db"
        self.c=database(self.path)

    def tearDown(self):
        self.c.close();self.tmp.cleanup()

    def totals(self,start=None,end=None):
        with readonly_database(self.path) as c:
            return summarize(c,start,end)["totals"]

    def test_cache_semantics_and_decimal_cost(self):
        insert(self.c,'a',input_tokens=1000,cache_read_tokens=600,output_tokens=100,total_cost_usd='0.1')
        insert(self.c,'b',app_type='claude',input_tokens=200,cache_read_tokens=5000,output_tokens=100,total_cost_usd='0.2')
        insert(self.c,'c',input_tokens=1000,cache_read_tokens=300,cache_creation_tokens=200,input_token_semantics=1)
        insert(self.c,'d',input_tokens=500,cache_read_tokens=300,cache_creation_tokens=200,input_token_semantics=2)
        t=self.totals()
        self.assertEqual(t['fresh_input'],1600)
        self.assertEqual(t['cache_read'],6200)
        self.assertEqual(t['cache_write'],400)
        self.assertEqual(t['total_tokens'],8400)
        self.assertEqual(t['estimated_cost_usd'],'0.3')

    def test_session_proxy_dedup_and_display_folding(self):
        insert(self.c,'proxy',app_type='claude-desktop',input_tokens=200,cache_read_tokens=500,created_at=1000)
        insert(self.c,'session',app_type='claude',input_tokens=200,cache_read_tokens=500,created_at=1100,data_source='session_log')
        with readonly_database(self.path) as c: result=summarize(c)
        self.assertEqual(result['totals']['requests'],1)
        self.assertEqual(result['suppressed_duplicate_records'],1)
        self.assertEqual(result['groups'][0]['app'],'claude')

    def test_failed_proxy_does_not_suppress_session(self):
        insert(self.c,'proxy',input_tokens=100,created_at=1000,status_code=500)
        insert(self.c,'session',input_tokens=100,created_at=1100,data_source='codex_session')
        self.assertEqual(self.totals()['requests'],2)

    def test_duplicate_boundary_and_model_mismatch(self):
        insert(self.c,'proxy',input_tokens=100,created_at=1000)
        insert(self.c,'edge',input_tokens=100,created_at=1600,data_source='codex_session')
        insert(self.c,'outside',input_tokens=100,created_at=1601,data_source='codex_session')
        insert(self.c,'different-model',input_tokens=100,created_at=1200,model='other',data_source='codex_session')
        self.assertEqual(self.totals()['requests'],3)

    def test_proxy_outside_filter_still_suppresses_session(self):
        insert(self.c,'proxy',input_tokens=100,created_at=999)
        insert(self.c,'session',input_tokens=100,created_at=1001,data_source='codex_session')
        self.assertEqual(self.totals(1000,2000)['requests'],0)

    def test_unknown_model_and_nullable_legacy_source(self):
        insert(self.c,'proxy',input_tokens=100,created_at=1000,model='unknown',data_source=None)
        insert(self.c,'session',input_tokens=100,created_at=1000,model='other',data_source='codex_session')
        self.assertEqual(self.totals()['requests'],1)

    def test_rollups_full_days_only(self):
        zone=ZoneInfo('Asia/Shanghai')
        start=int(datetime(2026,10,1,12,tzinfo=zone).timestamp())
        end=int(datetime(2026,10,3,12,tzinfo=zone).timestamp())
        for date,value in [('2026-10-01',10),('2026-10-02',20),('2026-10-03',30)]:
            self.c.execute('INSERT INTO usage_daily_rollups(date,input_tokens) VALUES (?,?)',(date,value))
        self.c.commit()
        with readonly_database(self.path) as c:result=summarize(c,start,end)
        self.assertEqual(result['totals']['total_tokens'],20)
        self.assertEqual(result['excluded_partial_rollup_days'],['2026-10-01','2026-10-03'])
        self.assertEqual(result['period_status'],'partial')
        self.assertTrue(result['total_is_lower_bound'])

    def test_midnight_range_does_not_include_next_day_rollup(self):
        zone=ZoneInfo('Asia/Shanghai')
        start=int(datetime(2026,10,1,tzinfo=zone).timestamp())
        end=int(datetime(2026,10,2,tzinfo=zone).timestamp())
        lo,hi=rollup_bounds(start,end)
        self.assertEqual((lo.isoformat(),hi.isoformat()),('2026-10-01','2026-10-01'))

    def test_dst_rollup_date_bounds(self):
        zone=ZoneInfo('America/New_York')
        start=int(datetime(2026,3,8,tzinfo=zone).timestamp())
        end=int(datetime(2026,3,8,23,59,59,tzinfo=zone).timestamp())
        lo,hi=rollup_bounds(start,end,zone)
        self.assertEqual(lo,hi)
        self.assertEqual(lo.isoformat(),'2026-03-08')

    def test_unknown_schema_and_semantics_fail_closed(self):
        self.c.execute('PRAGMA user_version=21');self.c.commit()
        with readonly_database(self.path) as c:
            with self.assertRaisesRegex(SourceError,'unsupported_ccswitch_schema'):validate_schema(c)
        self.c.execute('PRAGMA user_version=20');self.c.commit()
        insert(self.c,'bad',input_token_semantics=9)
        with readonly_database(self.path) as c:
            with self.assertRaisesRegex(SourceError,'unknown_token_semantics'):validate_schema(c)

    def test_source_database_cannot_be_written(self):
        with readonly_database(self.path) as c:
            with self.assertRaises(Exception):c.execute('DELETE FROM proxy_request_logs')

    def test_zero_is_known_for_empty_period(self):
        result=collect_ccswitch(self.path,1791483200)
        value=result['metrics']['tokens']['value']['periods']['today']['totals']
        self.assertEqual(result['metrics']['tokens']['status'],'available')
        self.assertEqual(value['total_tokens'],0)
        self.assertIsNone(value['cache_hit_rate'])

    def test_reference_uses_independent_record_algorithm(self):
        insert(self.c,'proxy',input_tokens=1000,cache_read_tokens=600,created_at=1000,total_cost_usd='0.1')
        insert(self.c,'session',input_tokens=1000,cache_read_tokens=600,created_at=1200,data_source='codex_session',total_cost_usd='0.1')
        insert(self.c,'unique',app_type='claude',input_tokens=10,cache_creation_tokens=50,created_at=1400,total_cost_usd='0.2')
        self.c.execute("INSERT INTO usage_daily_rollups(date,input_tokens,total_cost_usd) VALUES('1970-01-01',5,'0.3')")
        self.c.commit()
        with readonly_database(self.path) as c:
            actual=summarize(c,None,86400)['totals']
            expected=reference_ccswitch(c,None,86400,ZoneInfo('Asia/Shanghai'))
        for k,v in expected.items():self.assertEqual(actual[k],v,k)
