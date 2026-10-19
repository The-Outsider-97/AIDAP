"""Health of the SLAI integration, for ``/health`` and the admin UI. Reports reality, never optimism."""

from __future__ import annotations

from typing import Any

from .agent_pool import AgentPool
from .governance import AgentGovernor
from .runtime import SLAI_ROOT, slai_present

__all__ = ["slai_health"]


def slai_health(pool: AgentPool | None, gov: AgentGovernor | None, checkpoints: Any | None, *, deep: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {"present": slai_present(), "root": str(SLAI_ROOT)}
    if checkpoints is not None:
        out["checkpointing"] = checkpoints.health()
    if pool is not None:
        agents = pool.status()
        if deep:                                    # building an agent can be slow (torch); only on demand
            for key in list(agents):
                ok, why = pool.available(key)
                agents[key] = {**agents[key], "state": "ready" if ok else "unavailable", **({"reason": why} if why else {})}
            agents = pool.status()
        out["agents"] = agents
    if gov is not None:
        out["calls"] = gov.stats()
    out["ok"] = bool(out["present"]) and bool(out.get("checkpointing", {}).get("ok", True))
    return out
