"""W3C PROV-style graph (entities, activities, agents) for an assurance run."""

from __future__ import annotations

from typing import Any

__all__ = ["build_provenance"]


def build_provenance(*, run_id: str, tenant_id: str, original_digest: str, normalized_digest: str,
                     released_digest: str, policy_ref: str, profile_ref: str, baseline_ref: str | None,
                     evaluators: list[dict[str, Any]], reviewers: list[dict[str, Any]],
                     derived_from_digest: str | None = None, started_at: str = "", ended_at: str = "") -> dict[str, Any]:
    """Return a compact PROV-JSON-like document.

    Entities are content-addressed. A digest identifies and detects change; it
    does not establish authenticity or truth, and the graph says so.
    """
    ent: dict[str, Any] = {
        f"entity:input:{original_digest}": {"prov:type": "aidap:InputVersion", "aidap:digest": original_digest},
        f"entity:normalized:{normalized_digest}": {"prov:type": "aidap:NormalizedRepresentation",
                                                   "aidap:digest": normalized_digest},
        f"entity:policy:{policy_ref}": {"prov:type": "aidap:AssurancePolicy"},
        f"entity:profile:{profile_ref}": {"prov:type": "aidap:IntendedUseProfile"},
        f"entity:decision:{run_id}": {"prov:type": "aidap:FitnessDecision"},
    }
    if released_digest and released_digest != original_digest:
        ent[f"entity:released:{released_digest}"] = {"prov:type": "aidap:ReleasedArtifact",
                                                     "aidap:digest": released_digest}
    if baseline_ref:
        ent[f"entity:baseline:{baseline_ref}"] = {"prov:type": "aidap:Baseline"}
    if derived_from_digest:
        ent[f"entity:input:{derived_from_digest}"] = {"prov:type": "aidap:InputVersion",
                                                      "aidap:digest": derived_from_digest}
    act: dict[str, Any] = {f"activity:run:{run_id}": {"prov:type": "aidap:AssuranceRun",
                                                      "prov:startTime": started_at, "prov:endTime": ended_at}}
    agents: dict[str, Any] = {f"agent:aidap:{tenant_id}": {"prov:type": "prov:SoftwareAgent", "prov:label": "AIDAP"}}
    used: list[dict[str, str]] = []
    gen: list[dict[str, str]] = []
    assoc: list[dict[str, str]] = []
    derived: list[dict[str, str]] = []
    run = f"activity:run:{run_id}"
    for e in (f"entity:input:{original_digest}", f"entity:policy:{policy_ref}", f"entity:profile:{profile_ref}"):
        used.append({"activity": run, "entity": e})
    if baseline_ref:
        used.append({"activity": run, "entity": f"entity:baseline:{baseline_ref}"})
    gen.append({"entity": f"entity:normalized:{normalized_digest}", "activity": run})
    gen.append({"entity": f"entity:decision:{run_id}", "activity": run})
    derived.append({"generated": f"entity:normalized:{normalized_digest}", "used": f"entity:input:{original_digest}"})
    if f"entity:released:{released_digest}" in ent:
        derived.append({"generated": f"entity:released:{released_digest}", "used": f"entity:input:{original_digest}"})
    if derived_from_digest:
        derived.append({"generated": f"entity:input:{original_digest}", "used": f"entity:input:{derived_from_digest}"})
    assoc.append({"activity": run, "agent": f"agent:aidap:{tenant_id}"})
    for ev in evaluators:
        key = f"agent:evaluator:{ev.get('id')}@{ev.get('version', '')}"
        agents[key] = {"prov:type": "prov:SoftwareAgent", "prov:label": ev.get("name", ev.get("id")),
                       "aidap:origin": ev.get("origin", "native")}
        assoc.append({"activity": run, "agent": key})
    for rv in reviewers:
        key = f"agent:person:{rv.get('user_id')}"
        agents[key] = {"prov:type": "prov:Person", "aidap:role": rv.get("role", "")}
        assoc.append({"activity": run, "agent": key, "aidap:resolution": rv.get("resolution", "")})
    return {"prefix": {"prov": "http://www.w3.org/ns/prov#", "aidap": "https://aidap.invalid/ns#"},
            "entity": ent, "activity": act, "agent": agents, "used": used, "wasGeneratedBy": gen,
            "wasAssociatedWith": assoc, "wasDerivedFrom": derived,
            "note": "Digests establish identity and change detection, not authenticity or factual accuracy."}
