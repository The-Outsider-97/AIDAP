"""Run-time governance of SLAI agent calls: bounded concurrency, hard timeouts, accounting.

A hung agent can never hang a run: calls execute on a worker thread and the caller gives up at the deadline, marking
the check UNKNOWN(timeout). (The thread cannot be killed; it is left to finish and its result is discarded.)
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass, field
from typing import Any, Callable

__all__ = ["AgentGovernor", "AgentTimeout", "CallStats"]


class AgentTimeout(Exception):
    pass


@dataclass
class CallStats:
    calls: int = 0
    failures: int = 0
    timeouts: int = 0
    total_ms: int = 0
    last_error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"calls": self.calls, "failures": self.failures, "timeouts": self.timeouts, "total_ms": self.total_ms,
                "last_error": self.last_error}


class AgentGovernor:
    def __init__(self, *, max_concurrency: int = 2, default_timeout: float = 60.0) -> None:
        self._pool = ThreadPoolExecutor(max_workers=max(1, max_concurrency), thread_name_prefix="aidap-slai")
        self._gate = threading.BoundedSemaphore(max(1, max_concurrency))
        self.default_timeout = default_timeout
        self._stats: dict[str, CallStats] = {}
        self._lock = threading.Lock()

    def call(self, agent_key: str, fn: Callable[[], Any], *, timeout: float | None = None) -> Any:
        timeout = timeout or self.default_timeout
        st = self._stats.setdefault(agent_key, CallStats())
        started = time.monotonic()
        if not self._gate.acquire(timeout=min(timeout, 30)):
            raise AgentTimeout("SLAI agent concurrency limit reached")
        fut = self._pool.submit(self._guarded, fn)
        try:
            result = fut.result(timeout=timeout)
        except FutureTimeout as exc:
            with self._lock:
                st.timeouts += 1
                st.last_error = "timeout"
            raise AgentTimeout(f"{agent_key} did not answer within {timeout:.0f}s") from exc
        except Exception as exc:
            with self._lock:
                st.failures += 1
                st.last_error = f"{type(exc).__name__}: {str(exc)[:160]}"
            raise
        finally:
            with self._lock:
                st.calls += 1
                st.total_ms += int((time.monotonic() - started) * 1000)
        return result

    def _guarded(self, fn: Callable[[], Any]) -> Any:
        try:
            return fn()
        finally:
            self._gate.release()

    def stats(self) -> dict[str, Any]:
        return {k: v.to_dict() for k, v in self._stats.items()}

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
