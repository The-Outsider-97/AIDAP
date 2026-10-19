"""Privacy checks in the AIDAP catalog."""

from __future__ import annotations

from .models import Category, CheckSpec, FailureClass, Origin

__all__ = ["PRIVACY_CHECKS"]

PRIVACY_CHECKS: tuple[CheckSpec, ...] = (
    CheckSpec("privacy.pii", Category.PRIVACY, 9, "Personal data and secrets", "D",
              "Locally detected personal data and credentials, validated where checksums exist.",
              FailureClass.PRIVACY, default_mandatory=True),
    CheckSpec("privacy.destination", Category.PRIVACY, 9, "Destination permissions", "D",
              "Detected sensitive types against the destination class and profile restrictions.",
              FailureClass.PRIVACY, default_mandatory=True),
)
