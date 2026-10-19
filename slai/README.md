# AIDAP ↔ SLAI adapters

AIDAP lives in `applications/AIDAP` and uses SLAI as its runtime. This package is the **only** place AIDAP touches SLAI
(the domain and the assurance engine never import it).

| AIDAP need | SLAI component reused | Module |
|---|---|---|
| Password hashing and policy | `src.functions.functions_memory.PasswordHasher`, `CredentialPolicy` | `infra/crypto/passwords.py` |
| Rate limiting | `src.functions.ratelimiter.RateLimiter` | `infra/ratelimit/limiter.py` |
| Signed, SSRF-guarded webhooks | `src.functions.webhook.WebhookService` | `infra/notifications/webhooks.py` |
| SSRF validation for scheduled fetches | `webhook._validate_endpoint_syntax`, `_assert_safe_destination` | `infra/net/safe_fetch.py` |
| E-mail | `src.functions.email.EmailService` | `infra/notifications/mailer.py` |
| Artifact storage / object delivery | `src.functions.storage.Storage`, `file_transfer.FileTransferService` | `infra/storage/blobstore.py` |
| Durable, verified stage outputs | `checkpointing.CheckpointManager` | `slai/checkpoint_store.py` |
| Second-opinion PII identification | `src.agents.privacy.data_id.DataID` | `slai/evaluators.py` |
| Tabular quality | `src.agents.quality_agent.QualityAgent` | `slai/evaluators.py` |
| Safety screening | `src.agents.safety_agent.SafetyAgent` | `slai/evaluators.py` |
| Lineage | `src.agents.provenance_agent.ProvenanceAgent` | `slai/evaluators.py`, `orchestration.py` |
| Model-assisted semantic review | `src.agents.language_agent.LanguageAgent` | `slai/reasoning_gateway.py` |
| PDF and DOCX reading, file identity and integrity | `src.agents.reader` (`DetectionEngine`, `IntegrityEngine`, `ParserEngine`) in a sandboxed process | `slai/reader_intake.py`, `slai/_reader_worker.py` |

`src/tuning` is intentionally **not** used: AIDAP trains and tunes nothing. See `docs/OVERLAP.md`.

If an agent cannot be built (torch missing, QualityMemory not migrated, ...) its check is recorded as
`NOT_EVALUATED`/`UNKNOWN` with SLAI's own error. A mandatory check in that state forces REVIEW; it is never a pass.
