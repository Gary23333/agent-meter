"""Run the full test suite without real user accounts or external network I/O."""
import ipaddress
import os
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    connect = socket.socket.connect
    connect_ex = socket.socket.connect_ex

    def allow_loopback(address):
        if not isinstance(address, tuple):  # Unix sockets are local.
            return
        host = address[0]
        if host == "localhost":
            return
        try:
            if ipaddress.ip_address(host).is_loopback:
                return
        except ValueError:
            pass
        raise OSError("External network access is disabled in offline tests")

    def guarded_connect(sock, address):
        allow_loopback(address)
        return connect(sock, address)

    def guarded_connect_ex(sock, address):
        allow_loopback(address)
        return connect_ex(sock, address)

    with tempfile.TemporaryDirectory(prefix="agent-meter-tests-") as home:
        env = {key: os.environ[key] for key in ("PATH", "LANG", "LC_ALL", "TMPDIR", "TZ")
               if key in os.environ}
        env.update(HOME=home, XDG_CONFIG_HOME=home, XDG_DATA_HOME=home,
                   XDG_CACHE_HOME=home, NO_PROXY="localhost,127.0.0.1,::1")
        with patch.dict(os.environ, env, clear=True):
            from agent_meter import collector
            from agent_meter.model import SourceError
            default_config = collector.default_config

            def isolated_defaults():
                config = default_config()
                config.update(codex_binary=None, kimi_binary=None, codexbar_binary=None,
                              dreamina_binary=None,
                              design_probe_mcp=False, app_roots=[])
                return config

            with patch.object(collector, "default_config", isolated_defaults), \
                    patch.object(collector, "collect_claude", side_effect=SourceError("claude_not_logged_in")), \
                    patch.object(socket.socket, "connect", guarded_connect), \
                    patch.object(socket.socket, "connect_ex", guarded_connect_ex):
                suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), top_level_dir=str(ROOT))
                result = unittest.TextTestRunner(verbosity=2).run(suite)
                return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
