"""Read-only SQLite URIs that also work on databases left in idle WAL mode."""
from pathlib import Path


def _idle_wal_database(path):
    """True for a WAL database with no live log, which some SQLite builds refuse to open read-only."""
    if Path(str(path) + "-wal").exists():
        return False
    try:
        with open(path, "rb") as handle:
            header = handle.read(20)
    except OSError:
        return False
    return len(header) == 20 and header.startswith(b"SQLite format 3\0") and header[18] == 2


def readonly_uri(path):
    resolved = Path(path).resolve()
    query = "?mode=ro&immutable=1" if _idle_wal_database(resolved) else "?mode=ro"
    return resolved.as_uri() + query
