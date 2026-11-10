#!/usr/bin/env python3
"""Check the five login-gated account sources: python3 scripts/check-account-connections.py.

Exit 0 = all connected, 2 = at least one still needs a login, 1 = backend
unreachable. Read-only; never reads credentials.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agent_meter.account_check import main

if __name__ == "__main__":
    sys.exit(main())