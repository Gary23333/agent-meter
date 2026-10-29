"""Bounded, source-isolated cache for parsed local usage (never raw messages)."""
from collections import OrderedDict
from pathlib import Path
from sys import getsizeof
from threading import RLock


def _size(value):
    # Count shared objects once within an entry; across entries overcounting is
    # intentional, so shared model strings cannot make the budget optimistic.
    seen = set()
    def visit(item):
        identity = id(item)
        if identity in seen:
            return 0
        seen.add(identity)
        total = getsizeof(item)
        if isinstance(item, dict):
            total += sum(visit(k) + visit(v) for k, v in item.items())
        elif isinstance(item, (tuple, list)):
            total += sum(visit(v) for v in item)
        return total
    return visit(value)


class RecordCache:
    """LRU capped by estimated Python bytes and file count, shared by readers.

    Oversized entries are returned to the caller but never retained. Eviction
    affects parsing speed only, never the completeness of a usage report.
    """
    def __init__(self, max_bytes=16 * 1024 * 1024, max_entries=512):
        self.max_bytes, self.max_entries = max_bytes, max_entries
        self._entries = OrderedDict()
        self._lock = RLock()
        self.bytes = 0

    def _drop(self, key):
        self.bytes -= self._entries.pop(key)[2]

    def read(self, path, parser, namespace):
        path = Path(path)
        key = (namespace, str(path))
        stat = path.stat()
        stamp = (stat.st_mtime_ns, stat.st_size)
        with self._lock:
            cached = self._entries.get(key)
            if cached is not None and cached[0] == stamp:
                self._entries.move_to_end(key)
                return cached[1]
            if cached is not None:
                self._drop(key)
        parsed = parser(path)
        size = _size((key, stamp, parsed)) + 256
        with self._lock:
            # Another reader may have populated this key while parsing.
            if key in self._entries:
                self._drop(key)
            if size <= self.max_bytes and self.max_entries > 0:
                while self._entries and (self.bytes + size > self.max_bytes
                                         or len(self._entries) >= self.max_entries):
                    self._drop(next(iter(self._entries)))
                self._entries[key] = (stamp, parsed, size)
                self.bytes += size
        return parsed

    def prune(self, seen, namespace):
        with self._lock:
            for key in list(self._entries):
                if key[0] == namespace and key[1] not in seen:
                    self._drop(key)

    def clear(self):
        with self._lock:
            self._entries.clear()
            self.bytes = 0


records_cache = RecordCache()
