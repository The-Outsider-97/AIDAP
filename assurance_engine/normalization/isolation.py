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

__all__ = ["parse_isolated", "run_worker", "child_env", "IsolationUnavailable", "WorkerOutcome"]

_WORKER = Path(__file__).with_name("_worker.py")
MAX_OUTPUT_BYTES = 256 * 1024 * 1024


class IsolationUnavailable(RuntimeError):
    pass


class WorkerOutcome:
    """What a sandboxed child process produced. ``timed_out`` and ``error`` describe why there is no usable output."""

    __slots__ = ("stdout", "returncode", "stderr_tail", "timed_out", "error")

    def __init__(self, stdout: bytes = b"", returncode: int = 0, stderr_tail: str = "", timed_out: bool = False,
                 error: str = "") -> None:
        self.stdout, self.returncode, self.stderr_tail, self.timed_out, self.error = stdout, returncode, stderr_tail, timed_out, error

    @property
    def ok(self) -> bool:
        return not self.timed_out and not self.error and self.returncode == 0 and bool(self.stdout)


def child_env(timeout_s: float, memory_mb: int, extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {"PYTHONIOENCODING": "utf-8", "AIDAP_PARSE_CPU_S": str(max(2, int(timeout_s))), "AIDAP_PARSE_MEM_MB": str(memory_mb)}
    for keep in ("SYSTEMROOT", "PATH"):          # Windows needs these to start python
        if os.name == "nt" and keep in os.environ:
            env[keep] = os.environ[keep]
    env.update(extra or {})
    return env


def run_worker(script: Path, argv: list[str], data: bytes, *, timeout_s: float, env: dict[str, str],
               max_output: int = MAX_OUTPUT_BYTES) -> WorkerOutcome:
    """Run ``script`` in a child interpreter in isolated mode (``-I``) with scrubbed environment and a wall-clock timeout.

    The single place AIDAP starts untrusted-input processes, so the text parser and the SLAI document reader share one policy.
    Raises ``IsolationUnavailable`` only when a child process cannot be started at all.
    """
    try:
        proc = subprocess.run([sys.executable, "-I", str(script), *argv], input=data, capture_output=True,
                              timeout=timeout_s, env=env, check=False)
    except subprocess.TimeoutExpired:
        return WorkerOutcome(timed_out=True, error=f"processing exceeded {timeout_s:.0f}s and was terminated")
    except OSError as exc:
        raise IsolationUnavailable(str(exc)) from exc
    tail = (proc.stderr or b"")[-200:].decode("utf-8", "replace").strip()
    if proc.returncode != 0 or not proc.stdout:
        return WorkerOutcome(returncode=proc.returncode, stderr_tail=tail,
                             error=f"worker process failed (exit {proc.returncode}) {tail}".strip())
    if len(proc.stdout) > max_output:
        return WorkerOutcome(error="worker output exceeded the allowed size")
    return WorkerOutcome(proc.stdout, proc.returncode, tail)


def parse_isolated(data: bytes, fmt: str, *, max_records: int, max_chars: int, timeout_s: float,
                   memory_mb: int) -> dict:
    out = run_worker(_WORKER, [fmt, str(max_records), str(max_chars)], data, timeout_s=timeout_s,
                     env=child_env(timeout_s, memory_mb))
    if out.timed_out:
        return _failed(fmt, f"parsing exceeded {timeout_s:.0f}s and was terminated", timeout=True)
    if out.error:
        return _failed(fmt, out.error.replace("worker process", "parser process").replace("worker output", "parser output"))
    try:
        return json.loads(out.stdout.decode("utf-8"))
    except ValueError:
        return _failed(fmt, "parser returned malformed output")


def _failed(fmt: str, message: str, timeout: bool = False) -> dict:
    return {"kind": "text", "text": "", "records": None, "columns": [], "metadata": {}, "segments": [],
            "parse": {"coverage": 0.0, "errors": [message], "warnings": [], "truncated": False, "format": fmt,
                      "encoding": "unknown", "records_total": 0, "records_kept": 0, "timeout": timeout}}
