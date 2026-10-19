"""Lazy, failure-tolerant access to SLAI agents.

SLAI's agents are heavy (torch, models, per-agent SQLite memories). AIDAP therefore never imports them at start-up:
an agent is built on first use, behind a lock, and a failed build is remembered for a cool-down so a broken
dependency cannot make every run slow. Failures surface as ``Unavailable`` with the remediation SLAI itself gave, and
the evaluator turns that into an explicit UNKNOWN - never into a pass.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

from ..domain.utils.domain_errors import Unavailable
from .runtime import import_agent, ensure_path

__all__ = ["AgentPool", "AgentSpec", "DEFAULT_SPECS"]

COOLDOWN_SECONDS = 300.0


@dataclass(frozen=True)
class AgentSpec:
    key: str
    module: str
    cls: str
    needs_shared_memory: bool = True
    note: str = ""


DEFAULT_SPECS: dict[str, AgentSpec] = {
    "quality": AgentSpec("quality", "quality_agent", "QualityAgent",
                         note="needs the QualityMemory SQLite store: run SLAI's quality_memory_migrate.py --apply"),
    "privacy_id": AgentSpec("privacy_id", "privacy.data_id", "DataID", needs_shared_memory=False,
                            note="SLAI privacy entity identification (consent/purpose layers are not used)"),
    "safety": AgentSpec("safety", "safety_agent", "SafetyAgent", note="requires torch"),
    "provenance": AgentSpec("provenance", "provenance_agent", "ProvenanceAgent"),
    "language": AgentSpec("language", "language_agent", "LanguageAgent", note="local text generation; requires torch"),
}


class AgentPool:
    def __init__(self, specs: dict[str, AgentSpec] | None = None, *, factory: Callable[[str], Any] | None = None) -> None:
        self.specs = dict(specs or DEFAULT_SPECS)
        self._factory = factory                    # tests inject fakes; production builds real SLAI agents
        self._agents: dict[str, Any] = {}
        self._failed: dict[str, tuple[float, str]] = {}
        self._locks: dict[str, threading.RLock] = {k: threading.RLock() for k in self.specs}
        self._build_lock = threading.Lock()
        self._shared_memory: Any = None

    # ------------------------------------------------------------------ construction
    def _shared(self) -> Any:
        if self._shared_memory is None:
            from importlib import import_module
            ensure_path()
            self._shared_memory = import_module("src.agents.collaborative.shared_memory").SharedMemory()
        return self._shared_memory

    def _build(self, key: str) -> Any:
        if self._factory is not None:
            return self._factory(key)
        spec = self.specs[key]
        if "." in spec.module:                       # a SLAI sub-component rather than a BaseAgent
            from importlib import import_module
            ensure_path()
            try:
                return getattr(import_module(f"src.agents.{spec.module}"), spec.cls)()
            except Exception as exc:                  # noqa: BLE001
                raise Unavailable(f"{spec.cls} could not be created: {type(exc).__name__}: {exc}",
                                  code="slai_unavailable") from exc
        klass = import_agent(spec.module, spec.cls)
        try:
            kwargs: dict[str, Any] = {}
            if key == "quality":
                from importlib import import_module
                mem_cls = getattr(import_module("src.agents.quality_agent"), "QualityMemory")
                kwargs["local_memory"] = mem_cls()
            return klass(self._shared(), None, **kwargs)
        except Unavailable:
            raise
        except Exception as exc:                      # noqa: BLE001 - torch missing, store missing, config...
            hint = f" ({spec.note})" if spec.note else ""
            raise Unavailable(f"{spec.cls} could not be created: {type(exc).__name__}: {str(exc)[:240]}{hint}",
                              code="slai_unavailable") from exc

    # ------------------------------------------------------------------ public
    def lock(self, key: str) -> threading.RLock:
        return self._locks.setdefault(key, threading.RLock())

    def get(self, key: str) -> Any:
        if key not in self.specs:
            raise Unavailable(f"unknown SLAI agent '{key}'", code="slai_unavailable")
        if key in self._agents:
            return self._agents[key]
        failed = self._failed.get(key)
        if failed and time.monotonic() - failed[0] < COOLDOWN_SECONDS:
            raise Unavailable(failed[1], code="slai_unavailable")
        with self._build_lock:
            if key in self._agents:
                return self._agents[key]
            try:
                self._agents[key] = self._build(key)
            except Unavailable as exc:
                self._failed[key] = (time.monotonic(), exc.message)
                raise
            self._failed.pop(key, None)
            return self._agents[key]

    def available(self, key: str) -> tuple[bool, str]:
        try:
            self.get(key)
            return True, ""
        except Unavailable as exc:
            return False, exc.message

    def invalidate(self, key: str, reason: str = "") -> None:
        self._agents.pop(key, None)
        if reason:
            self._failed[key] = (time.monotonic(), reason)

    def status(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, spec in self.specs.items():
            if key in self._agents:
                out[key] = {"state": "ready", "agent": spec.cls}
            elif key in self._failed:
                out[key] = {"state": "unavailable", "agent": spec.cls, "reason": self._failed[key][1]}
            else:
                out[key] = {"state": "not_loaded", "agent": spec.cls, "note": spec.note}
        return out
