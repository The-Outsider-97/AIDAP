# HTTP API reference (v1)

Base path `/api/v1`. JSON in, JSON out; errors use the `aidap.error/1` envelope
`{"schema":"aidap.error/1","error":{"code","message","details"},"request_id"}`.

**Authentication.** Either `Authorization: Bearer aidk_…` (API key, scoped) or the browser session cookie `aidap_session`
with the `X-CSRF-Token` header (value of the `aidap_csrf` cookie) on every non-GET request.

**Submitting input.** `POST /runs` accepts a multipart `file`, a raw body (`X-Filename`, `X-Media-Type`, query parameters for the
fields), or JSON with `content`. `Idempotency-Key` makes retries safe; `wait=true` waits up to 25 s for the decision.

**Status codes.** 401 unauthenticated · 403 forbidden / release not authorized · 404 not found · 409 conflict · 413 too large ·
415 unsupported type · 422 validation (`details.fields`) · 402 plan limit or allowance reached · 429 rate limited (`Retry-After`).

Request-body contracts: `docs/contracts/requests.json`. Permission matrix: `docs/contracts/permissions.json`.

| Method | Path | Access |
|---|---|---|
| GET | `/health` | public |
| GET | `/health/ready` | public |
| GET | `/meta` | public |
| GET | `/plans` | public |
| GET | `/catalog/checks` | public |
| GET | `/catalog/roles` | public |
| GET | `/catalog/templates` | public |
| POST | `/contact` | public |
| POST | `/webhooks/stripe` | public |
| POST | `/auth/signup` | public |
| POST | `/auth/login` | public |
| POST | `/auth/logout` | auth |
| POST | `/auth/password/reset-request` | public |
| POST | `/auth/password/reset-confirm` | public |
| POST | `/auth/invitations/accept` | public |
| GET | `/me` | auth |
| POST | `/me/switch-tenant` | auth |
| POST | `/auth/csrf` | auth |
| POST | `/auth/password/change` | auth |
| POST | `/auth/mfa/setup` | auth |
| POST | `/auth/mfa/enable` | auth |
| POST | `/auth/mfa/disable` | auth |
| PATCH | `/tenant` | auth |
| GET | `/members` | auth |
| PATCH | `/members/{member_id}` | auth |
| DELETE | `/members/{member_id}` | auth |
| GET | `/invitations` | auth |
| POST | `/invitations` | auth |
| DELETE | `/invitations/{inv_id}` | auth |
| GET | `/api-keys` | auth |
| POST | `/api-keys` | auth |
| DELETE | `/api-keys/{key_id}` | auth |
| GET | `/runs` | auth |
| POST | `/runs` | auth |
| GET | `/runs/{run_id}` | auth |
| GET | `/runs/{run_id}/stages` | auth |
| GET | `/runs/{run_id}/decisions` | auth |
| GET | `/runs/{run_id}/findings` | auth |
| GET | `/runs/{run_id}/evidence` | auth |
| DELETE | `/runs/{run_id}/content` | auth (`retention.manage`) |
| GET | `/runs/{run_id}/report` | auth |
| GET | `/runs/{run_id}/diff` | auth |
| GET | `/runs/{run_id}/artifact` | auth |
| GET | `/runs/{run_id}/deliveries` | auth |
| POST | `/runs/{run_id}/cancel` | auth |
| POST | `/runs/{run_id}/retry` | auth |
| POST | `/runs/{run_id}/rerun` | auth |
| POST | `/runs/{run_id}/redact` | auth |
| GET | `/reviews` | auth |
| GET | `/reviews/{review_id}` | auth |
| POST | `/reviews/{review_id}/assign` | auth |
| POST | `/reviews/{review_id}/resolve` | auth |
| POST | `/exceptions/{exception_id}/revoke` | auth |
| GET | `/quarantine` | auth |
| GET | `/quarantine/{qid}` | auth |
| POST | `/quarantine/{qid}/access` | auth |
| GET | `/quarantine/{qid}/content` | auth |
| POST | `/quarantine/{qid}/dispose` | auth |
| GET | `/alerts` | auth |
| POST | `/alerts/{alert_id}/ack` | auth |
| GET | `/audit` | auth |
| GET | `/audit/verify` | auth |
| GET | `/audit/export` | auth |
| GET | `/account/export` | auth (owner) |
| GET | `/deliveries` | auth |
| POST | `/deliveries/{delivery_id}/retry` | auth |
| GET | `/usage` | auth |
| GET | `/usage/history` | auth |
| GET | `/billing` | auth |
| POST | `/billing/checkout` | auth |
| POST | `/billing/portal` | auth |
| POST | `/billing/cancel` | auth |
| POST | `/billing/topup` | auth |
| POST | `/billing/settings` | auth |
| POST | `/billing/sandbox/complete` | auth |
| GET | `/dashboard` | auth |
| GET | `/system/status` | auth |
| GET | `/projects` | auth |
| POST | `/projects` | auth |
| GET | `/projects/{project_id}` | auth |
| PATCH | `/projects/{project_id}` | auth |
| GET | `/profiles` | auth |
| GET | `/policies` | auth |
| POST | `/profiles` | auth |
| POST | `/policies` | auth |
| GET | `/profiles/{cid}` | auth |
| GET | `/policies/{cid}` | auth |
| POST | `/profiles/{cid}/versions` | auth |
| POST | `/policies/{cid}/versions` | auth |
| PUT | `/profiles/{cid}/draft` | auth |
| PUT | `/policies/{cid}/draft` | auth |
| DELETE | `/profiles/{cid}/draft` | auth |
| DELETE | `/policies/{cid}/draft` | auth |
| POST | `/profiles/{cid}/versions/{version}/publish` | auth |
| POST | `/policies/{cid}/versions/{version}/publish` | auth |
| POST | `/lint` | auth |
| POST | `/simulate` | auth |
| GET | `/destinations` | auth |
| POST | `/destinations` | auth |
| PATCH | `/destinations/{dest_id}` | auth |
| DELETE | `/destinations/{dest_id}` | auth |
| GET | `/baselines` | auth |
| POST | `/baselines` | auth |
| GET | `/baselines/{baseline_id}` | auth |
| POST | `/baselines/{baseline_id}/approve` | auth |
| POST | `/baselines/{baseline_id}/retire` | auth |
| GET | `/schedules` | auth |
| POST | `/schedules` | auth |
| PATCH | `/schedules/{sid}` | auth |
| DELETE | `/schedules/{sid}` | auth |
| GET | `/insights` | auth |
| GET | `/insights/metrics` | auth |
| POST | `/runs/{run_id}/findings/{finding_id}/feedback` | auth |
| GET | `/runs/{run_id}/feedback` | auth |
| GET | `/assets` | auth |
| GET | `/assets/{asset_id}` | auth |
| GET | `/suites` | auth |
| POST | `/suites` | auth |
| GET | `/suites/{suite_id}` | auth |
| DELETE | `/suites/{suite_id}` | auth |
| POST | `/suites/{suite_id}/cases` | auth |
| DELETE | `/suites/{suite_id}/cases/{case_id}` | auth |
| POST | `/suites/{suite_id}/run` | auth |
| POST | `/profiles/suggest` | auth |

## Insights, suites and finding feedback

* `GET /insights?days=30&project_id=` returns coverage, reliability, review and finding-quality measures with their definitions.
  `GET /insights/metrics` returns the same as Prometheus text (Team plan and above; `text/plain`).
* `POST /runs/{run_id}/findings/{finding_id}/feedback` records `useful`, `false_positive` or `unclear` (one rating per person per
  finding). Ratings feed Insights only; they never change a decision, a policy or a threshold.
* `/suites` (Starter plan and above) holds adjudicated examples. `POST /suites/{id}/run` takes `profile_id` and optional `policy_id`
  (or inline `profile` / `policy` documents) and returns per-example results with `looser` / `stricter` direction. Suite runs use
  deterministic checks only.
* `POST /profiles|policies/{id}/versions/{n}/publish` accepts `{"suite_ids": [...], "profile_id": "..."}`; a failing example stops
  the publication with `409 suite_failed`.
* `POST /profiles/suggest` drafts a profile from a sample (nothing is stored).
* `GET /assets` and `GET /assets/{id}` give per-asset version history, with the reasons that appeared or cleared between runs.
* Run metadata accepts `upstream_checks`, `great_expectations_result` and `soda_scan`; they are normalised into the
  `provenance.upstream` check.
