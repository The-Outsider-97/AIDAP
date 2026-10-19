"""AIDAP command line.

    python -m AIDAP serve                     start the API + web app (inline workers unless disabled)
    python -m AIDAP worker                    run a dedicated worker process
    python -m AIDAP check                     validate configuration and show SLAI / dependency health
    python -m AIDAP admin set-plan ...        operator action: set a workspace's plan (e.g. Enterprise)
    python -m AIDAP admin list-tenants        list workspaces
    python -m AIDAP admin verify-audit ...    verify a workspace's audit hash chain
    python -m AIDAP export-contracts --out D  write the JSON contracts (schemas, checks, workflow, permissions)

Run it from the directory that contains the ``AIDAP`` package (``SLAI/applications``).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any


def _services(args: argparse.Namespace) -> Any:
    from .bootstrap import bootstrap
    return bootstrap(args.config, data_dir=getattr(args, "data_dir", None))


def _find_tenant(svc: Any, ref: str) -> dict[str, Any]:
    db = svc.deps.db
    t = db.get("tenants", ref, tenant_id=ref) or db.get_by_ukey("tenants", f"slug:{ref}")
    if t is None and "@" in ref:
        u = db.get_by_ukey("users", f"email:{ref.lower()}") if hasattr(db, "get_by_ukey") else None
        if u:
            for m in db.find("memberships", where={"user_id": u["id"], "role": "owner"}, limit=1):
                t = db.get("tenants", m["tenant_id"], tenant_id=m["tenant_id"])
    if t is None:
        raise SystemExit(f"no workspace matches {ref!r} (use its id, slug or the owner's email)")
    return t


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn
    from .api import create_app
    svc = _services(args)
    st = svc.deps.settings
    host = args.host or "127.0.0.1"
    from urllib.parse import urlsplit
    port = args.port or urlsplit(st.base_url).port or 8780
    if not st.inline_workers:
        print("note: inline workers are off - start `python -m AIDAP worker` or runs will stay queued", file=sys.stderr)
    print(f"AIDAP {st.environment} on http://{host}:{port}  (billing: {svc.deps.billing.provider}, "
          f"SLAI: {'on' if svc.deps.slai and svc.deps.slai.enabled else 'off'})")
    uvicorn.run(create_app(svc, trust_proxy=args.trust_proxy), host=host, port=port, log_level="info", proxy_headers=False)
    return 0


def cmd_worker(args: argparse.Namespace) -> int:
    from .workers import WorkerLoop
    svc = _services(args)
    print(f"AIDAP worker started ({args.threads} threads)")
    WorkerLoop(svc, name="worker", threads=args.threads).run_forever()
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    svc = _services(args)
    d = svc.deps
    out = {"environment": d.settings.environment, "data_dir": d.settings.data_dir, "billing": d.billing.health(),
           "malware_scanner": d.scanner.health(), "checkpointing": d.checkpoints.health(),
           "slai": d.slai.health() if d.slai is not None else {"enabled": False},
           "templates": {"profiles": len(d.catalog.profiles), "policies": len(d.catalog.policies)}}
    print(json.dumps(out, indent=2, default=str))
    return 0


def cmd_set_plan(args: argparse.Namespace) -> int:
    svc = _services(args)
    t = _find_tenant(svc, args.tenant)
    sub = svc.billing.admin_set_plan(t["id"], args.plan, days=args.days, note=args.note, actor="cli")
    print(f"{t['name']} ({t['id']}) is now on '{sub['plan_id']}' until {sub.get('current_period_end') or 'further notice'}")
    return 0


def cmd_list_tenants(args: argparse.Namespace) -> int:
    svc = _services(args)
    for t in svc.deps.db.find("tenants", limit=1000, desc=False):
        sub = svc.plans.subscription(t["id"])
        print(f"{t['id']}  {t['slug']:<28} {sub['plan_id']:<10} {sub['status']:<9} {t['name']}")
    return 0


def cmd_verify_audit(args: argparse.Namespace) -> int:
    svc = _services(args)
    t = _find_tenant(svc, args.tenant)
    res = svc.deps.db.verify_audit(t["id"])
    print(json.dumps(res, indent=2))
    return 0 if res.get("ok") else 2


def cmd_export_contracts(args: argparse.Namespace) -> int:
    from .contracts.schema_export import export_all
    out = Path(args.out)
    written = export_all(out)
    print(f"wrote {len(written)} files to {out}")
    return 0


class _TolerantFormat(logging.Filter):
    """SLAI's checkpointing codecs call ``logger.info("... with", value)`` (no ``%s``), which makes the logging module print
    a traceback for every record. AIDAP does not edit SLAI; it folds such arguments into the message instead."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.args and isinstance(record.msg, str) and "%" not in record.msg:
            record.msg = f"{record.msg} {record.args}"
            record.args = ()
        return True


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m AIDAP", description="AIDAP - AI Data Assurance Platform")
    ap.add_argument("--config", help="path to a main.yaml (default: AIDAP/configs/main.yaml, or $AIDAP_CONFIG)")
    ap.add_argument("--data-dir", help="data directory (default ./var or $AIDAP_DATA_DIR)")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve", help="start the API and web app")
    s.add_argument("--host")
    s.add_argument("--port", type=int)
    s.add_argument("--trust-proxy", action="store_true", help="use X-Forwarded-For for client IPs (only behind your own proxy)")
    s.set_defaults(fn=cmd_serve)
    w = sub.add_parser("worker", help="run a dedicated worker")
    w.add_argument("--threads", type=int, default=2)
    w.set_defaults(fn=cmd_worker)
    sub.add_parser("check", help="validate configuration and print health").set_defaults(fn=cmd_check)
    ad = sub.add_parser("admin", help="operator actions").add_subparsers(dest="admin_cmd", required=True)
    sp = ad.add_parser("set-plan", help="set a workspace's plan (Enterprise is set this way)")
    sp.add_argument("--tenant", required=True, help="workspace id, slug or owner email")
    sp.add_argument("--plan", required=True, choices=["developer", "starter", "team", "business", "enterprise"])
    sp.add_argument("--days", type=int, default=365)
    sp.add_argument("--note", default="", help="contract reference or reason (recorded in the audit log)")
    sp.set_defaults(fn=cmd_set_plan)
    ad.add_parser("list-tenants").set_defaults(fn=cmd_list_tenants)
    va = ad.add_parser("verify-audit")
    va.add_argument("--tenant", required=True)
    va.set_defaults(fn=cmd_verify_audit)
    ec = sub.add_parser("export-contracts", help="write JSON contracts")
    ec.add_argument("--out", default="docs/contracts")
    ec.set_defaults(fn=cmd_export_contracts)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    for h in logging.getLogger().handlers:
        h.addFilter(_TolerantFormat())
    return int(args.fn(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
