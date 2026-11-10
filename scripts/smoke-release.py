"""Validate a relocated release backend using synthetic data, without accounts."""
import json
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))

backend = Path(sys.argv[1]).resolve()
output = Path(sys.argv[2]).resolve()
with tempfile.TemporaryDirectory(prefix="release-smoke-", dir=root / ".runtime") as temp:
    work = Path(temp)
    store = work / "imported-history.json"
    today = datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
    store.write_text(json.dumps({"schema": 1, "imported_at": int(time.time()),
                                 "detail": [], "daily": [["codex", "gpt-5.4", today, 1, 100, 20, 0, 0]],
                                 "apps": {}}))
    config = work / "config.json"
    config.write_text(json.dumps({"home": str(work), "app_roots": [],
        "history_store": str(store), "runtime_dir": str(work / ".runtime")}))
    env = {"HOME": str(work), "PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LANG": "en_US.UTF-8"}
    def run(*arguments):
        subprocess.run([str(backend), *arguments], cwd=work, env=env, check=True,
                       stdout=subprocess.DEVNULL, timeout=30)
    run("collect", "--local-only", "--config", str(config), "--output", str(output))
    snapshot = json.loads(output.read_text())
    assert next(s for s in snapshot["sources"] if s["id"] == "imported_history")["status"] == "available"
    report = work / "verify.json"
    run("verify", "--local-only", "--config", str(config), "--output", str(report))
    assert json.loads(report.read_text())["failed_checks"] == 0
    process = subprocess.Popen([str(backend), "serve", "--local-only", "--port", "0",
        "--config", str(config)], cwd=work, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        import select
        if not select.select([process.stdout], [], [], 15)[0]:
            raise RuntimeError("Bundled backend did not start within 15 seconds")
        startup = json.loads(process.stdout.readline())
        token_path = Path(startup["token_file"])
        token = token_path.read_text().strip()
        assert token_path.stat().st_mode & 0o777 == 0o600
        base = startup["listening"]
        for path in ["health", "snapshot", "pet"]:
            request = Request(base + "/v1/" + path, headers={"Authorization": "Bearer " + token})
            with urlopen(request, timeout=15) as response:
                assert response.status == 200
                if path == "pet":
                    frame = json.load(response)
                    assert frame["schema_version"] == 1 and frame["state"] in {"idle", "sleeping", "working", "confused", "tired"}
        try:
            urlopen(base + "/v1/health", timeout=5)
            raise AssertionError("Unauthenticated API request was accepted")
        except HTTPError as error:
            assert error.code == 401
        print("PASS: relocated bundled backend, synthetic collect/verify, authenticated HTTP API (incl. pet frame), token permissions")
    finally:
        process.terminate()
        process.communicate(timeout=10)
