"""Run stage outputs on SLAI's ``CheckpointManager`` (atomic commit, digest-verified, versioned).

AIDAP does not implement its own checkpoint format: each committed evaluation stage is one SLAI checkpoint
``aidap-<run>-sNN`` holding a JSON ``agent_state`` component. A restarted worker resumes by loading them; a checkpoint
that fails verification is treated as absent and the (deterministic) stage is recomputed.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ..domain.utils.domain_helpers import to_jsonable
from .runtime import checkpointing

__all__ = ["SlaiStageCheckpoints", "DocStageCheckpoints"]


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


def _version(run_id: str, stage: int) -> str:
    safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in run_id)
    return f"aidap-{safe}-s{stage:02d}"


class _RunStore:
    def __init__(self, mgr: Any, run_id: str, errors: tuple[type[BaseException], ...]) -> None:
        self.mgr, self.run_id, self._errors = mgr, run_id, errors

    def get(self, stage: int) -> dict[str, Any] | None:
        version = _version(self.run_id, stage)
        try:
            if version not in self.mgr.list_checkpoints():
                return None
            loaded = self.mgr.load_components(version=version, components=["agent_state"])
            state = _plain(loaded.components["agent_state"])
            return state.get("payload")
        except self._errors:
            return None

    def put(self, stage: int, payload: dict[str, Any]) -> str:
        version = _version(self.run_id, stage)
        body = {"run_id": self.run_id, "stage": stage, "payload": to_jsonable(payload)}
        try:
            self.mgr.save_components({"agent_state": body}, version=version, overwrite=True, apply_retention=False,
                                     metadata={"application": "aidap", "run_id": self.run_id, "stage": stage})
        except self._errors:
            raise
        return version


class SlaiStageCheckpoints:
    kind = "slai.checkpointing"

    def __init__(self, base_dir: str | Path) -> None:
        ck = checkpointing()
        Path(base_dir).mkdir(parents=True, exist_ok=True)
        self.mgr = ck.CheckpointManager(str(base_dir))
        self._errors: tuple[type[BaseException], ...] = (ck.CheckpointError,) if hasattr(ck, "CheckpointError") \
            else (Exception,)
        self._base = Path(base_dir)

    def store_for(self, run_id: str) -> _RunStore:
        return _RunStore(self.mgr, run_id, self._errors)

    def drop(self, run_id: str) -> int:
        prefix = _version(run_id, 0)[:-3]
        n = 0
        for v in self.mgr.list_checkpoints():
            if v.startswith(prefix):
                try:
                    self.mgr.delete_checkpoint(v)
                    n += 1
                except self._errors:
                    continue
        return n

    def health(self) -> dict[str, Any]:
        try:
            rep = self.mgr.health_report()
            return {"ok": True, "kind": self.kind, "detail": str(getattr(rep, "status", "ok"))}
        except Exception as exc:                                  # noqa: BLE001
            return {"ok": False, "kind": self.kind, "detail": f"{type(exc).__name__}: {exc}"[:200]}


class _DocRunStore:
    def __init__(self, db: Any, run_id: str) -> None:
        self.db, self.run_id = db, run_id

    def get(self, stage: int) -> dict[str, Any] | None:
        d = self.db.get("stage_outputs", f"{self.run_id}:{stage}")
        return d["payload"] if d else None

    def put(self, stage: int, payload: dict[str, Any]) -> str:
        self.db.put("stage_outputs", {"id": f"{self.run_id}:{stage}", "run_id": self.run_id, "stage": stage,
                                      "payload": json.loads(json.dumps(to_jsonable(payload)))})
        return f"db:{self.run_id}:{stage}"


class DocStageCheckpoints:
    """Degraded fallback used only when SLAI's checkpointing cannot be imported (reported by ``health``)."""

    kind = "aidap.docstore-fallback"

    def __init__(self, db: Any) -> None:
        self.db = db

    def store_for(self, run_id: str) -> _DocRunStore:
        return _DocRunStore(self.db, run_id)

    def drop(self, run_id: str) -> int:
        n = 0
        for d in self.db.find("stage_outputs", where={"run_id": run_id}, limit=100):
            n += int(self.db.delete("stage_outputs", d["id"]))
        return n

    def health(self) -> dict[str, Any]:
        return {"ok": True, "degraded": True, "kind": self.kind,
                "detail": "SLAI checkpointing is unavailable; stage outputs are stored in the database"}
