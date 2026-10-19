"""Policy test suites ("golden sets") and profile suggestions.

A suite is a set of adjudicated examples, each with the decision it should receive. Running a suite evaluates every
example with AIDAP's deterministic checks (the same path as a simulation: nothing is stored as a run, no quota is used,
no model is called) and reports which examples behave differently from what was adjudicated. Whitepaper 7.21: golden
datasets, regression and reproducibility.

A suite never changes a policy. It is evidence for the person who publishes one.
"""

from __future__ import annotations

import math
from typing import Any

from ...assurance_engine import AssuranceEngine, EngineRequest
from ...assurance_engine.evaluators.privacy.checks import detect_all
from ...assurance_engine.ingestion.loader import Limits
from ...assurance_engine.normalization.schema import infer_schema
from ...assurance_engine.evaluators.quality.population import column_stats
from ...domain.accounts.plans import F_TEST_SUITES
from ...domain.governance.authorization import Permission
from ...domain.utils.domain_errors import Conflict, NotFound, PayloadTooLarge, ValidationFailed
from ...domain.utils.domain_helpers import iso, new_id
from ..context import Principal
from ..utils.common import audit, get_or_404

__all__ = ["SuiteService", "SuggestionService", "EXPECTED", "STRICTNESS", "MAX_SUITES", "MAX_CASES", "MAX_CASE_BYTES"]

EXPECTED = ("pass", "review", "quarantine", "block")
STRICTNESS = {d: i for i, d in enumerate(EXPECTED)}
MAX_SUITES = 20
MAX_CASES = 100
MAX_CASE_BYTES = 200_000
KEEP_RUNS = 20


def _public(case: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in case.items() if k != "blob_ref"}


