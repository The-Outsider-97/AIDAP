"""Severity vocabulary. Severity is separate from confidence and from effect."""

from __future__ import annotations

from enum import Enum

__all__ = ["Severity"]


class Severity(str, Enum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    @property
    def rank(self) -> int:
        return ("info", "low", "medium", "high", "critical").index(self.value)

    def __lt__(self, other: "Severity") -> bool:  # type: ignore[override]
        return self.rank < other.rank

    def __le__(self, other: "Severity") -> bool:  # type: ignore[override]
        return self.rank <= other.rank

    def __gt__(self, other: "Severity") -> bool:  # type: ignore[override]
        return self.rank > other.rank

    def __ge__(self, other: "Severity") -> bool:  # type: ignore[override]
        return self.rank >= other.rank

    @classmethod
    def parse(cls, value: "str | Severity | None", default: "Severity" = None) -> "Severity":  # type: ignore[assignment]
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value).strip().lower())
        except ValueError:
            return default or cls.MEDIUM
