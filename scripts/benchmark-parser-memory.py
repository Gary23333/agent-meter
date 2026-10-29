"""Hermetic before/after memory probe; no real accounts or conversation data.

Run with Python 3.14; optionally --module-file a saved agy_tokens.py baseline.
The fixture includes opaque protobuf fields to simulate large session metadata.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
import tracemalloc

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent_meter import agy_tokens
from tests.test_agy_tokens import bytes_field, gen_metadata, step_metadata, usage

parser = argparse.ArgumentParser()
parser.add_argument("--module-file", type=Path)
parser.add_argument("--rows", type=int, default=1000)
args = parser.parse_args()
module = agy_tokens
if args.module_file:
    spec = importlib.util.spec_from_file_location("agent_meter._benchmark_agy", args.module_file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp) / "fixture.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE steps(idx INTEGER PRIMARY KEY, step_type INTEGER, metadata BLOB)")
        conn.execute("CREATE TABLE gen_metadata(idx INTEGER PRIMARY KEY, data BLOB)")
        padding = bytes_field(99, b"x" * 65536)
        for index in range(args.rows):
            conn.execute("INSERT INTO steps VALUES(?,15,?)", (index, step_metadata(1700000000 + index, usage(1000, 100, 20)) + padding))
            conn.execute("INSERT INTO gen_metadata VALUES(?,?)", (index, gen_metadata("fixture-model") + padding))
    tracemalloc.start()
    start = time.perf_counter()
    records = module._parse_conversation(path)
    seconds = time.perf_counter() - start
    retained, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    print(json.dumps({"rows": len(records), "seconds": round(seconds, 3),
                      "python_peak_mib": round(peak / 1048576, 3),
                      "python_retained_mib": round(retained / 1048576, 3),
                      "result_sha256": hashlib.sha256(json.dumps(records).encode()).hexdigest()}))
