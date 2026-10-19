# What AIDAP reuses from SLAI — and what it deliberately does not duplicate

AIDAP lives in `SLAI/applications/AIDAP`. Rule applied throughout: **if SLAI already has a tested capability, AIDAP calls it
through one adapter; it does not carry a second copy.** AIDAP code only exists where AIDAP's own domain (decisions, policies,
evidence, plans) has no SLAI counterpart. All SLAI access goes through `slai/` (agents) and `infra/` (functions); the domain,
engine and application layers never import SLAI.

## `src/functions` — reused

| Need | SLAI module used | AIDAP adapter |
|---|---|---|
| Password hashing and credential policy | `functions_memory` (`PasswordHasher`, `CredentialPolicy`) | `infra/crypto/passwords.py` |
| Request rate limiting | `ratelimiter` (`RateLimiter`) | `infra/ratelimit/limiter.py` |
| Webhook signing, header names, SSRF target validation, delivery | `webhook` (`WebhookService`, `sign_webhook_payload`) | `infra/notifications/webhooks.py`, `infra/net/safe_fetch.py` |
| E-mail (invitations, resets, contact form) | `email` (`EmailService`) | `infra/notifications/mailer.py` |
| Blob storage and verified transfer | `storage` (`LocalStorage`), `file_transfer` (`FileTransferService`) | `infra/storage/blobstore.py` |

Consequence: AIDAP webhooks carry SLAI's header names (`X-SLAI-Webhook-Id/-Timestamp/-Signature/-Event`) and signature scheme
(`v1=hex(HMAC_SHA256(secret, "<ts>.<event_id>.<body>"))`), so a receiver written for SLAI verifies AIDAP too.

### `src/functions` — considered and *not* used (not a duplicate)

| SLAI module | Why AIDAP does not use it |
|---|---|
| `auth.py` (`AuthService`) | Different model: SLAI's is an in-memory single-tenant user/session service with verification challenges. AIDAP needs multi-tenant memberships and roles, persistent sessions with CSRF, API keys with scopes, TOTP two-factor with recovery codes, invitations, and lock-out. AIDAP reuses SLAI's *password hashing and policy* (the shared part) and implements only the tenant/session/API-key layer on top. |
| `payment.py` (`PaymentService`) | A one-off authorize/capture/refund abstraction. AIDAP's billing is **subscriptions**, usage metering and plan entitlements with Stripe webhooks. There is no overlap in operations. |
| `phone_verification`, `search`, `sidebar`, `dropdown`, `loader`, `queries`, `codec`, `transport`, `utils/` | Not needed by any AIDAP requirement. |

### AIDAP-local crypto helpers (why they are not in `src/functions`)

`infra/crypto/secretbox.py` (AES-256-GCM sealing with key rotation), `tokens.py` (API-key / reset-token digests) and `totp.py`
(RFC 6238) have no counterpart in `src/functions` (verified by search for TOTP, AES-GCM and token digests). They are small and
standard-library or `cryptography` based.

## `checkpointing/` — reused, not re-implemented

* Stages 3–14 of the 20-stage workflow persist their outputs through SLAI's `CheckpointManager` (`slai/checkpoint_store.py`).
  AIDAP does **not** implement its own checkpoint format, manifest, verification or codec.
* What AIDAP stores itself is *not* a checkpoint: the per-run **stage ledger** (`run_stages` rows: state, attempt, timing, metrics)
  and the **job ledger** (queue leases, attempts). The whitepaper calls for "SLAI checkpoints plus AIDAP job ledger"; checkpoints
  hold stage *outputs*, the ledgers answer "what ran, when, and how often" for the UI, billing idempotency and retries.
* If SLAI's checkpointing cannot be imported, `slai/checkpoint_store.py` falls back to storing stage outputs in the database and
  `System & SLAI status` reports `degraded: true`. This is a fail-safe, not a second implementation to keep in sync.
* Known SLAI issue, **not edited here**: several checkpoint codecs call `logger.info("… with", value)` without a `%s`, which makes
  Python's logging print a harmless "--- Logging error ---". AIDAP's CLI installs a tolerant log filter instead of modifying SLAI.

## `src/tuning/` — intentionally unused

`src/tuning` is a hyper-parameter tuning lifecycle (search strategies, trial evaluation, promotion, artifact persistence). AIDAP
trains no model and tunes no parameters, so nothing imports it. Thresholds in AIDAP profiles and policies are **declared
configuration**, versioned and published by people (with segregation of duties), not learned values. If calibration studies are
later run on AIDAP's confidence scores, they would call `src/tuning` from outside the product code path.

## SLAI agents — used through `slai/`

| Capability | SLAI agent | Behaviour when unavailable |
|---|---|---|
| Personal-data identification | `DataID` | Native detectors still run; `slai.privacy` is `not_evaluated` |
| Quality | `QualityAgent` (needs `quality_memory_migrate.py --apply`) | `slai.quality` is `not_evaluated` |
| Safety | `SafetyAgent` (needs torch) | `slai.safety` is `not_evaluated` |
| Provenance | `ProvenanceAgent` | `slai.provenance` is `not_evaluated` |
| Language / semantic | `LanguageAgent` (needs torch) | `slai.semantic` is `not_evaluated` |

Agent output is mapped to AIDAP findings in `slai/result_mapper.py`: severity capped at HIGH, origin recorded as `slai`, and
context-free detections (for example a bare date flagged as a date of birth) are ignored rather than escalated.
