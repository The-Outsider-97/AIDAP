"""Canonical forms used to compute the normalized digest."""

from __future__ import annotations

import json
import unicodedata
from typing import Any

from ...domain.utils.domain_helpers import digest_ref

__all__ = ["canonical_text", "canonical_records", "normalized_digest"]


def canonical_text(text: str) -> str:
    return unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n")


def canonical_records(records: list[dict[str, Any]]) -> str:
    return json.dumps(records, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def normalized_digest(kind: str, text: str, records: list[dict[str, Any]] | None) -> str:
    if kind == "records" and records is not None:
        return digest_ref("records:" + canonical_records(records))
    return digest_ref("text:" + canonical_text(text))
