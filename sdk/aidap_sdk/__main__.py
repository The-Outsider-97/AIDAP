"""CI gate:  python -m aidap_sdk check data.json --project prj_... --profile rag_indexing

Exit codes: 0 PASS, 10 REVIEW, 20 QUARANTINE, 30 BLOCK, 2 usage/connection error, 3 run failed."""

from __future__ import annotations

import argparse
import json
import sys

from .client import EXIT_CODES, AidapError, Client


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m aidap_sdk")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="submit a file and exit with the decision")
    c.add_argument("path")
    c.add_argument("--project", required=True)
    c.add_argument("--profile", required=True)
    c.add_argument("--policy", default="")
    c.add_argument("--destination", default="")
    c.add_argument("--source-class", default="unknown")
    c.add_argument("--metadata", default="", help="JSON object")
    c.add_argument("--url")
    c.add_argument("--api-key")
    c.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    try:
        cl = Client(a.url, a.api_key)
        res = cl.assure(a.path, project=a.project, profile=a.profile, policy=a.policy, destination=a.destination,
                        source_class=a.source_class, metadata=json.loads(a.metadata) if a.metadata else None)
    except (AidapError, OSError, ValueError, TimeoutError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if res.state != "completed":
        print(f"run {res.run_id} {res.state}: {res.run.get('error', '')}", file=sys.stderr)
        return 3
    if a.json:
        print(json.dumps({"run_id": res.run_id, "decision": res.decision, "release_authorized": res.release_authorized,
                          "reasons": res.reason_codes, "summary": res.summary}, indent=2))
    else:
        print(f"{res.decision.upper()}  {res.summary}\nrun {res.run_id}  release {'authorised' if res.release_authorized else 'NOT authorised'}")
    return EXIT_CODES.get(res.decision or "", 2)


if __name__ == "__main__":
    raise SystemExit(main())
