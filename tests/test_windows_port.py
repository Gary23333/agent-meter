"""Windows 适配层测试：只使用模拟数据，不访问用户账户。"""
import json
import os
import sqlite3
import subprocess
import sys
import time
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

try:
    import zstandard
except ImportError:
    zstandard = None
from windows import backend
from agent_meter.model import SourceError
from agent_meter.kimi import process_exists


class WindowsBackendTests(unittest.TestCase):
    def test_mimo_session_is_explicit_and_only_allowlisted_cookies_are_sent(self):
        answers = {'/balance': {'code': 0, 'data': {'balance': '12.3', 'currency': 'CNY'}},
                   '/tokenPlan/detail': {'code': 0, 'data': {'planCode': 'lite'}},
                   '/tokenPlan/usage': {'code': 0, 'data': {'monthUsage': {'used': 20, 'limit': 100}}}}
        def response(url, **kwargs):
            self.assertTrue(url.startswith('https://platform.xiaomimimo.com/api/v1/'))
            self.assertNotIn('private-extra', kwargs['headers']['Cookie'])
            return answers[url.removeprefix('https://platform.xiaomimimo.com/api/v1')]
        with patch('agent_meter.mimo.get_json', side_effect=response) as request:
            with self.assertRaises(SourceError): backend.mimo_account(None, 1800000000)
            request.assert_not_called()
            session = {'cookie': 'api-platform_serviceToken=synthetic-secret; userId=42; private-extra=secret', 'user_agent': 'Synthetic/1.0'}
            result = backend.mimo_account(session, 1800000000)
            self.assertEqual(result['quota']['value'][0]['remaining_percent'], 80)
            self.assertEqual(result['credits']['value'][0]['balance'], '12.3')
            self.assertNotIn('synthetic-secret', json.dumps(result))
            self.assertNotIn('private-extra', json.dumps(result))
            with self.assertRaises(SourceError): backend.mimo_account({'cookie': 'x\r\ny', 'user_agent': 'ua'}, 1800000000)

    def test_mimo_missing_session_is_offline(self):
        env = dict(os.environ, MIMO_COOKIE='synthetic-ambient-secret')
        result = subprocess.run([sys.executable, '-m', 'windows.backend', '--mimo-only'], input='{"session":null}',
                                text=True, encoding='utf-8', capture_output=True, timeout=15, check=True, env=env)
        self.assertEqual(json.loads(result.stdout)['reason'], 'mimo_session_missing')
        self.assertNotIn('synthetic-ambient-secret', result.stdout + result.stderr)

    def test_mimo_failed_plan_does_not_guess_pay_as_you_go(self):
        def response(url, **kwargs):
            if url.endswith('/balance'): return {'code': 0, 'data': {'balance': '12', 'currency': 'CNY'}}
            raise SourceError('synthetic_plan_failure')
        with patch('agent_meter.mimo.get_json', side_effect=response):
            result = backend.mimo_account({'cookie':'api-platform_serviceToken=secret; userId=42', 'user_agent':'synthetic'}, 1800000000)
        self.assertEqual(result['status'], 'partial')
        self.assertIsNone(result['subscription'])
        self.assertEqual(result['credits']['value'][0]['balance'], '12')
        self.assertNotIn('secret', json.dumps(result))

    def test_volcengine_requires_explicit_pair_and_signs_fixed_endpoint(self):
        payload = {'Result': {'PlanName': 'PLAN_TIER_LITE', 'QuotaUsage': [
            {'Level': 'session', 'Percent': 20}, {'Level': 'weekly', 'Percent': 50}]}}
        with patch.dict('os.environ', {'VOLC_ACCESSKEY': 'ambient-private'}), \
             patch('agent_meter.volcengine.get_json', return_value=payload) as request:
            with self.assertRaises(SourceError): backend.volcengine_quota(None, 1800000000)
            with self.assertRaises(SourceError): backend.volcengine_quota({'access_key_id':'ark-key','secret_access_key':'x'}, 1800000000)
            request.assert_not_called()
            result = backend.volcengine_quota({'access_key_id':'AK-synthetic', 'secret_access_key':'synthetic-private'}, 1800000000)
            self.assertEqual(request.call_args.args[0], 'https://open.volcengineapi.com/?Action=GetCodingPlanUsage&Version=2024-01-01')
            self.assertEqual(request.call_args.kwargs['body'], b'')
            self.assertEqual(result['quota']['value'][0]['remaining_percent'], 80)
            self.assertNotIn('synthetic-private', json.dumps(result))
            self.assertNotIn('AK-synthetic', json.dumps(result))
            self.assertNotIn('ambient-private', json.dumps(result))

    def test_volcengine_subprocess_missing_pair_is_offline(self):
        env = dict(os.environ, VOLC_ACCESSKEY='synthetic-ambient-secret')
        result = subprocess.run([sys.executable, '-m', 'windows.backend', '--volcengine-only'], input='{"credentials":null}',
                                text=True, encoding='utf-8', capture_output=True, timeout=15, check=True, env=env)
        self.assertEqual(json.loads(result.stdout)['reason'], 'volcengine_credential_not_connected')
        self.assertNotIn('synthetic-ambient-secret', result.stdout + result.stderr)

    def test_zcode_requires_explicit_key_and_filters_account_metadata(self):
        payload = {'code': 200, 'success': True, 'data': {'level': 'pro', 'limits': [
            {'type': 'CREDIT_LIMIT', 'unit': 3, 'number': 5, 'usage': 100, 'remaining': 75},
            {'type': 'TIME_LIMIT', 'usage': 100, 'remaining': 20}]}}
        with patch.dict('os.environ', {'ZCODE_API_KEY': 'ambient-secret'}), \
             patch('agent_meter.zcode.get_json', return_value=payload) as request:
            with self.assertRaises(SourceError): backend.zcode_quota(None, 1800000000)
            request.assert_not_called()
            result = backend.zcode_quota('synthetic-secret', 1800000000)
            self.assertEqual(request.call_args.args[0], 'https://open.bigmodel.cn/api/monitor/usage/quota/limit')
            self.assertEqual(request.call_args.args[1], 'synthetic-secret')
            self.assertEqual(result['quota']['value'][0]['remaining_percent'], 75)
            self.assertEqual(result['subscription']['plan'], 'GLM Coding Pro')
            self.assertNotIn('synthetic-secret', json.dumps(result))
            self.assertNotIn('ambient-secret', json.dumps(result))
            with self.assertRaises(SourceError): backend.zcode_quota('bad key', 1800000000)

    def test_zcode_subprocess_missing_key_is_offline(self):
        env = dict(os.environ, ZCODE_API_KEY='synthetic-ambient-secret')
        result = subprocess.run([sys.executable, '-m', 'windows.backend', '--zcode-only'], input='{"key":null}',
                                text=True, encoding='utf-8', capture_output=True, timeout=15, check=True, env=env)
        self.assertEqual(json.loads(result.stdout)['reason'], 'zcode_credential_not_connected')
        self.assertNotIn('synthetic-ambient-secret', result.stdout + result.stderr)

    def test_workbuddy_uses_only_explicit_session_and_fixed_endpoint(self):
        payload = {'code': 0, 'data': {'SubscriptionPackageName': '模拟套餐', 'Packages': [
            {'CapacityUnit': 'credits', 'CycleTotalCapacity': '100', 'CycleRemainCapacity': '25', 'CycleFrozenCapacity': '0'}]}}
        with patch('agent_meter.web_sources.post_json', return_value=payload) as request:
            with self.assertRaises(SourceError):
                backend.workbuddy_balance(None, 1800000000)
            request.assert_not_called()
            result = backend.workbuddy_balance({'cookie': 'session=synthetic-private', 'user_agent': 'SyntheticBrowser/1.0'}, 1800000000)
            self.assertEqual(request.call_args.args[0], 'https://www.workbuddy.cn/billing/meter/get-user-resource-summary')
            self.assertEqual(result['quota']['value'][0]['remaining_percent'], 25)
            self.assertNotIn('synthetic-private', json.dumps(result))
            self.assertNotIn('SyntheticBrowser', json.dumps(result))
            with self.assertRaises(SourceError):
                backend.workbuddy_balance({'cookie': 'session=x\r\nheader=y', 'user_agent': 'SyntheticBrowser/1.0'}, 1800000000)

    def test_deepseek_balance_requires_explicit_key_and_uses_official_endpoint(self):
        payload = {'is_available': True, 'balance_infos': [{'currency': 'CNY', 'total_balance': '110.00',
                   'granted_balance': '10.00', 'topped_up_balance': '100.00'}]}
        with patch.dict('os.environ', {'DEEPSEEK_API_KEY': 'ambient-secret'}), \
             patch('agent_meter.deepseek.get_json', return_value=payload) as request:
            with self.assertRaises(SourceError):
                backend.deepseek_balance(None, 1800000000)
            request.assert_not_called()
            result = backend.deepseek_balance('synthetic-secret', 1800000000)
            self.assertEqual(request.call_args.args[0], 'https://api.deepseek.com/user/balance')
            self.assertEqual(request.call_args.args[1], 'synthetic-secret')
            self.assertEqual(result['credits']['value'][0]['total'], '110.00')
            self.assertNotIn('synthetic-secret', json.dumps(result))
            self.assertNotIn('ambient-secret', json.dumps(result))
            with self.assertRaises(SourceError):
                backend.deepseek_balance('bad key', 1800000000)

    def test_quota_cards_drop_once_and_preserve_private_account_names(self):
        now = 1800000000
        def account(label, remaining, reset=1800003600):
            return {'label': label, 'status': 'available', 'quota': {'status': 'available', 'value': [
                {'bucket': '5h', 'remaining_percent': remaining, 'resets_at': {'epoch_seconds': reset}}]}}
        with tempfile.TemporaryDirectory() as root:
            snapshot = {'account': {'status': 'disabled'}, 'other_accounts': {'MiniMax Code': [account('synthetic-private-label', 15)]}}
            first = backend.update_quota_cards(root, snapshot, now)
            cards = {row['id']: row['count'] for row in first['cards']}
            self.assertEqual((cards['q5_50'], cards['q5_80'], cards['q5_90']), (1, 1, 0))
            again = backend.update_quota_cards(root, snapshot, now + 60)
            self.assertEqual({row['id']: row['count'] for row in again['cards']}, cards)
            snapshot['other_accounts']['MiniMax Code'][0] = account('synthetic-private-label', 5)
            later = backend.update_quota_cards(root, snapshot, now + 120)
            self.assertEqual({row['id']: row['count'] for row in later['cards']}['q5_90'], 1)
            snapshot['other_accounts']['MiniMax Code'].append(account('synthetic-second-label', 15))
            multiple = backend.update_quota_cards(root, snapshot, now + 180)
            self.assertEqual({row['id']: row['count'] for row in multiple['cards']}['q5_80'], 2)
            ledger = (Path(root) / 'collection.json').read_text(encoding='utf-8')
            self.assertNotIn('synthetic-private-label', ledger)
            self.assertNotIn('synthetic-second-label', ledger)
            self.assertNotIn('synthetic-private-label', json.dumps(later))

    def test_quota_cards_ignore_invalid_or_expired_windows_and_preserve_corrupt_ledger(self):
        now = 1800000000
        snapshot = {'account': {'status': 'available', 'quota': {'status': 'available', 'value': [
            {'bucket': '5h', 'remaining_percent': 0, 'resets_at': {'epoch_seconds': now - 1}},
            {'bucket': '5h', 'remaining_percent': True, 'resets_at': {'epoch_seconds': now + 3600}},
            {'bucket': 'unsafe|bucket', 'remaining_percent': 0, 'resets_at': {'epoch_seconds': now + 3600}}]}}, 'other_accounts': {}}
        self.assertEqual(backend.quota_card_sources(snapshot, now), [])
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'collection.json'
            path.write_text('{invalid', encoding='utf-8')
            result = backend.update_quota_cards(root, snapshot, now)
            self.assertEqual(result['status'], 'error')
            self.assertEqual(path.read_text(encoding='utf-8'), '{invalid')

    def test_weekly_quota_card_uses_its_own_tiers(self):
        now = 1800000000
        snapshot = {'account': {'status': 'available', 'quota': {'status': 'available', 'value': [
            {'bucket': 'codex', 'window_minutes': 10080, 'remaining_percent': 0,
             'resets_at': {'epoch_seconds': now + 7 * 86400}}]}}, 'other_accounts': {}}
        with tempfile.TemporaryDirectory() as root:
            result = backend.update_quota_cards(root, snapshot, now)
        counts = {row['id']: row['count'] for row in result['cards']}
        self.assertEqual([counts[f'q7_{suffix}'] for suffix in ('50', '80', '90', 'full')], [1, 1, 1, 1])
        self.assertEqual(counts['q5_50'], 0)

    def test_local_medals_use_supported_daily_records_and_mark_gaps(self):
        now = datetime(2026, 11, 14, 12, tzinfo=timezone.utc).timestamp()
        metric = {'status': 'available', 'value': {'periods': {'all': {'totals': {'requests': 2, 'total_tokens': 100000002}}},
                  'daily_buckets': [{'date': '2026-11-13', 'tokens': 100000000},
                                    {'date': '2026-11-14', 'tokens': 2},
                                    {'date': '2099-01-01', 'tokens': 999999999},
                                    {'date': 'invalid', 'tokens': 999999999}]}}
        result = backend.local_medals({'observed_at': now, 'history': {'Codex': metric,
            'failed': {'status': 'error', 'reason': 'synthetic', 'value': metric['value']}}})
        self.assertTrue(result['incomplete'])
        self.assertEqual(result['sources'], 1)
        self.assertEqual(result['active_days'], 2)
        badges = {row['id']: row for row in result['medals']}
        self.assertTrue(badges['day_1']['earned'])
        self.assertEqual(badges['day_1']['value'], 100000000)
        self.assertFalse(badges['life_10']['earned'])
        self.assertEqual({row['category'] for row in result['medals']}, {'day_peak', 'lifetime', 'streak', 'apps', 'record'})
        self.assertNotIn('daily_buckets', json.dumps(result))
        self.assertIsNone(backend.local_medals({'observed_at': now, 'history': {}}))
        empty = {'status': 'available', 'value': {'periods': {'all': {'totals': {'requests': 1, 'total_tokens': 0}}},
                 'daily_buckets': [{'date': '2026-11-14', 'tokens': 0}]}}
        self.assertIsNone(backend.local_medals({'observed_at': now, 'history': {'Codex': empty}}))
        failed = backend.local_medals({'observed_at': now, 'history': {'Codex': {'status': 'error', 'reason': 'read_failed'}}})
        self.assertTrue(failed['incomplete'])
        self.assertEqual(failed['medals'], [])

    def test_medal_failure_does_not_hide_local_usage(self):
        source = {'version': 1, 'observed_at': time.time(), 'account': {'status': 'disabled'}, 'history': {}, 'local_credits': {}}
        with patch('windows.backend.local_medals', side_effect=ValueError('synthetic')):
            result = backend.compact_history(source)
        self.assertEqual(result['history'], {})
        self.assertTrue(result['local_medals']['incomplete'])
        self.assertEqual(result['local_medals']['medals'], [])

    def test_forecast_projection_keeps_basis_and_never_invents_missing_values(self):
        source = {'status': 'partial', 'metrics': {'reset_forecast': {'value': {
            'cache_state': 'stale', 'sources': [
                {'source': 'willreset', 'status': 'available', 'headline_24h': 30,
                 'raw_24h': 10, 'raw_48h': 40, 'updated_at': {'epoch_seconds': 1000}, 'private_text': 'must-not-leak'},
                {'source': 'codex_reset', 'status': 'error', 'raw_24h': 0, 'updated_at': {'epoch_seconds': True}},
                {'source': 'codexreset_org', 'status': 'available', 'headline_24h': float('nan'), 'raw_48h': 101},
                {'source': 'unknown', 'status': 'available', 'raw_24h': 50}]}}}}
        result = backend.forecast_summary(source)
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['cache_state'], 'stale')
        self.assertEqual(result['sources'][0]['24h'], 30)
        self.assertEqual(result['sources'][0]['24h_basis'], 'published_answer')
        self.assertEqual(result['sources'][0]['48h'], 40)
        self.assertEqual(result['sources'][0]['48h_basis'], 'cadence_model_fallback')
        self.assertEqual(result['sources'][0]['updated_at'], 1000)
        self.assertNotIn('24h', result['sources'][1])
        self.assertNotIn('updated_at', result['sources'][1])
        self.assertNotIn('24h', result['sources'][2])
        self.assertNotIn('48h', result['sources'][2])
        self.assertEqual(len(result['sources']), 3)
        self.assertNotIn('must-not-leak', json.dumps(result))

    def test_forecast_cache_is_used_only_when_called(self):
        with tempfile.TemporaryDirectory() as root, patch('windows.backend.collect_reset_forecast') as collect:
            backend.collect(account_only=True, home=root, disabled_accounts=frozenset({'codex', 'kimi', 'claude'}))
            collect.assert_not_called()
            collect.return_value = {'status': 'available', 'metrics': {'reset_forecast': {'value': {'sources': []}}}}
            result = backend.forecast_only(Path(root) / 'forecast')
            self.assertEqual(result['status'], 'available')
            self.assertEqual(collect.call_args.kwargs['cache_path'], Path(root) / 'forecast' / 'reset-forecast.json')
        self.assertEqual(backend.forecast_summary({'metrics': {}})['status'], 'unavailable')

    def test_forecast_ensemble_uses_valid_fresh_sources_and_keeps_missing_horizon(self):
        now = 1800000000
        def row(key, number, age, confidence):
            return {'source': key, 'status': 'available', 'headline_24h': number,
                    'updated_at': {'epoch_seconds': now - age}, 'self_reported': {'confidence': confidence}}
        source = {'status': 'available', 'metrics': {'reset_forecast': {'value': {'sources': [
            row('willreset', 35, 1800, 'high'), row('codex_reset', 28, 3600, 'low'),
            row('codexreset_org', 99, 49 * 3600, 'high')]}}}}
        result = backend.forecast_summary(source, now=now)
        self.assertEqual(result['ensemble']['24h'], {'min': 28, 'max': 35, 'weighted_median': 35,
                         'n': 2, 'agreement': 'close', 'has_model': False})
        self.assertNotIn('48h', result['ensemble'])
        source['metrics']['reset_forecast']['value']['sources'][0]['headline_24h'] = float('nan')
        result = backend.forecast_summary(source, now=now)
        self.assertEqual(result['ensemble']['24h']['weighted_median'], 28)
        self.assertEqual(result['ensemble']['24h']['n'], 1)

    def test_forecast_projects_clock_and_history_without_remote_prose_or_urls(self):
        now = 1800000000
        source = {'status': 'partial', 'metrics': {'reset_forecast': {'value': {
            'sources': [], 'history_events': [
                {'kind': 'reset', 'announced_at': {'epoch_seconds': now - i * 86400},
                 'effective_at': {'epoch_seconds': now - i * 86400 + 60}, 'confirmed': True,
                 'sources': ['willreset', 'codex_reset', 'willreset', 'unknown'],
                 'summary': 'private-marker', 'url': 'https://invalid.example/private-marker', 'post_id': 'private-marker'}
                for i in range(45)]}},
            'known_reset_countdown': {'value': {'targets': [
                {'kind': 'typical_window', 'precision': 'window', 'open_at': {'epoch_seconds': now},
                 'close_at': {'epoch_seconds': now + 3600}, 'sources': ['willreset'], 'quote': 'private-marker'},
                {'kind': 'promised_reset', 'precision': 'label_only', 'label': 'tomorrow', 'sources': ['willreset']},
                {'kind': 'promised_reset', 'precision': 'window', 'close_at': {'epoch_seconds': True}, 'sources': ['willreset']},
                {'kind': 'promised_reset', 'precision': 'window', 'open_at': {'epoch_seconds': now + 10},
                 'close_at': {'epoch_seconds': now}, 'sources': ['willreset']}]}}}}
        result = backend.forecast_summary(source, now=now)
        self.assertEqual(result['targets'], [{'kind': 'typical_window', 'open_at': now, 'close_at': now + 3600, 'sources': ['WillReset']}])
        self.assertEqual(len(result['history']), 40)
        self.assertEqual(result['history'][0]['announced_at'], now)
        self.assertEqual(result['history'][0]['sources'], ['WillReset', 'Tibo Radar'])
        self.assertNotIn('private-marker', json.dumps(result))
        self.assertNotIn('tomorrow', json.dumps(result))

    def test_forecast_refresh_requests_history_even_when_cache_exists(self):
        from tests.test_reset_forecast import NORMALIZE
        from agent_meter.reset_forecast import normalize_history
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / 'reset-forecast.json'
            cache.write_text(json.dumps({'saved_at': 1000, 'rows': [], 'history': {}}), encoding='utf-8')
            history = normalize_history('willreset', [{'id': 'synthetic', 'announced_at': '2026-11-01T00:00:00Z', 'kind': 'reset'}])
            fetchers = {'willreset': {'forecast': lambda now: NORMALIZE['willreset'](), 'history': lambda: history}}
            with patch('windows.backend.default_fetchers', return_value=fetchers) as factories:
                result = backend.forecast_only(directory)
            factories.assert_called_once_with(with_history=True)
            self.assertEqual(result['history'][0]['kind'], 'reset')
            self.assertEqual(result['history'][0]['sources'], ['WillReset'])

    def test_minimax_account_is_opt_in_and_uses_fixed_service(self):
        payload = {'base_resp': {'status_code': 0}, 'model_remains': [{'model_name': 'general',
            'current_interval_remaining_percent': 65, 'end_time': 1800003600000}]}
        with tempfile.TemporaryDirectory() as root, patch.dict('os.environ', {
                'MINIMAX_TOKEN_PLAN_KEY': 'synthetic-test-key', 'MINIMAX_REGION': 'cn'}), \
             patch('agent_meter.minimax.get_json', return_value=payload) as request:
            off = backend.collect(account_only=True, home=root, disabled_accounts=frozenset({'codex', 'kimi', 'claude'}))
            self.assertEqual(off['other_accounts']['MiniMax Code']['status'], 'disabled')
            request.assert_not_called()
            on = backend.collect(account_only=True, home=root, disabled_accounts=frozenset({'codex', 'kimi', 'claude'}), enable_minimax=True)
            self.assertEqual(on['other_accounts']['MiniMax Code']['quota']['value'][0]['remaining_percent'], 65)
            self.assertEqual(request.call_args.args[0], 'https://www.minimax.cn/v1/token_plan/remains')
            self.assertNotIn('synthetic-test-key', json.dumps(on))
        with tempfile.TemporaryDirectory() as root, patch.dict('os.environ', {
                'MINIMAX_TOKEN_PLAN_KEY': 'synthetic-test-key', 'MINIMAX_REGION': 'unexpected'}), \
             patch('agent_meter.minimax.get_json') as request:
            with self.assertRaises(SourceError) as error:
                backend.minimax_quota(Path(root), 1800000000)
            self.assertEqual(error.exception.code, 'invalid_minimax_region')
            request.assert_not_called()

    def test_multiple_minimax_accounts_are_isolated_and_do_not_return_keys(self):
        accounts = backend.validate_account_input({'minimax_accounts': [
            {'label': '甲', 'region': 'cn', 'key': 'synthetic-one'},
            {'label': '乙', 'region': 'global', 'key': 'synthetic-two'},
            {'label': '丙', 'region': 'cn', 'key': None}]})
        payload = {'base_resp': {'status_code': 0}, 'model_remains': [{'model_name': 'general',
            'current_interval_remaining_percent': 65, 'end_time': 1800003600000}]}
        with tempfile.TemporaryDirectory() as root, patch('windows.backend.get_json', return_value=payload) as request:
            result = backend.collect(account_only=True, home=root, disabled_accounts=frozenset({'codex', 'kimi', 'claude'}),
                                     enable_minimax=True, saved_accounts=accounts)
        items = result['other_accounts']['MiniMax Code']
        self.assertEqual([item['label'] for item in items], ['甲', '乙', '丙'])
        self.assertEqual(items[2]['reason'], 'minimax_vault_credential_missing')
        self.assertEqual({call.args[0] for call in request.call_args_list}, {
            'https://www.minimax.cn/v1/token_plan/remains', 'https://www.minimax.io/v1/token_plan/remains'})
        self.assertNotIn('synthetic-one', json.dumps(result))
        self.assertNotIn('synthetic-two', json.dumps(result))
        with self.assertRaises(ValueError):
            backend.validate_account_input({'minimax_accounts': accounts + [accounts[0]]})
        with tempfile.TemporaryDirectory() as root, patch.dict('os.environ', {'MINIMAX_TOKEN_PLAN_KEY': 'synthetic-env-key'}), \
             patch.object(backend, 'minimax_quota') as legacy:
            result = backend.collect(account_only=True, home=root, disabled_accounts=frozenset({'codex', 'kimi', 'claude'}),
                                     enable_minimax=True, saved_accounts=[])
            self.assertEqual(result['other_accounts']['MiniMax Code']['reason'], 'minimax_no_saved_accounts')
            legacy.assert_not_called()

    def test_invalid_account_input_never_echoes_secret(self):
        with tempfile.TemporaryDirectory() as root:
            data = json.dumps({'minimax_accounts': [{'label': 'a', 'region': 'invalid', 'key': 'synthetic-secret'}]})
            run = subprocess.run([sys.executable, '-m', 'windows.backend', '--account-only', '--home', root,
                                  '--enable-minimax-account', '--account-input'], input=data, capture_output=True,
                                 text=True, encoding='utf-8', timeout=15)
            self.assertNotEqual(run.returncode, 0)
            self.assertNotIn('synthetic-secret', run.stdout + run.stderr)

    def test_saved_account_input_is_received_from_standard_input(self):
        with tempfile.TemporaryDirectory() as root:
            data = json.dumps({'minimax_accounts': [{'label': '测试账户', 'region': 'cn', 'key': None}]}, ensure_ascii=False)
            env = dict(os.environ, MINIMAX_TOKEN_PLAN_KEY='synthetic-env-key')
            run = subprocess.run([sys.executable, '-m', 'windows.backend', '--account-only', '--home', root,
                                  '--disable-codex-account', '--disable-kimi-account', '--disable-claude-account',
                                  '--enable-minimax-account', '--account-input'], input=data, capture_output=True,
                                 text=True, encoding='utf-8', env=env, timeout=15, check=True)
            result = json.loads(run.stdout)['other_accounts']['MiniMax Code']
            self.assertEqual(result[0]['label'], '测试账户')
            self.assertEqual(result[0]['reason'], 'minimax_vault_credential_missing')
            self.assertNotIn('synthetic-env-key', run.stdout + run.stderr)

    def test_claude_quota_uses_configured_file_and_fixed_service_without_exposing_token(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as config:
            token = 'synthetic-test-token'
            path = Path(config) / '.credentials.json'
            path.write_text(json.dumps({'claudeAiOauth': {'accessToken': token, 'expiresAt': 3000000000000, 'subscriptionType': 'max'}}), encoding='utf-8')
            response = {'five_hour': {'utilization': 25, 'resets_at': None}}
            with patch.dict('os.environ', {'CLAUDE_CONFIG_DIR': config}), \
                 patch('agent_meter.claude_code.get_json', return_value=response) as request:
                result = backend.claude_quota(Path(root), 1800000000)
            self.assertEqual(request.call_args.args[0], 'https://api.anthropic.com/api/oauth/usage')
            self.assertEqual(request.call_args.args[1], token)
            self.assertEqual(result['quota']['value'][0]['remaining_percent'], 75)
            self.assertEqual(result['subscription']['plan'], 'max')
            self.assertNotIn(token, json.dumps(result))

    def test_claude_missing_credentials_never_starts_keychain_or_network(self):
        with tempfile.TemporaryDirectory() as root, patch.dict('os.environ', {'CLAUDE_CONFIG_DIR': ''}), \
             patch('agent_meter.claude_code.get_json') as request, \
             patch('agent_meter.claude_code.subprocess.run') as keychain:
            with self.assertRaises(SourceError) as error:
                backend.claude_quota(Path(root), time.time())
            self.assertEqual(error.exception.code, 'claude_subscription_login_missing')
            request.assert_not_called()
            keychain.assert_not_called()

    def test_kimi_process_probe_does_not_terminate_process(self):
        child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
        try:
            self.assertTrue(process_exists(child.pid))
            self.assertIsNone(child.poll())
        finally:
            child.terminate(); child.wait(timeout=10)

    def test_kimi_existing_local_server_quota(self):
        token = 'synthetic-local-token'
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_GET(self):
                if self.path != '/api/v1/oauth/usage' or self.headers.get('Authorization') != 'Bearer ' + token:
                    self.send_error(401); return
                payload = {'code': 0, 'data': {'kind': 'ok', 'quota': {'usages': {
                    'limit5h': {'usedRatio': .25, 'resetAt': None}},
                    'extraUsage': {'balanceCents': 1234, 'currency': 'CNY'}}}}
                body = json.dumps(payload).encode()
                self.send_response(200); self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            with tempfile.TemporaryDirectory() as root, patch.dict('os.environ', {'KIMI_CODE_HOME': ''}):
                kimi_root = Path(root) / '.kimi-code'
                instances = kimi_root / 'server' / 'instances'; instances.mkdir(parents=True)
                (kimi_root / 'server.token').write_text(token, encoding='utf-8')
                (instances / 'test.json').write_text(json.dumps({'pid': os.getpid(), 'host': '127.0.0.1',
                                                                 'port': server.server_port}), encoding='utf-8')
                result = backend.kimi_quota(Path(root), time.time())
            self.assertEqual(result['quota']['value'][0]['remaining_percent'], 75)
            self.assertEqual(result['credits']['value']['amount'], '12.34')
            self.assertNotIn(token, json.dumps(result))
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=5)

    def test_minimax_reads_committed_wal_updates_on_windows(self):
        with tempfile.TemporaryDirectory() as root:
            db = Path(root) / '.minimax' / 'v2' / 'sqlite' / 'runtime-state.sqlite'
            db.parent.mkdir(parents=True)
            now = time.time()
            writer = sqlite3.connect(db)
            try:
                writer.execute('PRAGMA journal_mode=WAL')
                writer.execute('PRAGMA wal_autocheckpoint=0')
                writer.execute('CREATE TABLE local_runtime_token_usage (id INTEGER, session_id TEXT, turn_id TEXT, model TEXT, ts INTEGER, input_tokens INTEGER, output_tokens INTEGER, reasoning_tokens INTEGER, cache_read_tokens INTEGER, cache_write_tokens INTEGER)')
                row = (1, 's', 't', 'demo', int(now*1000)-1000, 10, 5, 0, 0, 0)
                writer.execute('INSERT INTO local_runtime_token_usage VALUES (?,?,?,?,?,?,?,?,?,?)', row)
                writer.commit()
                read = backend.histories(Path(root), now)['MiniMax Code']
                self.assertEqual(read()['value']['periods']['all']['totals']['total_tokens'], 15)
                writer.execute('INSERT INTO local_runtime_token_usage VALUES (?,?,?,?,?,?,?,?,?,?)', (2, 's', 'u', 'demo', row[4], 20, 3, 0, 0, 0))
                writer.commit()
                self.assertEqual(read()['value']['periods']['all']['totals']['total_tokens'], 38)
            finally:
                writer.close()

    def test_custom_kimi_and_opencode_locations(self):
        with tempfile.TemporaryDirectory() as root:
            home = Path(root) / 'home'
            xdg = Path(root) / 'data'
            kimi = Path(root) / 'kimi-custom'
            variables = {'KIMI_CODE_HOME': str(kimi), 'XDG_DATA_HOME': str(xdg), 'OPENCODE_DB': 'custom.db'}
            with patch.dict('os.environ', variables), \
                 patch.object(backend, 'collect_kimi_tokens', return_value={'status': 'available'}) as kimi_read, \
                 patch.object(backend, 'collect_opencode_tokens', return_value={'metrics': {'tokens': {'status': 'available'}}}) as opencode_read:
                jobs = backend.histories(home, 123)
                jobs['Kimi Code'](); jobs['OpenCode']()
                kimi_read.assert_called_once_with(home, 123, sessions_root=kimi / 'sessions')
                opencode_read.assert_called_once_with(xdg / 'opencode' / 'custom.db', 123)
            with patch.dict('os.environ', {'OPENCODE_DB': ':memory:'}):
                result = backend.guarded(backend.histories(home, 123)['OpenCode'])
            self.assertEqual(result['reason'], 'opencode_memory_database')

    def test_opencode_v2_rows_mark_history_partial(self):
        with tempfile.TemporaryDirectory() as root:
            db = Path(root) / 'opencode.db'
            now = time.time()
            message = {'role': 'assistant', 'modelID': 'test', 'tokens':
                       {'input': 10, 'output': 4, 'reasoning': 0, 'cache': {'read': 0, 'write': 0}}}
            conn = sqlite3.connect(db)
            conn.execute('CREATE TABLE message(time_created INTEGER, data TEXT)')
            conn.execute('INSERT INTO message VALUES (?, ?)', (int(now * 1000) - 1000, json.dumps(message)))
            conn.execute('CREATE TABLE session_message(id TEXT)')
            conn.execute("INSERT INTO session_message VALUES ('new-schema')")
            conn.commit(); conn.close()
            with patch.dict('os.environ', {'OPENCODE_DB': str(db)}):
                result = backend.histories(Path(root), now)['OpenCode']()
            self.assertEqual((result['status'], result['reason']), ('partial', 'opencode_v2_partial'))
            self.assertEqual(result['value']['periods']['all']['totals']['total_tokens'], 14)

    def test_qoder_credits_are_separate_and_keep_decimal_strings(self):
        source = {'version': 1, 'observed_at': 1, 'account': {'status': 'disabled'}, 'history': {},
                  'local_credits': {'Qoder CN': {'status': 'available', 'value': {'periods': {
                      'today': {'totals': {'requests': 2, 'credits': '1.250', 'billable_credits': '0.500'}},
                      'all': {'totals': {'requests': 2, 'credits': '1.250', 'billable_credits': '0.500'}}}}}}}
        result = backend.compact_history(source)
        self.assertEqual(result['history'], {})
        self.assertEqual(result['local_credits']['Qoder CN']['value']['periods']['all']['totals'],
                         {'credits': '1.250', 'billable_credits': '0.500'})
        source['local_credits']['Qoder CN'] = {'status': 'error', 'reason': 'read_failed', 'value': None}
        self.assertEqual(backend.compact_history(source)['local_credits']['Qoder CN'],
                         {'status': 'error', 'reason': 'read_failed', 'value': None})

    def test_empty_history_directory_is_not_reported_as_zero_usage(self):
        metric = {'version': 1, 'observed_at': 1, 'account': {'status': 'disabled'}, 'history':
                  {'Codex': {'status': 'available', 'value': {'periods': {'all': {'totals':
                      {'requests': 0, 'total_tokens': 0}}}}}}}
        item = backend.compact_history(metric)['history']['Codex']
        self.assertEqual(item, {'status': 'not_provided', 'reason': 'history_no_usage_records', 'value': None})
        metric['history']['Codex'].update(status='partial', reason='codex_rollout_unreadable')
        item = backend.compact_history(metric)['history']['Codex']
        self.assertEqual(item, {'status': 'partial', 'reason': 'codex_rollout_unreadable', 'value': None})

    def test_worker_output_only_contains_panel_fields(self):
        source = {'version': 1, 'observed_at': 1, 'account': {'status': 'disabled'}, 'history':
                  {'Codex': {'status': 'partial', 'reason': 'some_skipped', 'value':
                     {'daily_buckets': [{'private_detail': 'not sent'}], 'periods': {
                         'today': {'totals': {'total_tokens': 12, 'cache_read': 8}, 'groups': [{'model': 'example'}]},
                         '7d': {'totals': {'total_tokens': 20}}, '30d': {'totals': {'total_tokens': 35}},
                         'all': {'totals': {'total_tokens': 60}}}}}}}
        result = backend.compact_history(source)['history']['Codex']
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['reason'], 'some_skipped')
        self.assertEqual(result['value'], {'periods': {'today': {'totals': {'total_tokens': 12, 'cache_read': 8},
                                                                 'groups': [], 'groups_truncated': False, 'groups_incomplete': True},
                                                       '7d': {'totals': {'total_tokens': 20}},
                                                       '30d': {'totals': {'total_tokens': 35}},
                                                       'all': {'totals': {'total_tokens': 60}}}, 'daily_trend': None})
        self.assertNotIn('not sent', json.dumps(result))

    def test_worker_refreshes_changed_session_and_rejects_unknown_commands(self):
        stamp = datetime.now(timezone.utc).isoformat()
        def event(n):
            return {'timestamp': stamp, 'type': 'event_msg', 'payload': {'type': 'token_count', 'info':
                    {'total_token_usage': {'input_tokens': n, 'cached_input_tokens': 0,
                                           'output_tokens': 0, 'reasoning_output_tokens': 0}}}}
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / '.codex' / 'sessions' / 'sample.jsonl'
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(event(100)) + '\n', encoding='utf-8')
            env = dict(os.environ, CODEX_HOME='', CLAUDE_CONFIG_DIR='', DSH_HOME='', KIMI_CODE_HOME='', XDG_DATA_HOME='', OPENCODE_DB='')
            worker = subprocess.Popen([sys.executable, '-m', 'windows.backend', '--history-worker', '--home', root],
                                      stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                      text=True, encoding='utf-8', env=env)
            try:
                def refresh(prefix=''):
                    worker.stdin.write(prefix + '{"command":"refresh"}\n'); worker.stdin.flush()
                    return json.loads(worker.stdout.readline())['history']['Codex']['value']['periods']['all']['totals']['total_tokens']
                self.assertEqual(refresh('\ufeff'), 100)
                with path.open('a', encoding='utf-8') as f:
                    f.write(json.dumps(event(230)) + '\n')
                self.assertEqual(refresh(), 230)
                worker.stdin.write('{"command":"delete"}\n'); worker.stdin.flush()
                self.assertEqual(json.loads(worker.stdout.readline()), {'error': 'invalid_request'})
                worker.stdin.close()
                self.assertEqual(worker.wait(timeout=10), 0)
            finally:
                if worker.poll() is None:
                    worker.kill(); worker.wait(timeout=10)
                if not worker.stdin.closed:
                    worker.stdin.close()
                worker.stdout.close(); worker.stderr.close()

    def test_model_groups_are_bounded_sorted_and_exclude_other_fields(self):
        names = list(backend.PriceTable('USD', {}, set()).index.values())[:25]
        rows = [{'model': name, 'total_tokens': n, 'private_detail': '不应发送'} for n, name in enumerate(names)]
        rows.extend([{'model': 'bad', 'total_tokens': -1}, {'model': 'bad', 'total_tokens': True}])
        source = {'version': 1, 'observed_at': 1, 'account': {}, 'history': {'测试': {
            'status': 'available', 'value': {'periods': {'7d': {'totals': {'total_tokens': 300}, 'groups': rows}}}}}}
        period = backend.compact_history(source)['history']['测试']['value']['periods']['7d']
        self.assertEqual(len(period['groups']), 20)
        self.assertEqual(period['groups'][0], {'model': names[24], 'total_tokens': 24})
        self.assertTrue(period['groups_truncated'])
        self.assertTrue(period['groups_incomplete'])
        self.assertNotIn('不应发送', json.dumps(period, ensure_ascii=False))

    def test_model_groups_cover_periods_merge_aliases_and_hide_unknown_names(self):
        def group(model, count):
            return {'model': model, 'app': 'codex', 'fresh_input': count, 'cache_read': 0,
                    'cache_write': 0, 'output': 0, 'reasoning': 0, 'total_tokens': count, 'path': 'private-path'}
        periods = {}
        for period in ('today', '7d', '30d', 'all'):
            periods[period] = {'totals': {'total_tokens': 1500010}, 'groups': [
                group('gpt-5.3-codex', 1000000), group('provider/gpt-5-3-codex', 500000), group('private-unknown-model', 10)]}
        source = {'version': 1, 'observed_at': 1, 'account': {}, 'history': {'Codex': {'status': 'available', 'value': {'periods': periods}}}}
        item = backend.compact_history(source)['history']['Codex']
        for period in periods:
            value = item['value']['periods'][period]
            self.assertEqual(value['groups'][0], {'model': 'gpt-5.3-codex', 'total_tokens': 1500000})
            self.assertEqual(value['groups'][1], {'model': '未识别模型', 'total_tokens': 10})
            self.assertTrue(value['groups_incomplete'])
            self.assertEqual(Decimal(value['model_costs']['gpt-5.3-codex']['amount_usd']), Decimal('2.625'))
            self.assertFalse(value['model_costs']['gpt-5.3-codex']['partial'])
        self.assertNotIn('private-unknown-model', json.dumps(item, ensure_ascii=False))
        self.assertNotIn('private-path', json.dumps(item, ensure_ascii=False))
        # 即使用户自定义价格能够计价，也不能把自定义模型名称暴露到面板投影中。
        custom = {'version': 1, 'observed_at': 1, 'account': {}, 'history': {'Codex': {'status': 'available', 'value': {'periods': {
            'today': {'totals': {'total_tokens': 10}, 'groups': [group('private-unknown-model', 10)]}}}}}}
        table = backend.PriceTable('USD', {'private-unknown-model': (3, 0, 0, 0)}, set())
        projected = backend.compact_history(custom, table)['history']['Codex']['value']['periods']['today']
        self.assertEqual(projected['groups'][0]['model'], '未识别模型')
        self.assertTrue(projected['model_costs']['未识别模型']['partial'])
        self.assertNotIn('private-unknown-model', json.dumps(projected, ensure_ascii=False))

    def test_daily_trend_uses_beijing_dates_and_marks_partial_sources(self):
        now = datetime(2026, 11, 14, 16, 30, tzinfo=timezone.utc).timestamp()
        source = {'version': 1, 'observed_at': now, 'account': {}, 'history': {
            '甲': {'status': 'available', 'value': {'periods': {}, 'daily_buckets': [
                {'date': '2026-11-14', 'tokens': 15}, {'date': '2026-11-15', 'tokens': 7},
                {'date': '2026-11-08', 'tokens': 500}, {'date': '2026-11-16', 'tokens': 500}]}},
            '乙': {'status': 'partial', 'value': {'periods': {}, 'daily_buckets': [
                {'date': '2026-11-15', 'tokens': 3}]}}}}
        trend = backend.compact_history(source)['daily_trend']
        self.assertEqual(trend['days'][0], {'date': '2026-11-09', 'tokens': 0})
        self.assertEqual(trend['days'][-2:], [{'date': '2026-11-14', 'tokens': 15},
                                              {'date': '2026-11-15', 'tokens': 10}])
        self.assertEqual(trend['sources'], 2)
        self.assertTrue(trend['incomplete'])

    def test_account_card_trend_is_bounded_and_excludes_private_fields(self):
        now = datetime(2026, 11, 14, 16, 30, tzinfo=timezone.utc).timestamp()
        source = {'version': 1, 'observed_at': now, 'account': {}, 'history': {'Codex': {
            'status': 'partial', 'value': {'periods': {'today': {'totals': {'total_tokens': 15}}},
                'daily_buckets': [{'date': '2026-11-14', 'tokens': 15, 'session': 'private'},
                                  {'date': '2026-11-15', 'tokens': 7},
                                  {'date': '2026-11-15', 'tokens': 3},
                                  {'date': '2026-10-16', 'tokens': 99},
                                  {'date': '2026-11-16', 'tokens': 99},
                                  {'date': '2026-11-14', 'tokens': True}]}}}}
        item = backend.compact_history(source)['history']['Codex']
        trend = item['value']['daily_trend']
        self.assertEqual(len(trend['days']), 30)
        self.assertEqual(trend['days'][0], {'date': '2026-10-17', 'tokens': 0})
        self.assertEqual(trend['days'][-2:], [{'date': '2026-11-14', 'tokens': 15},
                                              {'date': '2026-11-15', 'tokens': 10}])
        self.assertTrue(trend['incomplete'])
        self.assertNotIn('private', json.dumps(item))
        self.assertIsNone(backend.source_daily_trend({'status': 'available', 'value': {}}, now))

    def test_calendar_report_uses_natural_periods_and_marks_missing_data(self):
        now = datetime(2026, 1, 1, 4, 0, tzinfo=timezone.utc).timestamp()
        source = {'version': 1, 'observed_at': now, 'account': {}, 'history': {
            '甲': {'status': 'available', 'value': {'periods': {}, 'daily_buckets': [
                {'date': '2025-12-15', 'tokens': 30}, {'date': '2025-12-28', 'tokens': 50},
                {'date': '2025-12-30', 'tokens': 100}, {'date': '2026-01-01', 'tokens': 200},
                {'date': '2026-01-02', 'tokens': 300}]}},
            '乙': {'status': 'partial', 'reason': 'some_skipped', 'value': {'periods': {}}}}}
        report = backend.compact_history(source)['calendar_report']
        self.assertEqual(report['periods']['week']['current_start'], '2025-12-29')
        self.assertEqual(report['periods']['week']['current_tokens'], 300)
        self.assertEqual(report['periods']['week']['previous_tokens'], 50)
        self.assertEqual(report['periods']['week']['comparable_days'], 3)
        self.assertEqual(report['periods']['week']['current_comparable_tokens'], 100)
        self.assertEqual(report['periods']['week']['previous_comparable_tokens'], 0)
        self.assertEqual(report['periods']['month']['current_start'], '2026-01-01')
        self.assertEqual(report['periods']['month']['current_tokens'], 200)
        self.assertEqual(report['periods']['month']['previous_tokens'], 180)
        self.assertEqual(report['periods']['month']['comparable_days'], 0)
        self.assertEqual(report['sources'], 1)
        self.assertTrue(report['incomplete'])

    def test_calendar_comparison_caps_to_shorter_previous_month(self):
        now = datetime(2026, 3, 31, 4, tzinfo=timezone.utc).timestamp()
        source = {'observed_at': now, 'history': {'Codex': {'status': 'available', 'value': {'periods': {}, 'daily_buckets': [
            {'date': '2026-02-28', 'tokens': 4}, {'date': '2026-03-28', 'tokens': 5},
            {'date': '2026-03-29', 'tokens': 6}, {'date': '2026-03-31', 'tokens': 8}]}}}}
        month = backend.calendar_report(source)['periods']['month']
        self.assertEqual(month['comparable_days'], 28)
        self.assertEqual(month['previous_comparable_tokens'], 4)
        self.assertEqual(month['current_comparable_tokens'], 5)
        self.assertEqual(month['current_tokens'], 19)

    def test_recent_activity_summarizes_without_project_paths_or_session_ids(self):
        now = 1800000000
        with tempfile.TemporaryDirectory() as root, patch.dict('os.environ', {
                'CODEX_HOME': '', 'CLAUDE_CONFIG_DIR': '', 'DSH_HOME': '', 'KIMI_CODE_HOME': '',
                'XDG_DATA_HOME': '', 'OPENCODE_DB': ''}):
            folder = Path(root) / '.codex'
            folder.mkdir(parents=True)
            db = sqlite3.connect(folder / 'state_5.sqlite')
            try:
                db.execute('CREATE TABLE threads (id TEXT, cwd TEXT, created_at INTEGER, updated_at INTEGER, model TEXT)')
                db.execute('INSERT INTO threads VALUES (?,?,?,?,?)', ('synthetic-private-session', 'C:/synthetic-private-project', now - 3600, now - 30, 'synthetic-model'))
                db.commit()
            finally:
                db.close()
            raw = backend.collect_activity(backend.activity_config(Path(root)), now=now)
            activity = backend.compact_activity(raw, now)
        codex = next(item for item in activity['apps'] if item['name'] == 'Codex')
        self.assertEqual((codex['sessions'], codex['recent_updates'], codex['last_updated']), (1, 1, now - 30))
        self.assertNotIn('synthetic-private-session', json.dumps(activity))
        self.assertNotIn('synthetic-private-project', json.dumps(activity))
        self.assertNotIn('synthetic-model', json.dumps(activity))

    def test_recent_activity_marks_unsupported_or_failed_sources_incomplete(self):
        result = backend.compact_activity({'activities': [], 'sources_meta': {
            'one': {'status': 'not_connected', 'reason': 'unsupported_schema'},
            'two': {'status': 'not_connected', 'reason': 'sessions_not_found'}}}, 1800000000)
        self.assertEqual(result['status'], 'partial')
        v2 = backend.compact_activity({'activities': [], 'sources_meta': {
            'opencode': {'status': 'partial', 'reason': 'opencode_v2_activity_partial'}}}, 1800000000)
        self.assertEqual((v2['status'], v2['sources']['OpenCode']), ('partial', 'partial'))

    def test_activity_coverage_exposes_only_safe_statuses(self):
        result = backend.compact_activity({'activities': [], 'sources_meta': {
            'codex': {'status': 'available', 'path': 'private-path'},
            'kimi': {'status': 'not_connected', 'reason': 'kimi_sessions_not_found'},
            'claude': {'status': 'error', 'reason': 'private-error'},
            'opencode': {'status': 'not_connected', 'reason': 'disabled_by_user'},
            'unknown': {'status': 'available'}}}, 1800000000)
        self.assertEqual(result['sources'], {'Codex': 'available', 'Kimi Code': 'not_found',
                                             'Claude Code': 'unavailable', 'OpenCode': 'disabled'})
        self.assertNotIn('private', json.dumps(result))
        self.assertNotIn('unknown', json.dumps(result))
        malformed = backend.compact_activity({'activities': [{'app': 'codex', 'last_event_at': {'epoch_seconds': True}}],
                                              'sources_meta': {'codex': {'status': 'available'}}}, 1800000000)
        self.assertEqual(malformed['sources']['Codex'], 'partial')
        self.assertEqual(malformed['status'], 'partial')
        self.assertEqual(malformed['apps'], [])

    def test_activity_only_uses_isolated_home_and_rejects_account_mode(self):
        now = int(time.time())
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root) / '.codex'
            folder.mkdir(parents=True)
            db = sqlite3.connect(folder / 'state_5.sqlite')
            try:
                db.execute('CREATE TABLE threads (id TEXT, cwd TEXT, created_at INTEGER, updated_at INTEGER, model TEXT)')
                db.execute('INSERT INTO threads VALUES (?,?,?,?,?)', ('private-session', 'C:/private-project', now - 60, now - 20, 'private-model'))
                db.commit()
            finally:
                db.close()
            env = dict(os.environ, CODEX_HOME='', CLAUDE_CONFIG_DIR='', DSH_HOME='', KIMI_CODE_HOME='', XDG_DATA_HOME='', OPENCODE_DB='')
            command = [sys.executable, '-m', 'windows.backend', '--activity-only', '--home', root]
            run = subprocess.run(command, env=env, capture_output=True, text=True, encoding='utf-8', timeout=30, check=True)
            result = json.loads(run.stdout)
            self.assertEqual(result['sources']['Codex'], 'available')
            self.assertEqual(next(row for row in result['apps'] if row['name'] == 'Codex')['sessions'], 1)
            self.assertNotIn('private-', run.stdout)
            self.assertNotIn('account', result)
            self.assertNotIn('history', result)
            conflict = subprocess.run(command + ['--account-only'], env=env, capture_output=True, timeout=30)
            self.assertEqual(conflict.returncode, 2)

    def test_estimated_cost_uses_known_groups_and_marks_unknown_models(self):
        priced = {'model': 'gpt-5.3-codex', 'app': 'codex', 'fresh_input': 1000000,
                  'cache_read': 0, 'cache_write': 0, 'output': 0, 'reasoning': 0, 'total_tokens': 1000000}
        unknown = {'model': 'unknown-private-model', 'app': 'codex', 'fresh_input': 10,
                   'cache_read': 0, 'cache_write': 0, 'output': 0, 'reasoning': 0, 'total_tokens': 10}
        source = {'version': 1, 'observed_at': 1, 'account': {}, 'history': {'Codex': {
            'status': 'available', 'value': {'periods': {'today': {
                'totals': {'total_tokens': 1000010}, 'groups': [priced, unknown]}}}}}}
        item = backend.compact_history(source)['history']['Codex']
        self.assertEqual(Decimal(item['estimate']['amount_usd']), Decimal('1.75'))
        self.assertTrue(item['estimate']['partial'])
        self.assertNotIn('unknown-private-model', json.dumps(item))
        source['history']['Codex']['value']['periods']['today']['groups'] = [unknown]
        self.assertNotIn('estimate', backend.compact_history(source)['history']['Codex'])
        deepseek = dict(priced, model='deepseek-flash')
        source['history']['Codex']['value']['periods']['today'] = {
            'totals': {'total_tokens': 1000000}, 'groups': [deepseek]}
        self.assertTrue(backend.compact_history(source)['history']['Codex']['estimate']['partial'])

    def test_estimated_cost_is_independent_for_each_period(self):
        def group(tokens, model='gpt-5.3-codex'):
            return {'model': model, 'app': 'codex', 'fresh_input': tokens, 'cache_read': 0,
                    'cache_write': 0, 'output': 0, 'reasoning': 0, 'total_tokens': tokens}
        periods = {
            'today': {'totals': {'total_tokens': 1000000}, 'groups': [group(1000000)]},
            '7d': {'totals': {'total_tokens': 2000000}, 'groups': [group(2000000)]},
            '30d': {'totals': {'total_tokens': 5}, 'groups': [group(5, 'private-unknown-model')]},
            'all': {'totals': {'total_tokens': 3000000}, 'groups': [group(2000000)]},
        }
        source = {'version': 1, 'observed_at': 1, 'account': {}, 'history': {'Codex': {
            'status': 'available', 'value': {'periods': periods}}}}
        item = backend.compact_history(source)['history']['Codex']
        self.assertEqual(Decimal(item['estimates']['today']['amount_usd']), Decimal('1.75'))
        self.assertEqual(Decimal(item['estimates']['7d']['amount_usd']), Decimal('3.5'))
        self.assertNotIn('30d', item['estimates'])
        self.assertTrue(item['estimates']['all']['partial'])
        self.assertFalse(item['estimates']['7d']['partial'])
        self.assertEqual(item['estimate'], item['estimates']['today'])
        self.assertNotIn('private-unknown-model', json.dumps(item))

    def test_custom_price_overrides_and_corrupt_file_suppresses_estimates(self):
        group = {'model': 'gpt-5.3-codex', 'app': 'codex', 'fresh_input': 1000000,
                 'cache_read': 0, 'cache_write': 0, 'output': 0, 'reasoning': 0, 'total_tokens': 1000000}
        source = {'version': 1, 'observed_at': 1, 'account': {}, 'history': {'Codex': {
            'status': 'available', 'value': {'periods': {'today': {
                'totals': {'total_tokens': 1000000}, 'groups': [group]}}}}}}
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'prices.json'
            path.write_text(json.dumps({'currency': 'USD', 'models': {'gpt-5.3-codex': {
                'input': 3, 'cache_read': 0.1, 'cache_write': 0, 'output': 9}}}), encoding='utf-8')
            item = backend.compact_history(source, backend.load_price_table(root))['history']['Codex']
            self.assertEqual(Decimal(item['estimate']['amount_usd']), Decimal('3'))
            path.write_text('{broken', encoding='utf-8')
            result = backend.compact_history(source, backend.load_price_table(root))
            self.assertEqual(result['price_status'], 'invalid')
            self.assertNotIn('estimate', result['history']['Codex'])
            path.write_text('{"currency":"USD","models":{},"future":true}', encoding='utf-8')
            self.assertIsNone(backend.load_price_table(root))
            path.write_text('{"currency":"USD","currency":"USD","models":{}}', encoding='utf-8')
            self.assertIsNone(backend.load_price_table(root))

    def test_history_worker_uses_the_explicit_price_directory(self):
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as prices:
            (Path(prices) / 'prices.json').write_text('broken', encoding='utf-8')
            env = dict(os.environ, CODEX_HOME='', CLAUDE_CONFIG_DIR='', DSH_HOME='', KIMI_CODE_HOME='', XDG_DATA_HOME='', OPENCODE_DB='')
            result = subprocess.run([sys.executable, '-m', 'windows.backend', '--history-worker', '--home', home,
                                     '--prices-dir', prices], input='{"command":"refresh"}\n', env=env,
                                    check=True, capture_output=True, text=True, encoding='utf-8', timeout=15)
            self.assertEqual(json.loads(result.stdout)['price_status'], 'invalid')

    def test_account_only_does_not_start_history_scan(self):
        with tempfile.TemporaryDirectory() as root, patch.dict('os.environ', {'KIMI_CODE_HOME': '', 'CLAUDE_CONFIG_DIR': ''}), \
             patch.object(backend, 'histories', side_effect=AssertionError('history scan called')), \
             patch.object(backend, 'codex_binary', return_value='codex.exe'), \
             patch.object(backend, 'quota', return_value={'status': 'available'}):
            result = backend.collect(account_only=True, home=root)
        self.assertEqual(result['account']['status'], 'available')
        self.assertEqual(result['history'], {})

    def test_disabled_accounts_never_read_credentials_or_contact_services(self):
        with tempfile.TemporaryDirectory() as root, \
             patch.object(backend, 'codex_binary') as codex, \
             patch.object(backend, 'kimi_quota') as kimi, \
             patch.object(backend, 'claude_quota') as claude:
            result = backend.collect(account_only=True, home=root,
                                     disabled_accounts=frozenset({'codex', 'kimi', 'claude'}))
            self.assertEqual(result['account']['reason'], 'disabled_by_user')
            self.assertEqual(result['other_accounts']['Kimi Code']['status'], 'disabled')
            self.assertEqual(result['other_accounts']['Claude Code']['status'], 'disabled')
            codex.assert_not_called()
            kimi.assert_not_called()
            claude.assert_not_called()

    def test_account_disable_flags_apply_to_backend_process(self):
        with tempfile.TemporaryDirectory() as root:
            result = subprocess.run([sys.executable, '-m', 'windows.backend', '--account-only', '--home', root,
                                     '--disable-codex-account', '--disable-kimi-account', '--disable-claude-account'],
                                    check=True, capture_output=True, text=True, encoding='utf-8', timeout=15)
        output = json.loads(result.stdout)
        self.assertEqual(output['account']['status'], 'disabled')
        self.assertEqual(output['other_accounts']['Kimi Code']['status'], 'disabled')
        self.assertEqual(output['other_accounts']['Claude Code']['status'], 'disabled')
        self.assertEqual(output['other_accounts']['MiniMax Code']['status'], 'disabled')
        with tempfile.TemporaryDirectory() as root:
            env = dict(os.environ, MINIMAX_TOKEN_PLAN_KEY='')
            result = subprocess.run([sys.executable, '-m', 'windows.backend', '--account-only', '--home', root,
                                     '--disable-codex-account', '--disable-kimi-account', '--disable-claude-account',
                                     '--enable-minimax-account'], env=env, check=True, capture_output=True,
                                    text=True, encoding='utf-8', timeout=15)
        self.assertEqual(json.loads(result.stdout)['other_accounts']['MiniMax Code']['reason'], 'minimax_credential_not_connected')

    def test_missing_histories_are_not_zero(self):
        with tempfile.TemporaryDirectory() as root, patch.dict('os.environ', {'CODEX_HOME': '', 'CLAUDE_CONFIG_DIR': '', 'DSH_HOME': '', 'KIMI_CODE_HOME': '', 'XDG_DATA_HOME': '', 'OPENCODE_DB': ''}):
            result = backend.collect(local_only=True, home=root)
        self.assertEqual(result['account']['status'], 'disabled')
        for item in result['history'].values():
            self.assertEqual(item['status'], 'unavailable')
            self.assertIsNone(item['value'])

    @unittest.skipUnless(zstandard is not None, 'python-zstandard is not installed')
    def test_compressed_codex_usage(self):
        event = {'timestamp': (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat(), 'type': 'event_msg',
                 'payload': {'type': 'token_count', 'info': {'total_token_usage':
                     {'input_tokens': 100, 'cached_input_tokens': 40, 'output_tokens': 20, 'reasoning_output_tokens': 0}}}}
        with tempfile.TemporaryDirectory() as root, patch.dict('os.environ', {'CODEX_HOME': '', 'CLAUDE_CONFIG_DIR': '', 'DSH_HOME': '', 'KIMI_CODE_HOME': '', 'XDG_DATA_HOME': '', 'OPENCODE_DB': ''}):
            folder = Path(root) / '.codex' / 'sessions'
            folder.mkdir(parents=True)
            (folder / 'synthetic.jsonl.zst').write_bytes(zstandard.ZstdCompressor().compress((json.dumps(event) + '\n').encode()))
            result = backend.collect(local_only=True, home=root)
        codex = result['history']['Codex']
        self.assertEqual(codex['status'], 'available')
        totals = codex['value']['periods']['all']['totals']
        self.assertEqual((totals['fresh_input'], totals['cache_read'], totals['output']), (60, 40, 20))

    def test_quota_read_is_limited_to_read_only_rpc(self):
        class FakeRPC:
            def __init__(self, binary, timeout): pass
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def call(self, method, params):
                self.method = method
                self.params = params
                self.assertion()
                return {'rateLimits': {'primary': {'usedPercent': 25, 'windowDurationMins': 300, 'resetsAt': None}}}
            def assertion(self):
                assert self.method == 'account/rateLimits/read'
        with patch.object(backend, 'CodexRPC', FakeRPC):
            result = backend.quota('unused', 1794600000)
        self.assertEqual(result['quota']['value'][0]['remaining_percent'], 75)

    def test_provider_errors_are_sanitized(self):
        def fail(): raise SourceError('rpc_timeout')
        self.assertEqual(backend.guarded(fail), {'status': 'unavailable', 'reason': 'rpc_timeout', 'value': None})


if __name__ == '__main__':
    unittest.main()