class SuiteService:
    def __init__(self, deps: Any, plans: Any, simulation: Any) -> None:
        self.d, self.plans, self.sim = deps, plans, simulation

    # ------------------------------------------------------------------ suites
    def _suite(self, p: Principal, suite_id: str) -> dict[str, Any]:
        s = get_or_404(self.d, "suites", suite_id, p.tenant_id, "test suite")
        if s.get("project_id"):
            p.require_project(s["project_id"])
        return s

    def list(self, p: Principal) -> list[dict[str, Any]]:
        p.require(Permission.POLICIES_READ)
        out = []
        for s in self.d.db.find("suites", tenant_id=p.tenant_id, limit=200):
            if s.get("project_id") and not p.can_project(s["project_id"]):
                continue
            last = self.d.db.find("suite_runs", tenant_id=p.tenant_id, where={"suite_id": s["id"]}, limit=1)
            out.append({**s, "cases": self.d.db.count("suite_cases", tenant_id=p.tenant_id, where={"suite_id": s["id"]}),
                        "last_run": ({k: last[0][k] for k in ("id", "created_at", "summary", "profile_ref", "policy_ref")} if last else None)})
        return out

    def create(self, p: Principal, name: str, description: str = "", project_id: str = "") -> dict[str, Any]:
        p.require(Permission.POLICIES_WRITE)
        self.plans.require_feature(p.tenant_id, F_TEST_SUITES, "policy test suites")
        if project_id:
            p.require_project(project_id)
            get_or_404(self.d, "projects", project_id, p.tenant_id, "project")
        if self.d.db.count("suites", tenant_id=p.tenant_id) >= MAX_SUITES:
            raise Conflict(f"a workspace can hold {MAX_SUITES} test suites", code="suite_limit")
        s = {"id": new_id("sui"), "tenant_id": p.tenant_id, "name": name.strip()[:100], "description": description.strip()[:500],
             "project_id": project_id or "", "created_by": p.actor, "created_at": iso(self.d.now())}
        self.d.db.insert("suites", s, tenant_id=p.tenant_id)
        audit(self.d, p, "suite.created", s["id"], {"name": s["name"]})
        return s

    def get(self, p: Principal, suite_id: str) -> dict[str, Any]:
        p.require(Permission.POLICIES_READ)
        s = self._suite(p, suite_id)
        cases = sorted(self.d.db.find("suite_cases", tenant_id=p.tenant_id, where={"suite_id": suite_id}, limit=MAX_CASES + 1),
                       key=lambda c: c["created_at"])
        runs = self.d.db.find("suite_runs", tenant_id=p.tenant_id, where={"suite_id": suite_id}, limit=KEEP_RUNS)
        return {**s, "cases": [_public(c) for c in cases], "runs": runs}

    def delete(self, p: Principal, suite_id: str) -> None:
        p.require(Permission.POLICIES_WRITE)
        s = self._suite(p, suite_id)
        for c in self.d.db.find("suite_cases", tenant_id=p.tenant_id, where={"suite_id": suite_id}, limit=MAX_CASES + 1):
            self._drop_case(p.tenant_id, c)
        for r in self.d.db.find("suite_runs", tenant_id=p.tenant_id, where={"suite_id": suite_id}, limit=100):
            self.d.db.delete("suite_runs", r["id"], tenant_id=p.tenant_id)
        self.d.db.delete("suites", suite_id, tenant_id=p.tenant_id)
        audit(self.d, p, "suite.deleted", suite_id, {"name": s["name"]})

    # ------------------------------------------------------------------ cases
    def add_case(self, p: Principal, suite_id: str, *, name: str, expected: str, content: bytes, filename: str = "sample.txt",
                 expected_codes: list[str] | None = None, destination: str = "local_index", source_class: str = "unknown",
                 classification: str = "internal", metadata: dict[str, Any] | None = None, note: str = "") -> dict[str, Any]:
        p.require(Permission.POLICIES_WRITE)
        self.plans.require_feature(p.tenant_id, F_TEST_SUITES, "policy test suites")
        self._suite(p, suite_id)
        if expected not in EXPECTED:
            raise ValidationFailed("expected must be pass, review, quarantine or block", details={"fields": {"expected": "invalid"}})
        if not content:
            raise ValidationFailed("provide the example content", details={"fields": {"content": "required"}})
        if len(content) > MAX_CASE_BYTES:
            raise PayloadTooLarge(f"examples are limited to {MAX_CASE_BYTES // 1000} KB")
        if self.d.db.count("suite_cases", tenant_id=p.tenant_id, where={"suite_id": suite_id}) >= MAX_CASES:
            raise Conflict(f"a suite holds up to {MAX_CASES} examples", code="case_limit")
        cid = new_id("cas")
        ref = self.d.blobs.put(f"suites/{p.tenant_id}/{suite_id}/{cid}", content, content_type="application/octet-stream")
        case = {"id": cid, "tenant_id": p.tenant_id, "suite_id": suite_id, "name": name.strip()[:100] or filename,
                "expected": expected, "expected_codes": [str(c)[:120] for c in (expected_codes or [])][:20],
                "filename": filename[:200], "destination": destination, "source_class": source_class,
                "classification": classification, "metadata": metadata or {}, "note": note.strip()[:300], "size": len(content),
                "blob_ref": ref, "created_by": p.actor, "created_at": iso(self.d.now())}
        self.d.db.insert("suite_cases", case, tenant_id=p.tenant_id)
        audit(self.d, p, "suite.case_added", suite_id, {"case": cid, "expected": expected})
        return _public(case)

    def _drop_case(self, tenant: str, case: dict[str, Any]) -> None:
        try:
            self.d.blobs.delete(case["blob_ref"])
        except Exception:                                                          # noqa: BLE001
            pass
        self.d.db.delete("suite_cases", case["id"], tenant_id=tenant)

    def remove_case(self, p: Principal, suite_id: str, case_id: str) -> None:
        p.require(Permission.POLICIES_WRITE)
        self._suite(p, suite_id)
        c = get_or_404(self.d, "suite_cases", case_id, p.tenant_id, "example")
        if c["suite_id"] != suite_id:
            raise NotFound("example not found", code="suite_cases_not_found")
        self._drop_case(p.tenant_id, c)
        audit(self.d, p, "suite.case_removed", suite_id, {"case": case_id})

    # ------------------------------------------------------------------ running
    def run(self, p: Principal, suite_id: str, *, profile_id: str = "", policy_id: str = "", profile: dict | None = None,
            policy: dict | None = None, record: bool = True) -> dict[str, Any]:
        p.require(Permission.POLICIES_READ)
        p.require(Permission.RUNS_SUBMIT)
        self.plans.require_feature(p.tenant_id, F_TEST_SUITES, "policy test suites")
        s = self._suite(p, suite_id)
        cases = sorted(self.d.db.find("suite_cases", tenant_id=p.tenant_id, where={"suite_id": suite_id}, limit=MAX_CASES + 1),
                       key=lambda c: c["created_at"])
        if not cases:
            raise ValidationFailed("add at least one example before running the suite", details={"fields": {"cases": "empty"}})
        previous = self.d.db.find("suite_runs", tenant_id=p.tenant_id, where={"suite_id": suite_id}, limit=1)
        before = {c["case_id"]: c["actual"] for c in previous[0]["cases"]} if previous else {}
        results, refs = [], {"profile": profile_id or (profile or {}).get("id") or "", "policy": policy_id or (policy or {}).get("id") or "standard"}
        for c in cases:
            try:
                data = self.d.blobs.get(c["blob_ref"])
            except Exception:                                                      # noqa: BLE001
                results.append(self._row(c, None, [], "the stored example is no longer available", before))
                continue
            try:
                out = self.sim.simulate(p, content=data, filename=c["filename"], profile=profile,
                                        profile_id=profile_id, policy=policy, policy_id=policy_id,
                                        destination=c["destination"], source_class=c["source_class"],
                                        classification=c["classification"], metadata=c["metadata"])
            except ValidationFailed:
                raise
            except Exception as exc:                                               # noqa: BLE001
                results.append(self._row(c, None, [], f"{type(exc).__name__}: {str(exc)[:160]}", before))
                continue
            codes = sorted({r["code"] for r in out["reasons"]} | {f["code"] for f in out["findings"]})
            results.append(self._row(c, out["decision"], codes, "", before))
        passed = sum(1 for r in results if r["ok"])
        errors = sum(1 for r in results if r["error"])
        summary = {"total": len(results), "passed": passed, "failed": len(results) - passed - errors, "errors": errors,
                   "looser_than_expected": sum(1 for r in results if r["direction"] == "looser"),
                   "stricter_than_expected": sum(1 for r in results if r["direction"] == "stricter"),
                   "changed_since_last_run": sum(1 for r in results if r["changed"]), "all_passed": passed == len(results)}
        rec = {"id": new_id("sru"), "tenant_id": p.tenant_id, "suite_id": suite_id, "suite_name": s["name"],
               "created_at": iso(self.d.now()), "created_by": p.actor,
               "profile_ref": refs["profile"] + ("@draft" if profile else ""), "policy_ref": refs["policy"] + ("@draft" if policy else ""),
               "summary": summary, "cases": results,
               "note": "Deterministic checks only. SLAI agents and model-assisted checks are not part of a suite run."}
        if record:
            self.d.db.insert("suite_runs", rec, tenant_id=p.tenant_id)
            for old in self.d.db.find("suite_runs", tenant_id=p.tenant_id, where={"suite_id": suite_id}, limit=200)[KEEP_RUNS:]:
                self.d.db.delete("suite_runs", old["id"], tenant_id=p.tenant_id)
            audit(self.d, p, "suite.run", suite_id, {"run": rec["id"], **{k: summary[k] for k in ("total", "passed", "failed", "errors")}})
        return rec

    def gate(self, p: Principal, kind: str, cid: str, version: int, suite_ids: list[str], *, profile_id: str = "",
             policy_id: str = "") -> list[dict[str, Any]]:
        """Run each suite against a draft before it is published; any failing example stops the publication."""
        p.require(Permission.POLICIES_PUBLISH)
        rec = self.d.db.get("configs", self.d.configs._doc_id(p.tenant_id, kind, cid, version), tenant_id=p.tenant_id)
        if rec is None:
            raise NotFound("version not found", code="config_not_found")
        if kind == "policy" and not profile_id:
            raise ValidationFailed("choose the profile to test this policy with", details={"fields": {"profile_id": "required"}})
        out = []
        for sid in suite_ids:
            kw = {"profile": rec["document"], "policy_id": policy_id} if kind == "profile" else \
                 {"policy": rec["document"], "profile_id": profile_id}
            res = self.run(p, sid, **kw)
            out.append({"suite_id": sid, "run_id": res["id"], "summary": res["summary"]})
            if not res["summary"]["all_passed"]:
                bad = [c for c in res["cases"] if not c["ok"]][:10]
                raise Conflict(f"suite '{res['suite_name']}' failed: {res['summary']['passed']} of {res['summary']['total']} "
                               f"examples behave as adjudicated. Nothing was published.", code="suite_failed",
                               details={"suite_id": sid, "run_id": res["id"], "summary": res["summary"], "failing": bad})
        return out

    @staticmethod
    def _row(case: dict[str, Any], actual: str | None, codes: list[str], error: str, before: dict[str, str | None]) -> dict[str, Any]:
        missing = [c for c in case.get("expected_codes", []) if c not in codes]
        direction = None
        if actual is not None and actual != case["expected"]:
            direction = "looser" if STRICTNESS[actual] < STRICTNESS[case["expected"]] else "stricter"
        ok = actual is not None and actual == case["expected"] and not missing
        return {"case_id": case["id"], "name": case["name"], "expected": case["expected"], "actual": actual, "ok": ok,
                "direction": direction, "missing_codes": missing, "codes": codes[:30], "error": error,
                "changed": case["id"] in before and before[case["id"]] != actual, "was": before.get(case["id"])}


