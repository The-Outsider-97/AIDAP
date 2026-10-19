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
| PDF and Word reading | `ReaderAgent` subsystem: `DetectionEngine`, `IntegrityEngine` (+ `ExpansionGuard`), `ParserEngine` | PDF and DOCX are reported as unsupported, as before |

Agent output is mapped to AIDAP findings in `slai/result_mapper.py`: severity capped at HIGH, origin recorded as `slai`, and
context-free detections (for example a bare date flagged as a date of birth) are ignored rather than escalated.

### How the Reader is used (`slai/reader_intake.py`, `slai/_reader_worker.py`)

AIDAP's own parsers read text, Markdown, HTML, JSON, JSON Lines, CSV and TSV. PDF and Word are the formats RAG corpora mostly consist of,
and SLAI already has the pieces to read them safely, so AIDAP calls those instead of writing a second PDF/DOCX reader:

* `DetectionEngine` — identity from content, not from the file name (a PDF named `.docx` is flagged); encrypted and damaged containers.
* `IntegrityEngine` — ZIP structure and expansion limits (decompression bombs), required package members, CRCs, PDF trailer and page tree.
* `ParserEngine` — text extraction (`pypdf`, Word XML).

It runs in a **separate sandboxed process** (CPU, memory, file-size and process limits on POSIX; wall-clock timeout everywhere), reads the
file from a private directory that is removed afterwards, and its output is a plain JSON document. Two deliberate deviations from "just
call the agent":

1. `ReaderMemory` (Reader's disk cache of parsed content) is **not used** and SLAI's logger is replaced by a silent one in that process.
   Both would put customer content outside AIDAP's retention, deletion and tenant boundaries.
2. Reader's `salvage`, `recovery`, `conversion` and `compression` engines are **not used**. AIDAP validates the file the customer sent;
   it never repairs, rewrites or recompresses it, because the released artifact must be byte-identical to what was assessed.

What AIDAP adds because Reader has no equivalent: scripts, launch actions and attachments in PDFs; macros, embedded objects and remote
templates in Word files; Word text formatted as hidden; refusal of XML with DTD/entity declarations; document properties (title, author,
dates) as provenance hints. Limits that remain: scanned PDFs have no text layer and are reported as *not read* (no OCR); Word headers,
footers, footnotes and comments are not read; hidden text in PDFs (for example white-on-white) cannot be detected from extracted text.

## SLAI agents reviewed and *not* integrated

Added only where it fixes a gap that was verified in AIDAP. Read in some depth: Reader, Alignment, Knowledge, Observability,
Verification, Evaluation (and the whitepaper's own assessment of Evaluation, Reasoning, Execution, Adaptive/Learning). The remainder
were judged from their purpose and the whitepaper's Table 4, not read line by line.

| Agent | Decision | Reason |
|---|---|---|
| Alignment (bias/fairness) | Not now | Needs the customer to declare protected attributes and an outcome column, which no AIDAP profile carries; fairness conclusions are a legal/organisational judgement (whitepaper: out of the product's remit). A candidate `training_batch` check if customers ask; it needs a profile-schema change first. |
| Knowledge | No | Retrieval, ontology and governance for SLAI's own knowledge. AIDAP's conflict, supersession and freshness checks are native and deterministic. |
| Observability | No | Analyses SLAI's multi-agent runtime telemetry. AIDAP's operational data comes from its own stage and job ledgers; there is nothing to feed it. |
| Verification | No | Formal model checking over explicit formal models; not a data validator. |
| Evaluation | No | Whitepaper: code/system evaluation, not a trained general AI-input anomaly service. |
| Reasoning | Later | Whitepaper: optional later use for explicit domain rules; AIDAP policies already express those. |
| Execution, Adaptive, Learning | No | Whitepaper: unused in a read-only gate; no live policy changes. |
| Handler | No | Fallback/retry policy at execution time. AIDAP's queue already retries and dead-letters, and metering must stay idempotent. |
| Orchestrator, Planning, Collaborative | No | AIDAP runs a fixed 20-stage plan on purpose (whitepaper: no autonomous negotiation for routine checks). |
| Perception | No | Images/audio; OCR is out of the initial scope. Scanned PDFs are reported as unread instead of guessed. |
| Browser, Network, QNN, Spatial, STEM, Simulation, Optimization | No | No data-assurance function for AIDAP's inputs. |

## Operating measures, test suites and near-duplicate detection — native by design

| Capability | Where | Reuse decision |
|---|---|---|
| Insights, review SLA, Prometheus export | `app/services/insights.py` | Native. Computed from AIDAP's own run, review, delivery and feedback ledgers. SLAI's Observability agent analyses SLAI runtime telemetry, which AIDAP does not produce, so it is still not used. |
| Test suites and publish gate | `app/services/suites.py` | Reuses AIDAP's `SimulationService`; no second evaluator. Suites run deterministic checks only, so results are repeatable. |
| Near-duplicates and outliers | `assurance_engine/evaluators/quality/similarity.py`, `population.py` | Native and deterministic (shingle Jaccard with a bounded sketch index; robust z-score). `slai.quality` stays an optional heuristic add-on and its findings are capped at Review. |
| Upstream monitoring signals | `assurance_engine/ingestion/signals.py`, `provenance.upstream` | Consumes Great Expectations, Soda and generic results as asserted by the submitter. AIDAP does not run warehouse monitoring. |
| Profile suggestion | `SuggestionService` | Uses `detect_all` and the existing profile schema and lint; nothing is stored until the user saves a draft. |
| Webhook relay example | `sdk/examples/slack_relay.py` | Uses the existing signed envelope from `src/functions`; no new delivery path. |

Not duplicated: `checkpointing/` (stage restart), `src/tuning/` (unused), `src/functions` (signing, rate limiting, webhooks).
