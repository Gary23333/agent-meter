"""Validate a relocated release backend using synthetic data, without accounts."""
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from tests.support import database, insert

backend = Path(sys.argv[1]).resolve()
output = Path(sys.argv[2]).resolve()
with tempfile.TemporaryDirectory(prefix="release-smoke-", dir=root / ".runtime") as temp:
    work = Path(temp)
    db = database(work / "history.db")
    insert(db, "synthetic-request", input_tokens=100, output_tokens=20, created_at=int(time.time()))
    db.close()
    config = work / "config.json"
    config.write_text(json.dumps({"home": str(work), "app_roots": [],
        "ccswitch_db": str(work / "history.db"), "runtime_dir": str(work / ".runtime")}))
    env = {"HOME": str(work), "PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LANG": "en_US.UTF-8"}
    def run(*arguments):
        subprocess.run([str(backend), *arguments], cwd=work, env=env, check=True,
                       stdout=subprocess.DEVNULL, timeout=30)
    run("collect", "--local-only", "--config", str(config), "--output", str(output))
    snapshot = json.loads(output.read_text())
    assert next(s for s in snapshot["sources"] if s["id"] == "ccswitch")["status"] == "available"
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
        for path in ["health", "snapshot"]:
            request = Request(base + "/v1/" + path, headers={"Authorization": "Bearer " + token})
            with urlopen(request, timeout=15) as response:
                assert response.status == 200
        try:
            urlopen(base + "/v1/health", timeout=5)
            raise AssertionError("Unauthenticated API request was accepted")
        except HTTPError as error:
            assert error.code == 401
        print("PASS: relocated bundled backend, synthetic collect/verify, authenticated HTTP API, token permissions")
    finally:
        process.terminate()
        process.communicate(timeout=10)
