#!/usr/bin/env python3
"""Shared subprocess client for the local Hermes CLI."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

HERMES = Path.home() / ".local/bin/hermes"


def run_hermes(prompt: str, cwd: Path, timeout: int = 170) -> str:
    command = [
        str(HERMES), "chat", "-Q", "--provider", "gemini", "-m", "gemini-2.5-flash",
        "--reasoning", "none", "-t", "file", "--source", "tool", "--max-turns", "8", "-q", prompt,
    ]
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()[-1200:]
        raise RuntimeError(f"Hermes call failed: {detail}")
    output = result.stdout.strip()
    lines = [line for line in output.splitlines() if not re.match(r"session[_ ]id:", line.strip(), re.IGNORECASE)]
    return "\n".join(lines).strip()
