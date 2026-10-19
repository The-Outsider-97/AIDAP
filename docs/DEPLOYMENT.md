# Deployment

AIDAP is a modular monolith: one Python package (`SLAI/applications/AIDAP`) that serves the API, the prebuilt web app
(`frontend/dist`) and background workers. It must run **inside the SLAI repository** so it can import SLAI's agents,
`checkpointing/` and `src/functions` (set `AIDAP_SLAI_ENABLED=0` to run with native checks only).

## Requirements
* Python 3.10+ with SLAI's own requirements, plus `pip install -r requirements.txt` (starlette, uvicorn, PyYAML, cryptography, python-multipart).
* Optional: ClamAV (`clamd`) for real malware scanning; an SMTP relay; Stripe account for paid plans.
* Node is **not** needed on the server: `frontend/dist` is committed. To rebuild after changing `frontend/src`:
  `cd frontend && npm install && npm run build` (esbuild, React 19, TypeScript).

## Run (single node)
```bash
cd SLAI/applications
cp AIDAP/.env.example .env          # edit it, then export the variables (or use your process manager)
python -m AIDAP check               # config, database, SLAI agents, checkpointing, scanner, billing
python -m AIDAP serve --host 0.0.0.0 --port 8780 --trust-proxy
```
With `AIDAP_INLINE_WORKERS=1` (default) jobs run inside the API process. For separate workers set it to `0` and run
`python -m AIDAP worker --threads 4` as another process on the same data directory.

## Production checklist (enforced at start-up when `AIDAP_ENV=production`)
* `AIDAP_BASE_URL` is `https://…`; cookies are Secure; terminate TLS at a reverse proxy and pass `--trust-proxy`.
* `AIDAP_SECRET_KEYS` (base64 32-byte keys, newest first) and `AIDAP_PEPPER` are set and backed up. Losing the keys makes stored artifacts unreadable.
* `AIDAP_BILLING_PROVIDER` is `stripe` or `none` — the sandbox is refused.
* Stripe: create three monthly EUR prices, put their ids in `AIDAP_STRIPE_PRICE_*`, point a webhook at
  `POST /api/v1/webhooks/stripe` for `checkout.session.completed`, `customer.subscription.*`, `invoice.paid`, `invoice.payment_failed`,
  and set `AIDAP_STRIPE_WEBHOOK_SECRET`.
* SMTP is configured; otherwise invitations, resets and contact-form mail only land in `<data dir>/mailbox` as JSON files, and nobody receives them.
* Connect `clamd` if you rely on file-safety results.
* Back up `AIDAP_DATA_DIR` (SQLite database, encrypted blobs, checkpoints). Run `python -m AIDAP admin verify-audit --tenant <id>` periodically.

## Operations
| Command | Purpose |
|---|---|
| `python -m AIDAP check` | Self-test and component status |
| `python -m AIDAP admin set-plan --tenant T --plan enterprise [--days N] [--note …]` | Operator-assigned plan (Enterprise is never self-served) |
| `python -m AIDAP admin list-tenants` | Tenants and plans |
| `python -m AIDAP admin verify-audit --tenant T` | Verify the hash-chained audit log |
| `python -m AIDAP export-contracts --out docs/contracts` | Write the JSON contracts |

## Known limitations
* Storage is SQLite (single node). The persistence port is isolated in `infra/persistence`; moving to PostgreSQL means a new adapter.
* The built-in malware check recognises only the EICAR test file and never reports "clean".
* Stripe integration is implemented against Stripe's REST API but has not been exercised against a live account in this repository.
* SLAI agents that need torch or an initialised store (`SafetyAgent`, `LanguageAgent`, `QualityAgent` → run
  `quality_memory_migrate.py --apply`) report `not_evaluated` until available; see *System & SLAI status* in the app.

## Backups, legal holds and deletion

* Back up the whole data directory (`var/`: SQLite database, sealed blobs, checkpoints) together, while the service is stopped or using
  SQLite's online backup, and keep the sealing keys (`AIDAP_SECRET_KEYS`) separately from the backups. Test a restore before promising a recovery objective.
* Deleting run content (`DELETE /runs/{id}/content`) and retention purges remove content from the live store only. Backups expire on the
  operator's own schedule — state that schedule in your customer terms.
* AIDAP has no legal-hold feature. If a hold applies, take a backup of the affected data before its retention window ends and keep it outside AIDAP; the retention sweep cannot be paused per run.
