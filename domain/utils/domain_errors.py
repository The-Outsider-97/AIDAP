"""AIDAP domain-layer error hierarchy.

Every error carries a stable machine-readable ``code`` and the HTTP status the
API layer should use, so that transport code never has to guess.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "AIDAPError",
    "ValidationFailed",
    "NotFound",
    "Conflict",
    "Unauthenticated",
    "Forbidden",
    "QuotaExceeded",
    "FeatureNotInPlan",
    "RateLimited",
    "Unavailable",
    "InvalidTransition",
    "IntegrityViolation",
    "PayloadTooLarge",
    "UnsupportedMedia",
]


class AIDAPError(Exception):
    """Base class for all expected, typed AIDAP failures."""

    code = "aidap_error"
    http_status = 500

    def __init__(self, message: str = "", *, code: str | None = None,
                 details: dict[str, Any] | None = None) -> None:
        super().__init__(message or self.code)
        self.message = message or self.code
        if code:
            self.code = code
        self.details: dict[str, Any] = dict(details or {})

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details:
            out["details"] = self.details
        return out


class ValidationFailed(AIDAPError):
    code = "validation_failed"
    http_status = 422


class NotFound(AIDAPError):
    code = "not_found"
    http_status = 404


class Conflict(AIDAPError):
    code = "conflict"
    http_status = 409


class InvalidTransition(Conflict):
    code = "invalid_transition"


class Unauthenticated(AIDAPError):
    code = "unauthenticated"
    http_status = 401


class Forbidden(AIDAPError):
    code = "forbidden"
    http_status = 403


class QuotaExceeded(AIDAPError):
    code = "quota_exceeded"
    http_status = 402


class FeatureNotInPlan(AIDAPError):
    code = "feature_not_in_plan"
    http_status = 402


class RateLimited(AIDAPError):
    code = "rate_limited"
    http_status = 429


class Unavailable(AIDAPError):
    code = "unavailable"
    http_status = 503


class PayloadTooLarge(AIDAPError):
    code = "payload_too_large"
    http_status = 413


class UnsupportedMedia(AIDAPError):
    code = "unsupported_media"
    http_status = 415


class IntegrityViolation(AIDAPError):
    code = "integrity_violation"
    http_status = 500
