"""Locating and importing the SLAI runtime that AIDAP lives inside (``applications/AIDAP``).

AIDAP *reuses* SLAI rather than re-implementing it:
  * ``src.functions``  - password hashing/policy, rate limiting, webhook signing + SSRF guard, e-mail, storage
  * ``checkpointing``  - durable, verified stage outputs
  * ``src.agents``     - Quality / Privacy / Safety / Provenance / Reasoning / Knowledge agents
  * ``src.tuning``     - not used by AIDAP (no model is trained here); intentionally not imported
Heavy agent imports (torch) are lazy and failure-tolerant; the lightweight ``functions`` / ``checkpointing`` imports are
required and fail with an actionable message.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import ModuleType

from ..domain.utils.domain_errors import Unavailable

__all__ = ["SLAI_ROOT", "ensure_path", "functions", "checkpointing", "import_agent", "slai_present"]

SLAI_ROOT = Path(__file__).resolve().parents[3]          # <SLAI>/applications/AIDAP/slai/runtime.py


def slai_present() -> bool:
    return (SLAI_ROOT / "src" / "functions").is_dir() and (SLAI_ROOT / "checkpointing").is_dir()


def ensure_path() -> None:
    root = str(SLAI_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)


def _load(name: str) -> ModuleType:
    ensure_path()
    try:
        return importlib.import_module(name)
    except Exception as exc:                                   # noqa: BLE001 - re-raised with context
        raise Unavailable(f"SLAI module '{name}' could not be imported ({type(exc).__name__}: {exc}). "
                          f"AIDAP must run inside the SLAI repository with SLAI's requirements installed.",
                          code="slai_unavailable") from exc


def functions(submodule: str) -> ModuleType:
    return _load(f"src.functions.{submodule}")


def checkpointing() -> ModuleType:
    return _load("checkpointing")


def import_agent(module: str, cls: str):
    """Import an agent class lazily; raises ``Unavailable`` (never crashes the process)."""
    mod = _load(f"src.agents.{module}")
    try:
        return getattr(mod, cls)
    except AttributeError as exc:
        raise Unavailable(f"SLAI agent {cls} not found in src.agents.{module}", code="slai_unavailable") from exc