class SuggestionService:
    """Draft an intended-use profile from a representative sample. Deterministic profiling; nothing is stored."""

    def __init__(self, deps: Any, plans: Any) -> None:
        self.d, self.plans = deps, plans
        self._engine = AssuranceEngine(external={})

    def suggest(self, p: Principal, *, content: bytes, filename: str = "sample.csv", name: str = "", task: str = "") -> dict[str, Any]:
        p.require(Permission.POLICIES_READ)
        p.require(Permission.RUNS_SUBMIT)
        if not content:
            raise ValidationFailed("provide a representative sample", details={"fields": {"content": "required"}})
        if len(content) > 5_000_000:
            raise PayloadTooLarge("samples are limited to 5 MB")
        from ...domain.policies import IntendedUseProfile
        pol, _, _ = self.d.configs.resolve(p.tenant_id, "policy", "standard")
        base_prof, _, _ = self.d.configs.resolve(p.tenant_id, "profile", "dataset_upload")
        req = EngineRequest(data=content, profile=base_prof, policy=pol, filename=filename, av=self.d.scanner.scan(content),
                            document_reader=getattr(self.d.slai, "documents", None),
                            limits=Limits(max_bytes=5_000_000, max_chars=self.d.settings.max_text_chars,
                                          parse_timeout_s=float(self.d.settings.parse_timeout)),
                            now=self.d.now(), run_id="suggestion")
        ctx = self._engine.prepare(req)
        n = ctx.norm
        notes: list[str] = []
        sensitive: dict[str, int] = {}
        try:
            found, _, _ = detect_all(ctx)
            sensitive = {k.value: len(v) for k, v in found.items()}
        except Exception:                                                          # noqa: BLE001
            notes.append("Personal-data detection could not run on this sample.")
        slug = "".join(ch if ch.isalnum() else "_" for ch in (name or task or filename.rsplit(".", 1)[0]).lower()).strip("_")[:40] or "suggested"
        doc: dict[str, Any] = {"id": slug, "name": name or f"Suggested profile for {filename}", "task": task or "dataset_upload",
                               "description": f"Drafted from a sample of {filename}. Review every rule before publishing.",
                               "source_classes": ["internal_doc", "customer_upload"], "max_classification": "internal",
                               "destinations": ["local_index"], "privacy": {"purpose": "", "allowed_types": [], "redact_instead_of_block": True}}
        columns: list[dict[str, Any]] = []
        if n.is_records and n.records:
            recs = n.records
            schema = infer_schema(recs, n.columns)
            fields, text_fields = [], []
            for col in n.columns:
                st = column_stats(recs, col, schema[col]["type"])
                spec: dict[str, Any] = {"name": col, "type": schema[col]["type"] if schema[col]["type"] != "null" else "any"}
                if st["missing_rate"] == 0 and len(recs) >= 10:
                    spec["required"] = True
                if spec["type"] in ("integer", "number") and st.get("count"):
                    span = (st["max"] - st["min"]) or abs(st["max"]) or 1.0
                    pad = span * 0.1
                    lo, hi = st["min"] - pad, st["max"] + pad
                    if st["min"] >= 0:
                        lo = max(lo, 0.0)
                    digits = 0 if spec["type"] == "integer" else 3
                    spec["min"], spec["max"] = (math.floor(lo) if digits == 0 else round(lo, digits)), \
                                               (math.ceil(hi) if digits == 0 else round(hi, digits))
                elif spec["type"] == "string":
                    lens = sorted(len(str(r.get(col))) for r in recs if r.get(col) not in (None, ""))
                    if lens:
                        spec["max_length"] = int(math.ceil(lens[int(len(lens) * 0.99) - 1 if len(lens) > 1 else 0] * 1.5 / 10) * 10)
                        if sum(lens) / len(lens) >= 80:
                            text_fields.append(col)
                    distinct = st.get("distinct", 0)
                    if len(recs) >= 30 and 1 < distinct <= 12 and distinct / len(recs) <= 0.2 and st.get("categories"):
                        spec["domain"] = sorted(st["categories"])
                fields.append(spec)
                columns.append({"name": col, "type": spec["type"], "missing_rate": st["missing_rate"],
                                **{k: st[k] for k in ("min", "max", "mean", "distinct") if k in st}})
            doc.update({"fields": fields, "text_fields": text_fields,
                        "required_checks": ["intake.format", "quality.structural", "quality.statistical", "quality.duplicates",
                                            "privacy.pii", "safety.injection"],
                        "optional_checks": ["quality.relationship", "quality.anomaly", "slai.quality", "slai.privacy", "slai.safety"],
                        "thresholds": {"min_records": 10 if len(recs) >= 10 else 1, "max_missing_ratio": 0.2,
                                       "max_duplicate_ratio": 0.05, "max_near_duplicate_ratio": 0.1}})
            if len(recs) < 30:
                notes.append(f"Only {len(recs)} records: ranges and allowed values are weak estimates. Use a larger sample.")
            notes.append("Numeric ranges include a 10% margin around the observed range. Narrow them if you know the real limits.")
        else:
            doc.update({"fields": [], "text_fields": ["text", "body", "content"], "freshness_days": 365,
                        "required_metadata": ["owner", "source_revision", "effective_date"],
                        "required_checks": ["intake.format", "quality.structural", "quality.metadata", "temporal.freshness",
                                            "temporal.supersession", "privacy.pii", "safety.injection"],
                        "optional_checks": ["quality.duplicates", "semantic.conflicts", "provenance.origin", "slai.quality",
                                            "slai.privacy", "slai.safety", "slai.provenance"],
                        "thresholds": {"min_text_chars": 50, "max_duplicate_ratio": 0.05, "max_near_duplicate_ratio": 0.1}})
            notes.append("The sample is free text, so the draft follows the document-intake pattern (owner, revision, effective date).")
        if sensitive:
            notes.append("Personal or sensitive data was detected in the sample (" + ", ".join(sorted(sensitive)) +
                         "). The draft does not allow any of it; add allowed types only where the destination justifies it.")
        doc["tags"] = ["suggested"]
        prof = IntendedUseProfile.from_dict(doc)
        lint = self.d.configs.lint_documents(doc, None)
        return {"profile": prof.to_dict(), "columns": columns, "sensitive_types": sensitive, "records": len(n.records or []),
                "format": n.format, "notes": notes, "lint": lint, "stored": False,
                "next": "Review the draft, then save it as a new profile and publish a version."}
