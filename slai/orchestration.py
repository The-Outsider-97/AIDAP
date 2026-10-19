"""Assembles the SLAI side of AIDAP: agent pool, governor, evaluators, checkpoints, optional lineage recording."""

from __future__ import annotations

from typing import Any

from ..assurance_engine.evaluators.external import ExternalEvaluator
from ..domain.utils.domain_helpers import to_jsonable
from .agent_pool import AgentPool
from .checkpoint_store import DocStageCheckpoints, SlaiStageCheckpoints
from .evaluators import build_slai_evaluators
from .governance import AgentGovernor
from .health import slai_health
from .reasoning_gateway import SlaiLanguageReasoner
from .runtime import slai_present

__all__ = ["SlaiRuntime", "build_slai_runtime"]


class SlaiRuntime:
    def __init__(self, pool: AgentPool, gov: AgentGovernor, checkpoints: Any, gateway: Any | None, enabled: bool) -> None:
        self.pool, self.gov, self.checkpoints, self.gateway, self.enabled = pool, gov, checkpoints, gateway, enabled
        self._evaluators = build_slai_evaluators(pool, gov, gateway) if enabled else {}

    def evaluators(self) -> dict[str, ExternalEvaluator]:
        return dict(self._evaluators)

    def record_lineage(self, *, artifact_id: str, digest: str, source_id: str, parent_id: str | None,
                       transformation: str, metadata: dict[str, Any]) -> bool:
        """Best-effort: store this input's lineage in SLAI's ProvenanceAgent. Never affects a decision."""
        if not self.enabled:
            return False
        try:
            agent = self.pool.get("provenance")
            with self.pool.lock("provenance"):
                agent.register_artifact(artifact_id, artifact_type="input", source_id=source_id, digest=digest,
                                        metadata={k: str(v) for k, v in to_jsonable(metadata).items()
                                                  if isinstance(v, (str, int, float))})
                if parent_id:
                    agent.record_derivation(artifact_id, parent_id, transformation)
            return True
        except Exception:                                         # noqa: BLE001
            return False

    def health(self, deep: bool = False) -> dict[str, Any]:
        return slai_health(self.pool, self.gov, self.checkpoints, deep=deep)

    def shutdown(self) -> None:
        self.gov.shutdown()


def build_slai_runtime(*, checkpoint_dir: str, docstore: Any, enabled: bool = True, pool: AgentPool | None = None,
                       gateway: Any | None = None, max_concurrency: int = 2) -> SlaiRuntime:
    enabled = bool(enabled and slai_present())
    pool = pool or AgentPool()
    try:
        checkpoints: Any = SlaiStageCheckpoints(checkpoint_dir)
    except Exception:                                             # noqa: BLE001 - degrade, and say so in health
        checkpoints = DocStageCheckpoints(docstore)
    if gateway is None and enabled:
        gateway = SlaiLanguageReasoner(pool)
    return SlaiRuntime(pool, AgentGovernor(max_concurrency=max_concurrency), checkpoints, gateway, enabled)
