"""Versioned interchange contracts. A breaking change gets a new suffix, never an in-place edit."""

from __future__ import annotations

from ..domain.evidence import EVIDENCE_SCHEMA
from ..version import API_VERSION

__all__ = ["CONTRACTS", "DECISION_SCHEMA", "REPORT_SCHEMA", "WEBHOOK_SCHEMA", "SLAI_REQUEST_SCHEMA",
           "SLAI_RESPONSE_SCHEMA", "ERROR_SCHEMA", "API_VERSION"]

DECISION_SCHEMA = "aidap.decision/1"
REPORT_SCHEMA = "aidap.report/1"
WEBHOOK_SCHEMA = "aidap.webhook/1"
SLAI_REQUEST_SCHEMA = "aidap.slai.request/1"
SLAI_RESPONSE_SCHEMA = "aidap.slai.response/1"
ERROR_SCHEMA = "aidap.error/1"

CONTRACTS: dict[str, str] = {
    "evidence": EVIDENCE_SCHEMA,
    "decision": DECISION_SCHEMA,
    "report": REPORT_SCHEMA,
    "webhook": WEBHOOK_SCHEMA,
    "slai_request": SLAI_REQUEST_SCHEMA,
    "slai_response": SLAI_RESPONSE_SCHEMA,
    "error": ERROR_SCHEMA,
}
