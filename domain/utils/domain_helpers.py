"""Shared, dependency-free helpers for the AIDAP domain."""

from __future__ import annotations

import dataclasses
import enum
import hashlib
import json
import re
import secrets
from datetime import date, datetime, timedelta, timezone
from typing import Any

__all__ = [
    "utcnow", "iso", "parse_iso", "parse_date_lenient", "new_id", "sha256_hex",
    "canonical_json", "canonical_digest", "digest_ref", "to_jsonable", "period_key",
    "mask_value", "clamp", "slugify", "add_days", "EMAIL_RE",
]

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


_DATE_FORMATS = ("%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y", "%d/%m/%Y", "%Y%m%d", "%d %B %Y", "%B %d, %Y", "%d %b %Y")


def parse_date_lenient(value: Any) -> datetime | None:
    """Parse a date from common formats; ``None`` if it is not a date."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or len(text) > 40:
        return None
    try:
        return parse_iso(text)
    except ValueError:
        pass
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def add_days(value: datetime, days: int) -> datetime:
    return value + timedelta(days=days)


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(10)}"


def sha256_hex(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def digest_ref(data: bytes | str) -> str:
    return "sha256:" + sha256_hex(data)


def to_jsonable(value: Any) -> Any:
    """Convert dataclasses, enums, datetimes and containers to JSON-safe data."""
    if isinstance(value, enum.Enum):
        return to_jsonable(value.value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return iso(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, bytes):
        return {"$bytes_sha256": sha256_hex(value), "size": len(value)}
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        if hasattr(value, "to_dict"):
            return to_jsonable(value.to_dict())
        return {f.name: to_jsonable(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        items = sorted(value, key=str) if isinstance(value, (set, frozenset)) else value
        return [to_jsonable(v) for v in items]
    if hasattr(value, "to_dict"):
        return to_jsonable(value.to_dict())
    return str(value)


def canonical_json(value: Any) -> str:
    return json.dumps(to_jsonable(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def canonical_digest(value: Any) -> str:
    return digest_ref(canonical_json(value))


def period_key(moment: datetime | None = None) -> str:
    """Billing/usage period key (calendar month, UTC)."""
    moment = moment or utcnow()
    return f"{moment.year:04d}-{moment.month:02d}"


def mask_value(value: str, keep: int = 2) -> str:
    """Mask a sensitive string for display: keeps only a short prefix."""
    if not value:
        return ""
    if len(value) <= keep + 2:
        return "*" * len(value)
    return value[:keep] + "*" * min(len(value) - keep, 12)


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def slugify(text: str, default: str = "item") -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return slug[:48] or default
