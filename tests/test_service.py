import copy
import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from agent_meter.collector import SnapshotService, coverage_matrix, safe_collect
from agent_meter.model import METRICS, SourceError, failed_source, metric, source, timestamp
from agent_meter.server import load_or_create_token, make_server


def sample(now=1000):
    s=source('codex','account',now)
    s['metrics']['quota']=metric([{'used_percent':10,'remaining_percent':90}])
    app={'name':'Codex','provider':'codex','installed':True}
    return {'schema_version':3,'collected_at':timestamp(now),'sources':[s],
            'coverage':coverage_matrix([app],[s]),'coverage_summary':{'applications':1}}


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.now=1000;self.calls=0

    def tearDown(self):self.tmp.cleanup()

    def service(self,collect_fn=None):
        def capture(config,now):self.calls+=1;return sample(now)
        return SnapshotService({'runtime_dir':self.tmp.name,'cache_ttl_seconds':120},collect_fn or capture,lambda:self.now)

    def test_cache_expiry_and_defensive_copy(self):
        s=self.service();a=s.get();a['sources'][0]['status']='corrupted'
        self.assertEqual(s.get()['sources'][0]['status'],'available')
        self.assertEqual(self.calls,1)
        self.now+=121;s.get();self.assertEqual(self.calls,2)

    def test_concurrent_reads_only_collect_once(self):
        s=self.service();threads=[threading.Thread(target=s.get) for _ in range(8)]
        for t in threads:t.start()
        for t in threads:t.join()
        self.assertEqual(self.calls,1)

    def test_config_setters_do_not_wait_for_a_slow_collection(self):
        release=threading.Event()
        def slow(config,now):
            release.wait(10)
            return sample(now)
        s=SnapshotService({'runtime_dir':self.tmp.name,'cache_ttl_seconds':120},slow,lambda:self.now)
        done=[]
        reader=threading.Thread(target=lambda:done.append(s.get()))
        reader.start();time.sleep(.05)
        started=time.monotonic()
        s.set_web_sessions({'claude':[{'cookie':'x'}]})
        elapsed=time.monotonic()-started
        release.set();reader.join(10)
        self.assertEqual(done[0]['schema_version'],3)
        self.assertLess(elapsed,2)

    def test_invalidation_survives_an_in_flight_collection(self):
        gate=threading.Event();seen=[]
        def slow(config,now):
            initial=config.get('web_sessions')   # read at entry, like the real collect()
            gate.wait(10)
            seen.append(initial)
            return sample(now)
        s=SnapshotService({'runtime_dir':self.tmp.name,'cache_ttl_seconds':120},slow,lambda:self.now)
        reader=threading.Thread(target=s.get);reader.start();time.sleep(.05)
        s.set_web_sessions({'claude':[{'cookie':'NEW'}]})
        gate.set();reader.join(10)
        self.assertEqual(seen,[None])          # the running collect kept the old config
        s.get()                                 # within TTL, but invalidated by the setter
        self.assertEqual(seen,[None,{'claude':[{'cookie':'NEW'}]}])

    def test_failed_refresh_retains_previous_measurement_as_stale(self):
        def fetch(config,now):
            if now==1000:return sample(now)
            out=sample(now);out['sources']=[failed_source('codex','account',now,'connection_failed')];return out
        s=self.service(fetch);s.get();self.now=1200
        out=s.get()
        self.assertEqual(out['sources'][0]['status'],'stale')
        self.assertEqual(out['sources'][0]['observed_at']['epoch_seconds'],1000)
        self.assertEqual(out['sources'][0]['metrics']['quota']['status'],'stale')
        self.assertEqual(out['coverage'][0]['fields']['quota']['status'],'stale')
        self.assertEqual(out['coverage_summary']['available_fields'],0)

    def test_stale_recovery_keeps_fresh_local_tokens(self):
        def fetch(config,now):
            out=sample(now)
            if now!=1000:
                failed=failed_source('kimi','account',now,'connection_failed')
                failed['metrics']['tokens']=metric({'periods':{'all':{'totals':{'requests':5}}}})
                out['sources']=[out['sources'][0],failed]
            else:
                kimi=source('kimi','account',now)
                kimi['metrics']['quota']=metric([{'bucket':'limit5h','used_percent':10}])
                kimi['metrics']['tokens']=metric({'periods':{'all':{'totals':{'requests':4}}}})
                out['sources']=[out['sources'][0],kimi]
            return out
        s=self.service(fetch);s.get();self.now=1200
        kimi=[x for x in s.get()['sources'] if x['id']=='kimi'][0]
        self.assertEqual(kimi['status'],'stale')                       # account part rolled back
        self.assertEqual(kimi['metrics']['quota']['status'],'stale')
        self.assertEqual(kimi['metrics']['tokens']['status'],'available')   # local history stays fresh
        self.assertEqual(kimi['metrics']['tokens']['value']['periods']['all']['totals']['requests'],5)

    def test_atomic_snapshot_permissions(self):
        self.service().get()
        p=Path(self.tmp.name)/'snapshot.json'
        self.assertEqual(p.stat().st_mode&0o777,0o600)
        self.assertEqual(json.loads(p.read_text())['schema_version'],3)

    def test_source_error_isolated_and_private_message_not_exposed(self):
        def fn():raise RuntimeError('Authorization: secret-value private URL')
        out=safe_collect('x','account',1000,fn)
        self.assertEqual(out['status'],'error')
        self.assertNotIn('secret-value',json.dumps(out))

    def test_no_duplicate_sum_across_ccswitch_and_account_tokens(self):
        s=source('codex','account',1000);s['metrics']['tokens']=metric({'lifetime_tokens':123})
        cc=source('ccswitch','local_imported_history',1000)
        cc['metrics']['tokens']=metric({'periods':{'all':{'groups':[{'app':'codex','total_tokens':100}]}}})
        matrix=coverage_matrix([{'name':'Codex','provider':'codex','installed':True}],[s,cc])
        self.assertEqual(matrix[0]['fields']['tokens']['source'],'ccswitch')
        self.assertNotIn('223',json.dumps(matrix))

    def test_unsupported_apps_have_all_field_gaps(self):
        matrix=coverage_matrix([{'name':'Unknown','provider':'unknown','installed':True}],[])
        self.assertEqual(len(matrix[0]['fields']),len(METRICS))
        self.assertTrue(all(x['status']=='not_supported' for x in matrix[0]['fields'].values()))


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.token=load_or_create_token(Path(self.tmp.name)/'api.token')
        self.service=SnapshotService({'runtime_dir':self.tmp.name},lambda config,now:sample(now))
        self.server=make_server(self.service,self.token,0)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.url='http://127.0.0.1:'+str(self.server.server_address[1])

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join();self.tmp.cleanup()

    def request(self,path,auth=True,**headers):
        if auth:headers['Authorization']='Bearer '+self.token
        req=urllib.request.Request(self.url+path,headers=headers)
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        return opener.open(req,timeout=3)

    def test_authenticated_snapshot(self):
        with self.request('/v1/snapshot') as r:
            self.assertEqual(r.status,200);self.assertEqual(json.load(r)['schema_version'],3)

    def test_health_schema_version_matches_snapshot(self):
        with self.request('/v1/health') as r:health=json.load(r)
        with self.request('/v1/snapshot') as r:snapshot=json.load(r)
        self.assertEqual(health['schema_version'],snapshot['schema_version'])
        self.assertEqual(health['schema_version'],3)

    def test_no_auth_denied(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:self.request('/v1/snapshot',False)
        self.assertEqual(ctx.exception.code,401)

    def test_origin_and_rebinding_denied(self):
        for headers in [{'Origin':'https://example.com'},{'Host':'attacker.invalid'}]:
            with self.assertRaises(urllib.error.HTTPError) as ctx:self.request('/v1/snapshot',**headers)
            self.assertEqual(ctx.exception.code,403)

    def test_unknown_endpoint_not_found(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:self.request('/v1/consume-reset-card')
        self.assertEqual(ctx.exception.code,404)

    def test_token_not_printed_or_in_snapshot(self):
        with self.request('/v1/snapshot') as r:self.assertNotIn(self.token,r.read().decode())
        self.assertEqual((Path(self.tmp.name)/'api.token').stat().st_mode&0o777,0o600)
