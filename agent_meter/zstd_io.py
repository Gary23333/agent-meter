"""Shared zstd decompression for local ledgers that rotate to compressed JSONL.

DeepSeek Harness sessions (`.jsonl.zstd`) and Codex rollouts (`.jsonl.zst`)
are both zstd-compressed JSONL. Python 3.14's `compression.zstd` is used when
present; otherwise the zstd CLI is spawned per file. A corrupt or truncated
file surfaces as OSError so the per-file caches can skip exactly that file.
"""
import subprocess
from contextlib import contextmanager

from .model import SourceError

try:
    from compression import zstd as _zstd   # Python >= 3.14
    HAS_STDLIB_ZSTD = True
except ImportError:
    HAS_STDLIB_ZSTD = False

# ZstdError is not an OSError subclass, so callers normalise it themselves.
ZSTD_ERRORS = (OSError, _zstd.ZstdError) if HAS_STDLIB_ZSTD else (OSError,)
COMPRESSED_SUFFIXES = (".zst", ".zstd")


def is_compressed(path):
    return str(getattr(path, "name", path)).endswith(COMPRESSED_SUFFIXES)


def route(zstd_binary):
    """Which decompression route is available; raises when neither exists."""
    if HAS_STDLIB_ZSTD:
        return "stdlib_compression_zstd"
    if zstd_binary:
        return "zstd_cli"
    raise SourceError("zstd_unavailable")


@contextmanager
def decompressed(path, route_name, zstd_binary):
    """Binary line iterator over one zstd file."""
    if route_name == "stdlib_compression_zstd":
        with _zstd.open(path, "rb") as handle:
            yield handle
    else:
        proc = subprocess.Popen([zstd_binary, "-dc", str(path)], stdout=subprocess.PIPE)
        try:
            yield proc.stdout
        finally:
            proc.stdout.close()
            proc.wait()
            if proc.returncode != 0:
                raise OSError("zstd decompression failed")
