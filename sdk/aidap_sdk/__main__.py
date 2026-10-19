"""Command line.

  python -m aidap_sdk check data.json --project prj_... --profile rag_indexing [--gx-result gx.json] [--github]
  python -m aidap_sdk suite SUITE_ID --profile rag_indexing [--policy standard]

``check`` exit codes: 0 PASS, 10 REVIEW, 20 QUARANTINE, 30 BLOCK, 2 usage/connection error, 3 run failed.
``suite`` exit codes: 0 every example behaves as adjudicated, 1 at least one does not, 2 usage/connection error.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from .client import EXIT_CODES, AidapError, Client


def _upstream(args: argparse.Namespace) -> dict:
    """Results from tools that already looked at the data. AIDAP records them as asserted by the submitter."""
    meta: dict = {}
    for flag, key in ((args.gx_result, "great_expectations_result"), (args.soda_scan, "soda_scan")):
        if flag:
            with open(flag, encoding="utf-8") as fh:
                meta[key] = json.load(fh)
    checks = []
    for item in args.upstream or []:                      # SOURCE:NAME=STATUS, for example monte_carlo:orders_freshness=failed
        left, _, status = item.partition("=")
        source, _, name = left.partition(":")
        if not status or not name:
            raise ValueError(f"--upstream expects SOURCE:NAME=STATUS, got {item!r}")
        checks.append({"source": source, "name": name, "status": status})
    if checks:
        meta["upstream_checks"] = checks
    return meta


def _github(res, findings: list[dict]) -> None:
    """Workflow annotations plus a step summary, so a pull request shows why the gate stopped."""
    level = "notice" if res.decision == "pass" else "error" if res.decision in ("quarantine", "block") else "warning"
    print(f"::{level} title=AIDAP {str(res.decision).upper()}::{res.summary}")
    for f in findings[:20]:
        lvl = "error" if f["severity"] in ("critical", "high") else "warning"
        print(f"::{lvl} title={f['code']}::{f['title']}: {f['recommended_action']}")
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        rows = "\n".join(f"| {f['severity']} | `{f['code']}` | {f['title']} |" for f in findings[:30])
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"### AIDAP: {str(res.decision).upper()}\n\n{res.summary}\n\nRun `{res.run_id}`\n\n"
                     f"| Severity | Code | Finding |\n|---|---|---|\n{rows}\n")


def _check(a: argparse.Namespace) -> int:
    cl = Client(a.url, a.api_key)
    meta = json.loads(a.metadata) if a.metadata else {}
    meta.update(_upstream(a))
    res = cl.assure(a.path, project=a.project, profile=a.profile, policy=a.policy, destination=a.destination,
                    source_class=a.source_class, metadata=meta or None)
    if res.state != "completed":
        print(f"run {res.run_id} {res.state}: {res.run.get('error', '')}", file=sys.stderr)
        return 3
    if a.json:
        print(json.dumps({"run_id": res.run_id, "decision": res.decision, "release_authorized": res.release_authorized,
                          "reasons": res.reason_codes, "summary": res.summary}, indent=2))
    else:
        print(f"{res.decision.upper()}  {res.summary}\nrun {res.run_id}  release {'authorised' if res.release_authorized else 'NOT authorised'}")
    if a.github:
        _github(res, cl.findings(res.run_id).get("findings", []))
    return EXIT_CODES.get(res.decision or "", 2)


def _suite(a: argparse.Namespace) -> int:
    cl = Client(a.url, a.api_key)
    res = cl.run_suite(a.suite_id, profile=a.profile, policy=a.policy)
    s = res["summary"]
    for c in res["cases"]:
        mark = "ok  " if c["ok"] else "FAIL"
        extra = "" if c["ok"] else f"  expected {c['expected']}, got {c['actual'] or 'error'}" + \
            (f" ({c['direction']})" if c["direction"] else "") + (f"; missing {', '.join(c['missing_codes'])}" if c["missing_codes"] else "")
        print(f"{mark} {c['name']}{extra}")
    print(f"{s['passed']}/{s['total']} examples behave as adjudicated; {s['looser_than_expected']} looser, "
          f"{s['stricter_than_expected']} stricter than expected")
    return 0 if s["all_passed"] else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m aidap_sdk")
    sub = ap.add_subparsers(dest="cmd", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--url")
    common.add_argument("--api-key")
    c = sub.add_parser("check", parents=[common], help="submit a file and exit with the decision")
    c.add_argument("path")
    c.add_argument("--project", required=True)
    c.add_argument("--profile", required=True)
    c.add_argument("--policy", default="")
    c.add_argument("--destination", default="")
    c.add_argument("--source-class", default="unknown")
    c.add_argument("--metadata", default="", help="JSON object")
    c.add_argument("--gx-result", help="Great Expectations validation result (JSON) to record as an upstream check")
    c.add_argument("--soda-scan", help="Soda scan summary (JSON) to record as an upstream check")
    c.add_argument("--upstream", action="append", metavar="SOURCE:NAME=STATUS",
                   help="result from any other tool (passed, warning or failed); repeatable")
    c.add_argument("--github", action="store_true", help="print GitHub Actions annotations and a step summary")
    c.add_argument("--json", action="store_true")
    c.set_defaults(fn=_check)
    t = sub.add_parser("suite", parents=[common], help="run a golden-set test suite against a profile and policy")
    t.add_argument("suite_id")
    t.add_argument("--profile", required=True)
    t.add_argument("--policy", default="")
    t.set_defaults(fn=_suite)
    a = ap.parse_args(argv)
    try:
        return a.fn(a)
    except (AidapError, OSError, ValueError, TimeoutError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
