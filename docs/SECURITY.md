# Security model

* **Fail-closed decisions.** A mandatory check that is unknown, errored or not evaluated can never produce PASS. Model-origin findings are
  capped at REVIEW; shadow policies never authorize release; `FitnessDecision.release_authorized()` is the single release gate (active,
  non-shadow, PASS, unexpired, digest unchanged).
* **Non-waivable findings** (`privacy.secret`, `safety.malicious`, `safety.file.malware`, `safety.injection.tool`, `incomplete.safety`,
  `policy.prohibited_destination`) cannot be excepted by anyone.
* **Segregation of duties** for baseline approval, policy publishing and exceptions (the submitter cannot approve when another eligible reviewer exists).
* **Authentication.** Salted slow password hashing and policy (SLAI `functions_memory`), lock-out, TOTP two-factor with single-use recovery
  codes, HTTP-only session cookies, CSRF token on all non-GET requests, Origin check, scoped hashed API keys.
* **Transport and browser.** Strict CSP (no inline scripts), `X-Frame-Options`, `Referrer-Policy`, `no-store` on API responses.
* **Data.** Artifacts are sealed with AES-256-GCM with the object key as associated data; secrets are sealed with the same box; keys rotate (list newest first).
* **Webhooks and schedules.** HTTPS only, SSRF-validated (SLAI `webhook`), HMAC-signed with a timestamp; payloads are metadata only.
* **Evidence and audit.** SHA-256-sealed evidence bundles; append-only (database triggers) hash-chained audit log with a verifier.
* **Input handling.** Parsing in an isolated process with size/time limits; CSV exports neutralise spreadsheet formulas; HTML reports are escaped and script-free.
* **Retention, deletion and export.** Content and evidence are purged when the plan's retention window ends (open reviews and held quarantine are exempt); admins can delete a finished run's stored content earlier (`DELETE /runs/{id}/content`); owners can export the organisation's records (`GET /account/export`, no content or credentials). Decisions and the audit log are kept — they are the record. Legal holds and backup expiry are an operator procedure, not a product feature (see `docs/DEPLOYMENT.md`).
* **Documents.** PDF and Word files are read only in a separate sandboxed process (SLAI Reader) from a private directory that is deleted afterwards; decompression bombs, XML entity declarations, encrypted and damaged files are refused; PDF scripts/launch actions/attachments and Word macros/embedded objects/remote templates become findings; no copy of the content is cached outside AIDAP's own store.
* **Quarantine.** Content is readable only after a stated purpose, for a 15-minute window, and every access is audited.

Report vulnerabilities to info.remy3design@gmail.com.

## Test suites, feedback and metrics

* Suite example content is stored in the blob store, sealed like run inputs, limited to 200 KB per example, 100 examples per suite and
  20 suites per workspace. It is removed with the example or the suite and is included in neither exports nor webhooks.
* Suite runs call the simulation path: nothing is released, delivered, metered as a run or sent to a model.
* Finding feedback is opinion. It is attributed, one rating per person per finding, and it never alters a decision, a policy or a
  threshold. Insights present it as reviewer opinion rather than accuracy.
* `GET /insights/metrics` exposes aggregate counts only (no filenames, content or user identifiers) and requires an authenticated
  principal with run read access and the Team plan or above.
* The MCP server (`python -m aidap_sdk.mcp`) returns decisions, reason codes and finding metadata. It never returns checked content.
