import json
import sqlite3
import tempfile
import threading
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from agent_meter.ccswitch import (app_imported_days, collect_ccswitch, readonly_database,
                                  rollup_bounds, summarize, validate_schema)
from agent_meter.collector import collect
from agent_meter.model import SourceError, metric
from agent_meter.prices import PriceTable
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

    def test_mcode_unknown_model_resolved_and_priced(self):
        # CC Switch stores MiniMax Code proxy rows with model "unknown"; the
        # runtime db's per-turn telemetry supplies the name, and the local
        # price table fills the missing (zero) estimate.
        mcode = Path(self.tmp.name) / "runtime-state.sqlite"
        conn = sqlite3.connect(mcode)
        conn.execute("CREATE TABLE local_runtime_token_usage(id INTEGER PRIMARY KEY, session_id TEXT, agent_name TEXT,"
                     " framework_type TEXT, turn_id TEXT, model TEXT, ts INTEGER, input_tokens INTEGER,"
                     " output_tokens INTEGER, reasoning_tokens INTEGER, cache_read_tokens INTEGER,"
                     " cache_write_tokens INTEGER, cost_usd REAL, raw TEXT)")
        conn.execute("CREATE TABLE local_runtime_message_rows(id INTEGER PRIMARY KEY, session_id TEXT, turn_id TEXT,"
                     " role TEXT, data_json TEXT)")
        conn.execute("INSERT INTO local_runtime_message_rows(session_id,turn_id,role,data_json) VALUES('s','t','assistant',?)",
                     (json.dumps({"context_usage_telemetry": {"model": "MiniMax-M3.1-Flash"}}),))
        conn.execute("INSERT INTO local_runtime_token_usage(id,session_id,turn_id,model,ts,input_tokens,output_tokens,"
                     " reasoning_tokens,cache_read_tokens,cache_write_tokens)"
                     " VALUES(7,'s','t',NULL,1000,1000000,1000000,0,0,0)")
        conn.commit()
        conn.close()
        now = int(datetime(2026, 10, 21, 12, tzinfo=ZoneInfo("Asia/Shanghai")).timestamp())
        insert(self.c, "mcode:s:7", app_type="mcode", model="unknown", input_tokens=1000000,
               output_tokens=1000000, created_at=now - 60, total_cost_usd="0")
        out = collect_ccswitch(self.path, now, ZoneInfo("Asia/Shanghai"), str(mcode),
                               PriceTable("USD", {}, set()))
        groups = out["metrics"]["tokens"]["value"]["periods"]["all"]["groups"]
        group = next(g for g in groups if g["app"] == "mcode")
        self.assertEqual(group["model"], "MiniMax-M3.1-Flash")
        self.assertAlmostEqual(float(group["estimated_cost_usd"]), 0.75, places=6)

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

    def test_schema_24_supported_and_25_rejected(self):
        # v4.0.22 migrations 21-24 only add the session_usage_dedup table and
        # session_log_sync.parser_state; the columns we read are unchanged.
        self.c.execute('PRAGMA user_version=24')
        self.c.execute('CREATE TABLE session_usage_dedup (data_source TEXT, semantic_id TEXT, has_entry_id INTEGER)')
        self.c.execute('ALTER TABLE session_log_sync ADD COLUMN parser_state TEXT')
        self.c.commit()
        insert(self.c,'ok',input_tokens=100)
        with readonly_database(self.path) as c:
            self.assertEqual(validate_schema(c),24)
            self.assertEqual(summarize(c)['totals']['total_tokens'],100)
        self.c.execute('PRAGMA user_version=25');self.c.commit()
        with readonly_database(self.path) as c:
            with self.assertRaisesRegex(SourceError,'unsupported_ccswitch_schema'):validate_schema(c)

    def test_v4022_codex_cache_creation_zero_proxy_suppresses_session(self):
        # 4.0.22 adds a third cache-match branch: a proxy row with
        # cache_creation=0 and legacy semantics dedups a codex_session row that
        # carries cache writes (4.0.5 would have kept both).
        insert(self.c,'proxy',app_type='codex',input_tokens=100,output_tokens=50,cache_read_tokens=300,
               cache_creation_tokens=0,input_token_semantics=0,created_at=1000)
        insert(self.c,'session',app_type='codex',input_tokens=100,output_tokens=50,cache_read_tokens=300,
               cache_creation_tokens=50,input_token_semantics=0,created_at=1100,data_source='codex_session')
        with readonly_database(self.path) as c:
            result=summarize(c)
            expected=reference_ccswitch(c,None,None,ZoneInfo('Asia/Shanghai'))
        self.assertEqual(result['totals']['requests'],1)
        self.assertEqual(result['suppressed_duplicate_records'],1)
        for k,v in expected.items():self.assertEqual(result['totals'][k],v,k)

    def test_v4022_codex_cache_branch_requires_legacy_proxy_semantics(self):
        # Only new/no write: a total-inclusive proxy row, or a non-codex session
        # source, must not suppress the session row.
        insert(self.c,'proxy',app_type='codex',input_tokens=100,output_tokens=50,cache_read_tokens=300,
               cache_creation_tokens=0,input_token_semantics=2,created_at=1000)
        insert(self.c,'codex-session',app_type='codex',input_tokens=100,output_tokens=50,cache_read_tokens=300,
               cache_creation_tokens=50,input_token_semantics=0,created_at=1100,data_source='codex_session')
        insert(self.c,'gemini-session',app_type='codex',input_tokens=100,output_tokens=50,cache_read_tokens=300,
               cache_creation_tokens=50,input_token_semantics=0,created_at=1200,data_source='gemini_session')
        with readonly_database(self.path) as c:
            result=summarize(c)
            expected=reference_ccswitch(c,None,None,ZoneInfo('Asia/Shanghai'))
        self.assertEqual(result['totals']['requests'],3)
        for k,v in expected.items():self.assertEqual(result['totals'][k],v,k)

    def test_new_sources_fold_and_direct_primary_apps(self):
        # Project mapping only (not upstream): dsh -> deepseek_harness;
        # other sources keep their app_type. agy is direct-primary: the
        # Antigravity conversation DBs are complete, so CC Switch's partial
        # transcript import must not add a second agy bucket.
        insert(self.c,'agy:s:1',app_type='agy',input_tokens=10,created_at=1000,data_source='agy_session')
        insert(self.c,'dsh:s:1',app_type='dsh',input_tokens=20,created_at=1000,data_source='dsh_session')
        insert(self.c,'kimi:s:1',app_type='kimi',input_tokens=30,created_at=1000,data_source='kimi_session')
        insert(self.c,'mcode:s:1',app_type='mcode',input_tokens=40,created_at=1000,data_source='mcode_session')
        with readonly_database(self.path) as c:
            result=summarize(c)
            apps=sorted(g['app'] for g in result['groups'])
            expected=reference_ccswitch(c,None,None,ZoneInfo('Asia/Shanghai'))
        self.assertEqual(apps,['deepseek_harness','kimi','mcode'])
        self.assertEqual(result['direct_primary_apps'],['agy'])
        # The agy row is outside both the detail and raw counts.
        self.assertEqual(result['totals']['requests'],3)
        self.assertEqual(result['totals']['fresh_input'],90)
        self.assertEqual(result['raw_detail_records'],3)
        for k,v in expected.items():self.assertEqual(result['totals'][k],v,k)

    def test_retained_detail_count_excludes_rollup_requests(self):
        insert(self.c,'proxy',input_tokens=100,created_at=1000)
        insert(self.c,'session',input_tokens=100,created_at=1100,data_source='codex_session')
        self.c.execute("INSERT INTO usage_daily_rollups(date,request_count,success_count) "
                       "VALUES('1970-01-01',7,7)")
        self.c.commit()
        with readonly_database(self.path) as c:
            result=summarize(c)
        self.assertEqual(result['raw_detail_records'],2)
        self.assertEqual(result['deduplicated_detail_records'],1)
        self.assertEqual(result['suppressed_duplicate_records'],1)
        self.assertEqual(result['totals']['requests'],8)
        self.assertEqual(sum(g['detail_requests'] for g in result['groups']),1)

    def test_collect_cache_is_shared_and_cleared_between_runs(self):
        insert(self.c,'first',created_at=1000)
        barrier=threading.Barrier(2)
        real_connect=sqlite3.connect
        disabled=["ccswitch","kimi","qoder","minimax_code","dreamina","minimax_design",
                  "deepseek_api","workbuddy","trae_cn","zcode","opencode","gemini","antigravity",
                  "deepseek_harness","kimi_desktop","mimo","stepfun","volcengine","reset_forecast"]
        config={"runtime_dir":self.tmp.name,"app_roots":[],"ccswitch_db":str(self.path),
                "disabled_sources":disabled}

        def fake_days(*args,**kwargs):
            # Both workers request the same key concurrently; only one may read SQLite.
            barrier.wait(5)
            days,state=app_imported_days(self.path,ZoneInfo('Asia/Shanghai'),'codex')
            return metric({"periods":{},"observed_days":sorted(days),"overlap_state":state})

        def dead(*args,**kwargs):
            raise SourceError("connection_failed")

        with patch('agent_meter.ccswitch.sqlite3.connect',side_effect=real_connect) as connect, \
                patch('agent_meter.collector.collect_codex',side_effect=dead), \
                patch('agent_meter.collector.collect_claude',side_effect=dead), \
                patch('agent_meter.collector.codex_tokens_metric',side_effect=fake_days), \
                patch('agent_meter.collector.claude_tokens_metric',side_effect=fake_days), \
                patch('agent_meter.collector.codex_image_metric',return_value=metric({"count":0})):
            first=collect(config,now=2000)
            self.assertEqual(connect.call_count,1)
            for source_id in ('codex','claude'):
                source=next(s for s in first['sources'] if s['id']==source_id)
                self.assertEqual(source['metrics']['tokens']['value']['observed_days'],['1970-01-01'])

            insert(self.c,'second',created_at=86400)
            second=collect(config,now=2000)
            self.assertEqual(connect.call_count,2)
            for source_id in ('codex','claude'):
                source=next(s for s in second['sources'] if s['id']==source_id)
                self.assertEqual(source['metrics']['tokens']['value']['observed_days'],
                                 ['1970-01-01','1970-01-02'])

    def test_app_imported_days_requires_supported_schema(self):
        # If the CC Switch reader cannot run, direct readers must not exclude
        # days it would have imported, or those days vanish from both sides.
        insert(self.c,'dsh-row',app_type='dsh',input_tokens=10,created_at=1000,data_source='dsh_session')
        self.c.execute('PRAGMA user_version=25');self.c.commit()
        days,state=app_imported_days(self.path,ZoneInfo('Asia/Shanghai'),'dsh')
        self.assertEqual((days,state),(set(),'ccswitch_unsupported_schema'))
        self.c.execute('PRAGMA user_version=24');self.c.commit()
        days,state=app_imported_days(self.path,ZoneInfo('Asia/Shanghai'),'dsh')
        self.assertEqual(state,'checked')
        self.assertEqual(days,{'1970-01-01'})

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
