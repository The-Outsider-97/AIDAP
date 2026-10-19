"""Engine request and re-exported evaluation context."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from ..domain.data.classification import DataClassification, DestinationClass, SourceClass
from ..domain.decisions import ExceptionGrant
from ..domain.policies import AssurancePolicy, IntendedUseProfile
from .evaluators.base import EvalContext
from .ingestion.loader import Limits

__all__ = ["EngineRequest", "EvalContext"]


@dataclass
class EngineRequest:
    data: bytes
    profile: IntendedUseProfile
    policy: AssurancePolicy
    filename: str = ""
    declared_media_type: str = ""
    destination: DestinationClass = DestinationClass.LOCAL_INDEX
    classification: DataClassification = DataClassification.INTERNAL
    source_class: SourceClass = SourceClass.UNKNOWN
    source_metadata: dict[str, Any] = field(default_factory=dict)
    baseline: dict[str, Any] | None = None        # approved baseline document or None
    known_revisions: list[dict[str, Any]] = field(default_factory=list)
    grants: list[ExceptionGrant] = field(default_factory=list)
    av: dict[str, Any] | None = None
    limits: Limits = field(default_factory=Limits)
    isolate: bool = True
    run_id: str = ""
    withheld: dict[str, str] = field(default_factory=dict)   # check_id -> reason (plan/budget); recorded as NOT_EVALUATED
    now: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
