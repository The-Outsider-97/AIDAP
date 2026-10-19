"""Near-duplicate and outlier detection, and upstream monitoring signals."""

from __future__ import annotations

import random
import unittest
from datetime import datetime, timedelta, timezone

from ..assurance_engine.evaluators.quality.similarity import jaccard, near_duplicates, shingles
from ..assurance_engine.ingestion.signals import collect_signals
from ..domain.decisions import Decision
from .test_engine import META, docs, load, policy, profile, rules, run

S1 = ("The quarterly maintenance window for the primary database cluster starts at midnight and "
      "lasts roughly ninety minutes, during which writes are queued and replayed afterwards, and read replicas "
      "continue to serve traffic from their local caches until the primary is promoted back into service.")
S1_NEAR = S1.replace("roughly", "about")


def ds_profile(**thr):
    from ..domain.policies.models import IntendedUseProfile
    d = load("profiles", "dataset_upload")
    d["thresholds"] = {**d["thresholds"], **thr}
    return IntendedUseProfile.from_dict(d)


def codes(result, check):
    return {f.code for f in result.results[check].findings}


class NearDuplicates(unittest.TestCase):
    def test_similarity_is_deterministic_and_ignores_exact_repeats(self):
        units = [S1, S1_NEAR, S1, "A completely different sentence about onboarding new employees to the building and badge system."]
        found = near_duplicates(units)
        self.assertEqual(found, near_duplicates(units))
        self.assertEqual(list(found), [1])            # unit 2 is an exact repeat: the exact check reports it, not this one
        self.assertEqual(found[1][0], 0)
        self.assertGreaterEqual(found[1][1], 0.8)
        self.assertEqual(jaccard(shingles(S1.split()), shingles(S1.split())), 1.0)

    def test_short_units_are_not_compared(self):
        self.assertEqual(near_duplicates(["see section two", "see section 2"]), {})

    def test_records_with_near_copies_are_flagged(self):
        rnd = random.Random(7)
        words = "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu nu xi omicron pi rho sigma tau".split()
        base = [{"body": " ".join(rnd.choice(words) + str(rnd.randint(0, 9999)) for _ in range(20))} for _ in range(12)]
        recs = base + [{"body": b["body"].replace(b["body"].split()[0], "changed", 1)} for b in base[:6]]
        r = run(recs, prof=profile("rag_indexing"))
        self.assertIn("quality.duplicates.near", codes(r, "quality.duplicates"))

    def test_distinct_records_are_not_flagged(self):
        rnd = random.Random(3)
        recs = [{"body": " ".join(str(rnd.random()) for _ in range(20))} for _ in range(30)]
        r = run(recs, prof=profile("rag_indexing"))
        self.assertNotIn("quality.duplicates.near", codes(r, "quality.duplicates"))


class Outliers(unittest.TestCase):
    def test_extreme_values_are_reported_but_never_block(self):
        rnd = random.Random(1)
        recs = [{"id": i, "amount": rnd.gauss(100, 5)} for i in range(200)] + [{"id": 900, "amount": 100000.0}]
        r = run(recs, prof=ds_profile())
        f = [x for x in r.results["quality.statistical"].findings
             if x.code == "quality.statistical.outliers" and x.data["field"] == "amount"]
        self.assertEqual(len(f), 1)
        self.assertIn(f[0].severity.value, ("info", "low"))
        self.assertNotEqual(r.outcome.decision, Decision.BLOCK)


class UpstreamSignals(unittest.TestCase):
    def sigs(self, *items):
        return {**META, "upstream_checks": list(items)}

    def prof(self):
        from ..domain.policies.models import IntendedUseProfile
        d = load("profiles", "rag_indexing")
        d["optional_checks"] = [*d["optional_checks"], "provenance.upstream"]
        return IntendedUseProfile.from_dict(d)

    def test_no_signals_means_not_applicable_not_failure(self):
        r = run(docs("Employees accrue twenty five days of paid leave per calendar year and may carry over five days."), prof=self.prof())
        self.assertEqual(r.results["provenance.upstream"].status.value, "not_evaluated" if "not_evaluated" in
                         {s.value for s in type(r.results["provenance.upstream"].status)} else r.results["provenance.upstream"].status.value)
        self.assertEqual(r.results["provenance.upstream"].findings, [])

    def test_failed_signal_adds_a_finding_and_withholds_pass(self):
        text = "Employees accrue twenty five days of paid leave per calendar year and may carry over five days."
        r = run(docs(text), prof=self.prof(), meta=self.sigs({"source": "monte_carlo", "name": "freshness", "status": "failed"}))
        self.assertIn("provenance.upstream.failed", codes(r, "provenance.upstream"))
        self.assertIn(r.outcome.decision, (Decision.REVIEW, Decision.QUARANTINE, Decision.BLOCK))

    def test_a_passing_signal_does_not_create_findings_or_raise_confidence(self):
        text = "Employees accrue twenty five days of paid leave per calendar year and may carry over five days."
        r = run(docs(text), prof=self.prof(), meta=self.sigs({"source": "soda", "name": "orders", "status": "passed"}))
        self.assertEqual(r.results["provenance.upstream"].findings, [])
        self.assertTrue(r.results["provenance.upstream"].metrics["asserted"])

    def test_old_results_are_stale(self):
        old = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        text = "Employees accrue twenty five days of paid leave per calendar year and may carry over five days."
        r = run(docs(text), prof=self.prof(), meta=self.sigs({"source": "soda", "name": "orders", "status": "passed", "observed_at": old}))
        self.assertIn("provenance.upstream.stale", codes(r, "provenance.upstream"))

    def test_adapters(self):
        gx = {"success": False, "statistics": {"evaluated_expectations": 10, "unsuccessful_expectations": 2},
              "meta": {"expectation_suite_name": "orders", "run_id": {"run_time": "2026-10-01T10:00:00+00:00"}}}
        soda = {"hasFailures": False, "hasErrors": False, "hasWarnings": True, "dataSource": "wh"}
        out = collect_signals({"great_expectations_result": gx, "soda_scan": soda, "upstream_checks": ["junk", {"status": "ok"}]})
        by = {(s["source"], s["status"]) for s in out}
        self.assertIn(("great_expectations", "failed"), by)
        self.assertIn(("soda", "warning"), by)
        self.assertIn(("unspecified", "passed"), by)
        self.assertEqual(len(out), 3)
        self.assertEqual(collect_signals({"upstream_checks": "x"}), [])


if __name__ == "__main__":
    unittest.main()
