import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock, patch

from agent_meter.record_cache import RecordCache
from agent_meter import cli_sessions, kimi_tokens
from tests import test_cli_sessions as fixtures


class RecordCacheTests(unittest.TestCase):
    def test_budget_eviction_and_oversized_records_preserve_results(self):
        cache = RecordCache(max_bytes=1500, max_entries=2)
        with tempfile.TemporaryDirectory() as tmp:
            paths = [Path(tmp) / str(i) for i in range(4)]
            for p in paths:
                p.touch()
            parser = Mock(return_value=["x" * 250])
            for p in paths:
                self.assertEqual(cache.read(p, parser, "a"), ["x" * 250])
                self.assertLessEqual(cache.bytes, cache.max_bytes)
            self.assertLessEqual(len(cache._entries), 2)
            parser.return_value = ["y" * 2000]
            self.assertEqual(cache.read(paths[0], parser, "large"), parser.return_value)
            count = parser.call_count
            cache.read(paths[0], parser, "large")
            self.assertEqual(parser.call_count, count + 1)

    def test_namespaces_pruning_updates_and_concurrent_access(self):
        cache = RecordCache()
        with tempfile.TemporaryDirectory() as tmp:
            paths = [Path(tmp) / str(i) for i in range(8)]
            for p in paths:
                p.write_text("first")
            with ThreadPoolExecutor(max_workers=8) as pool:
                rows = list(pool.map(lambda p: cache.read(p, Path.read_text, str(p)), paths))
            self.assertEqual(rows, ["first"] * 8)
            cache.prune(set(), str(paths[0]))
            self.assertEqual(len(cache._entries), 7)
            parser = Mock(return_value="unexpected")
            self.assertEqual(cache.read(paths[1], parser, str(paths[1])), "first")
            parser.assert_not_called()
            paths[1].write_text("second version")
            self.assertEqual(cache.read(paths[1], Path.read_text, str(paths[1])), "second version")
            cache.clear()
            self.assertEqual(cache.bytes, 0)

    def test_codex_and_claude_do_not_evict_each_others_files(self):
        cli_sessions._cache.clear()
        with tempfile.TemporaryDirectory() as tmp:
            roots = fixtures.CodexTests().dir(tmp)
            claude = fixtures.ClaudeTests().records(tmp)
            before = cli_sessions.load_codex(*roots)
            cli_sessions.load_claude(claude)
            with patch.object(cli_sessions, "_parse_codex_file", wraps=cli_sessions._parse_codex_file) as parser:
                parser.__name__ = "_parse_codex_file"
                self.assertEqual(cli_sessions.load_codex(*roots), before)
                parser.assert_not_called()

    def test_kimi_cli_and_desktop_keep_separate_roots(self):
        kimi_tokens._cache.clear()
        with tempfile.TemporaryDirectory() as tmp:
            roots = [Path(tmp) / name for name in ("cli", "desktop")]
            for root in roots:
                path = root / "s/agents/a/wire.jsonl"
                path.parent.mkdir(parents=True)
                path.write_text('{"type":"usage.record","usageScope":"turn","time":1000,"usage":{"output":2}}\n')
                kimi_tokens.load_records(root)
            with patch.object(kimi_tokens, "_parse_file", side_effect=AssertionError("cache missed")):
                for root in roots:
                    self.assertEqual(kimi_tokens.load_records(root)[0][0][3], 2)
