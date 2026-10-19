from __future__ import annotations

import logging
import threading
import time
from typing import Any

log = logging.getLogger("aidap.worker")

__all__ = ["WorkerLoop"]


class WorkerLoop:
    """Leases jobs (assurance runs, deliveries, outbox mail) and performs periodic housekeeping.

    Jobs are durable and leased, so a crash mid-run is recovered when the lease expires; run stages resume from their
    SLAI checkpoints rather than starting over.
    """

    def __init__(self, services: Any, *, name: str = "worker", threads: int = 2, housekeeping_seconds: float = 30.0) -> None:
        self.svc, self.name, self.n, self.hk = services, name, max(1, threads), housekeeping_seconds
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []

    def _loop(self, idx: int) -> None:
        poll = max(0.05, self.svc.deps.settings.poll_seconds)
        last_hk = 0.0
        while not self._stop.is_set():
            try:
                worked = self.svc.run_one(f"{self.name}-{idx}")
            except Exception:                                          # noqa: BLE001
                log.exception("worker loop error")
                worked = False
            if idx == 0 and time.monotonic() - last_hk >= self.hk:
                last_hk = time.monotonic()
                try:
                    done = self.svc.housekeeping()
                    if any(done.values()):
                        log.info("housekeeping: %s", done)
                except Exception:                                      # noqa: BLE001
                    log.exception("housekeeping failed")
            if not worked:
                self._stop.wait(poll)

    def start(self) -> None:
        for i in range(self.n):
            t = threading.Thread(target=self._loop, args=(i,), name=f"{self.name}-{i}", daemon=True)
            t.start()
            self._threads.append(t)

    def stop(self, timeout: float = 10.0) -> None:
        self._stop.set()
        for t in self._threads:
            t.join(timeout)
        try:
            if self.svc.deps.slai is not None:
                self.svc.deps.slai.shutdown()
        except Exception:                                              # noqa: BLE001
            pass

    def run_forever(self) -> None:
        self.start()
        try:
            while not self._stop.is_set():
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()
