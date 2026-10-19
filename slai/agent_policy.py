"""Which SLAI agents may run for a given run - decided from plan, policy and budget before the engine starts."""

from __future__ import annotations

from ..domain.accounts.plans import F_MODEL_ASSIST, Plan
from ..domain.evaluations import CHECK_CATALOG, Origin
from ..domain.policies import AssurancePolicy

__all__ = ["withheld_checks"]


def withheld_checks(plan: Plan, policy: AssurancePolicy, *, inference_budget_left_cents: int | None) -> dict[str, str]:
    """``check_id -> reason`` for SLAI checks that must not run. The engine records them as NOT_EVALUATED(plan/budget);
    if the profile makes the check mandatory the decision falls back to REVIEW - never a silent pass."""
    out: dict[str, str] = {}
    for cid, spec in CHECK_CATALOG.items():
        if spec.origin == Origin.NATIVE:
            continue
        if spec.origin == Origin.MODEL or spec.external:
            if not plan.has(F_MODEL_ASSIST):
                out[cid] = f"model-assisted checks are not included in the {plan.name} plan"
            elif not policy.model_assist:
                out[cid] = "model-assisted checks are not enabled by the policy"
            elif inference_budget_left_cents is not None and inference_budget_left_cents <= 0 \
                    and plan.inference_allowance_cents > 0:
                out[cid] = "the managed-inference allowance for this period is used up"
    return out
