"""Source-metadata handling: what a submitter *asserts* about an input.

Nothing here verifies an assertion. Verified origin would need signatures
(not offered in v1), so the evidence says ``asserted``.
"""

from __future__ import annotations

from typing import Any

__all__ = ["ALIASES", "normalize_source_metadata", "lookup"]

ALIASES: dict[str, tuple[str, ...]] = {
    "owner": ("owner", "author", "maintainer", "team", "dc.creator"),
    "source_id": ("source_id", "source", "source_url", "url", "canonical", "origin"),
    "source_revision": ("source_revision", "revision", "version", "rev", "doc_version"),
    "effective_date": ("effective_date", "effective", "published", "published_at", "date", "created",
                       "created_at", "updated", "updated_at", "last_modified", "modified", "last_updated"),
    "expires_at": ("expires_at", "expiry", "expires", "valid_until", "review_by", "expiration_date"),
    "supersedes": ("supersedes", "replaces"),
    "superseded_by": ("superseded_by", "replaced_by"),
    "audience": ("audience",),
    "sha256": ("sha256", "content_sha256", "digest"),
    "language": ("language", "lang"),
}


def normalize_source_metadata(*layers: dict[str, Any]) -> dict[str, Any]:
    """Merge metadata layers (later layers do not override earlier ones: submitter-declared wins)."""
    merged: dict[str, Any] = {}
    for layer in layers:
        for k, v in (layer or {}).items():
            key = str(k).strip().lower().replace(" ", "_").replace("-", "_")
            if key not in merged and v not in (None, ""):
                merged[key] = v
    return merged


def lookup(meta: dict[str, Any], canonical: str) -> Any:
    for alias in ALIASES.get(canonical, (canonical,)):
        if alias in meta and meta[alias] not in (None, ""):
            return meta[alias]
    return None
