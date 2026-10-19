"""Sensitive information types and their default handling."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ..evaluations.severity import Severity

__all__ = ["SensitiveType", "SensitiveSpec", "SENSITIVE_TYPES"]


class SensitiveType(str, Enum):
    EMAIL = "email"
    PHONE = "phone"
    IBAN = "iban"
    CREDIT_CARD = "credit_card"
    NATIONAL_ID = "national_id"
    IP_ADDRESS = "ip_address"
    API_SECRET = "api_secret"
    PRIVATE_KEY = "private_key"
    PASSWORD_ASSIGNMENT = "password_assignment"
    ACCESS_TOKEN = "access_token"
    DATE_OF_BIRTH = "date_of_birth"


@dataclass(frozen=True)
class SensitiveSpec:
    type: SensitiveType
    label: str
    severity: Severity
    is_secret: bool          # credentials: never acceptable for external destinations
    redactable: bool = True


SENSITIVE_TYPES: dict[SensitiveType, SensitiveSpec] = {
    s.type: s for s in (
        SensitiveSpec(SensitiveType.EMAIL, "email address", Severity.MEDIUM, False),
        SensitiveSpec(SensitiveType.PHONE, "phone number", Severity.MEDIUM, False),
        SensitiveSpec(SensitiveType.IBAN, "bank account (IBAN)", Severity.HIGH, False),
        SensitiveSpec(SensitiveType.CREDIT_CARD, "payment card number", Severity.HIGH, False),
        SensitiveSpec(SensitiveType.NATIONAL_ID, "national identifier", Severity.HIGH, False),
        SensitiveSpec(SensitiveType.IP_ADDRESS, "IP address", Severity.LOW, False),
        SensitiveSpec(SensitiveType.API_SECRET, "API key or secret", Severity.CRITICAL, True),
        SensitiveSpec(SensitiveType.PRIVATE_KEY, "private key", Severity.CRITICAL, True),
        SensitiveSpec(SensitiveType.PASSWORD_ASSIGNMENT, "password assignment", Severity.HIGH, True),
        SensitiveSpec(SensitiveType.ACCESS_TOKEN, "access token", Severity.CRITICAL, True),
        SensitiveSpec(SensitiveType.DATE_OF_BIRTH, "date of birth", Severity.MEDIUM, False),
    )
}
