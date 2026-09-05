#!/usr/bin/env python3
"""Silent cron wrapper for the research-feed extraction pipeline.

Successful runs write only to local log files and produce no cron delivery.
Failures return non-zero so Hermes cron emits an alert.
"""
from __future__ import annotations

import datetime as dt
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG = LOG_DIR / "cron-extract.log"
ERR = LOG_DIR / "cron-extract-error.log"
COMMAND = ["python3", str(ROOT / "extract" / "extract.py"), "--once"]

stamp = dt.datetime.now().astimezone().isoformat()
with LOG.open("a") as stdout, ERR.open("a") as stderr:
    stdout.write(f"\n[{stamp}] cron extract\n")
    stdout.flush()
    result = subprocess.run(COMMAND, cwd=ROOT, stdout=stdout, stderr=stderr, timeout=600)

raise SystemExit(result.returncode)
