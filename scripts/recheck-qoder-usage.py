#!/usr/bin/env python3
"""Run after a Qoder upgrade: python3 scripts/recheck-qoder-usage.py [--days N].

Exit 0 = no drift, exit 2 = drift detected (version change, tokens appearing,
or usage records missing). Read-only; aggregates only, no message content.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agent_meter.qoder_watch import main

if __name__ == "__main__":
    sys.exit(main())