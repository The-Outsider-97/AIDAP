"""Process isolation for hostile-file parsing.

The parser runs in a child interpreter started with ``-I`` (isolated mode),
a scrubbed environment, CPU/address-space/file-size limits on POSIX, and a
wall-clock timeout. Python locks are not a security boundary; a separate
process is the minimum. On Windows ``resource`` is unavailable, so only the
timeout and process separation apply, and this is reported in the result.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

__all__ = ["parse_isolated", "IsolationUnavailable"]

_WORKER = Path(__file__).with_name("_worker.py")
MAX_OUTPUT_BYTES = 256 * 1024 * 1024


class IsolationUnavailable(RuntimeError):
    pass


def parse_isolated(data: bytes, fmt: str, *, max_records: int, max_chars: int, timeout_s: float,
                   memory_mb: int) -> dict:
    env = {"PYTHONIOENCODING": "utf-8", "AIDAP_PARSE_CPU_S": str(max(2, int(timeout_s))),
           "AIDAP_PARSE_MEM_MB": str(memory_mb)}
    for keep in ("SYSTEMROOT", "PATH"):          # Windows needs these to start python
        if os.name == "nt" and keep in os.environ:
            env[keep] = os.environ[keep]
    try:
        proc = subprocess.run([sys.executable, "-I", str(_WORKER), fmt, str(max_records), str(max_chars)],
                              input=data, capture_output=True, timeout=timeout_s, env=env, check=False)
    except subprocess.TimeoutExpired:
        return _failed(fmt, f"parsing exceeded {timeout_s:.0f}s and was terminated", timeout=True)
    except OSError as exc:
        raise IsolationUnavailable(str(exc)) from exc
    if proc.returncode != 0 or not proc.stdout:
        tail = (proc.stderr or b"")[-200:].decode("utf-8", "replace").strip()
        return _failed(fmt, f"parser process failed (exit {proc.returncode}) {tail}")
    if len(proc.stdout) > MAX_OUTPUT_BYTES:
        return _failed(fmt, "parser output exceeded the allowed size")
    try:
        return json.loads(proc.stdout.decode("utf-8"))
    except ValueError:
        return _failed(fmt, "parser returned malformed output")


def _failed(fmt: str, message: str, timeout: bool = False) -> dict:
    return {"kind": "text", "text": "", "records": None, "columns": [], "metadata": {}, "segments": [],
            "parse": {"coverage": 0.0, "errors": [message], "warnings": [], "truncated": False, "format": fmt,
                      "encoding": "unknown", "records_total": 0, "records_kept": 0, "timeout": timeout}}
