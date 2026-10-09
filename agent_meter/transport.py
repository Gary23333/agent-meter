"""Bounded read-only transports. Never publish upstream bodies or stderr."""

import json
import os
import queue
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from .model import SourceError

MAX_BODY = 8 * 1024 * 1024


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # A bearer credential must never follow a redirect to another origin.
        raise SourceError("redirect_rejected")


def post_json(url, body, timeout=10, headers=None):
    """Read-only query endpoints that happen to use POST (WorkBuddy, TRAE)."""
    return get_json(url, timeout=timeout, headers=headers, body=body)


def get_json(url, token=None, timeout=10, local=False, headers=None, body=None):
    parsed = urllib.parse.urlsplit(url)
    if parsed.username or parsed.password or parsed.fragment:
        raise SourceError("invalid_endpoint")
    if local:
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "::1", "localhost"}:
            raise SourceError("non_loopback_endpoint")
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    else:
        if parsed.scheme != "https":
            raise SourceError("insecure_endpoint")
        opener = urllib.request.build_opener(NoRedirect())
    headers = dict(headers or {})
    if any(not isinstance(v,str) or "\r" in v or "\n" in v for v in headers.values()):
        raise SourceError("invalid_request_header")
    headers.setdefault("Accept", "application/json")
    if token:
        headers["Authorization"] = "Bearer " + token
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    try:
        request = urllib.request.Request(url, data=data, headers=headers, method="POST" if data is not None else "GET")
        with opener.open(request, timeout=timeout) as response:
            body = response.read(MAX_BODY + 1)
            if len(body) > MAX_BODY:
                raise SourceError("response_too_large")
            obj = json.loads(body)
            if not isinstance(obj, (dict, list)):
                raise SourceError("invalid_response_shape")
            return obj
    except urllib.error.HTTPError as e:
        raise SourceError("not_authenticated" if e.code in (401, 403) else "http_" + str(e.code)) from None
    except SourceError:
        raise
    except (urllib.error.URLError, TimeoutError, OSError):
        raise SourceError("connection_failed") from None
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise SourceError("invalid_json") from None


class CodexRPC:
    ALLOWED = {"initialize", "account/rateLimits/read", "account/usage/read"}

    def __init__(self, binary, timeout=20, cwd=None):
        self.binary, self.timeout, self.cwd = binary, timeout, cwd
        self.process = None
        self.inbox = queue.Queue(maxsize=256)
        self.next_id = 0

    def __enter__(self):
        if not self.binary:
            raise SourceError("cli_not_available")
        try:
            self.process = subprocess.Popen(
                [self.binary, "app-server"], cwd=self.cwd,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError:
            raise SourceError("cli_not_available") from None
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()
        try:
            self.call("initialize", {"clientInfo": {"name": "agent_meter", "version": "0.1.0"},
                                     "capabilities": {"experimentalApi": True, "explicitGatewayOauth": True}})
            self._write({"method": "initialized"})
            return self
        except Exception:
            self.__exit__(None, None, None)
            raise

    def _read(self):
        while True:
            line = self.process.stdout.readline(MAX_BODY + 1)
            if not line:
                try:
                    self.inbox.put(None, timeout=1)
                except queue.Full:
                    pass
                return
            try:
                if len(line) > MAX_BODY:
                    raise ValueError()
                obj = json.loads(line)
                self.inbox.put(obj, timeout=1)
            except (ValueError, queue.Full):
                continue

    def _write(self, obj):
        try:
            self.process.stdin.write((json.dumps(obj) + "\n").encode())
            self.process.stdin.flush()
        except (BrokenPipeError, OSError):
            raise SourceError("rpc_disconnected") from None

    def call(self, method, params=None):
        if method not in self.ALLOWED:
            raise SourceError("write_method_rejected")
        self.next_id += 1
        request_id = self.next_id
        self._write({"id": request_id, "method": method, "params": params})
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            try:
                obj = self.inbox.get(timeout=max(.01, deadline - time.monotonic()))
            except queue.Empty:
                raise SourceError("rpc_timeout") from None
            if obj is None:
                raise SourceError("rpc_disconnected")
            if "method" in obj and "id" in obj:
                # Server request IDs are independent from client IDs.
                self._write({"id": obj["id"], "error": {"code": -32601, "message": "Read-only client"}})
                continue
            if obj.get("id") == request_id:
                if "error" in obj:
                    code = obj["error"].get("code")
                    raise SourceError("rpc_method_unavailable" if code == -32601 else "rpc_request_failed")
                result = obj.get("result")
                if not isinstance(result, dict):
                    raise SourceError("invalid_response_shape")
                return result
        raise SourceError("rpc_timeout")

    def __exit__(self, *args):
        if self.process:
            if self.process.stdin:
                self.process.stdin.close()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                try:
                    self.process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=2)
            if self.process.stdout:
                self.process.stdout.close()
