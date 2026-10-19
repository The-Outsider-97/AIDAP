"""Contract for externally implemented evaluators (the SLAI adapter implements this)."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ...domain.evaluations import CHECK_CATALOG, CheckResult, Origin
from .base import EvalContext

__all__ = ["ExternalEvaluator", "withheld_reason"]


@runtime_checkable
class ExternalEvaluator(Protocol):
    check_id: str
    name: str
    version: str
    origin: Origin
    sends_content_out: bool      # True when content leaves the local process boundary

    def available(self) -> tuple[bool, str]: ...

    def evaluate(self, ctx: EvalContext) -> CheckResult: ...


def withheld_reason(ctx: EvalContext, ev: ExternalEvaluator) -> str | None:
    """Why an external/model-assisted evaluator must not run now (``None`` = allowed)."""
    spec = CHECK_CATALOG[ev.check_id]
    if spec.external or spec.origin == Origin.MODEL:
        if not ctx.policy.model_assist:
            return "model-assisted checks are not enabled by the policy"
        if ev.sends_content_out and not ctx.policy.external_inference:
            return "the policy does not permit sending content to a non-local endpoint"
        if ctx.destination.is_external or ev.sends_content_out:
            scan = ctx.cache.get("pii_scan")
            if scan is None:
                return "the local privacy screen has not completed"
            found = scan[0]
            if found:
                return "the local privacy screen found sensitive data; content is not sent for model-assisted evaluation"
    return None
