"""The sealed evidence bundle (schema ``aidap.evidence/1``).

The seal is a SHA-256 over the canonical JSON of everything except the seal
itself. It detects tampering after the fact; it is not a signature and does
not prove who produced the bundle.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..utils.domain_errors import IntegrityViolation
from ..utils.domain_helpers import canonical_digest, canonical_json, to_jsonable

__all__ = ["EVIDENCE_SCHEMA", "EvaluatorVersion", "EvidenceBundle", "seal", "verify_bundle"]

EVIDENCE_SCHEMA = "aidap.evidence/1"


@dataclass(frozen=True)
class EvaluatorVersion:
    id: str
    name: str
    version: str
    origin: str = "native"
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "version": self.version, "origin": self.origin,
                "detail": self.detail}


def seal(body: dict[str, Any]) -> str:
    material = {k: v for k, v in body.items() if k != "seal"}
    return canonical_digest(material)


def verify_bundle(bundle: dict[str, Any]) -> bool:
    if not isinstance(bundle, dict) or bundle.get("schema") != EVIDENCE_SCHEMA:
        return False
    return bundle.get("seal") == seal(bundle)


@dataclass
class EvidenceBundle:
    body: dict[str, Any] = field(default_factory=dict)

    @property
    def digest(self) -> str:
        return str(self.body.get("seal", ""))

    def sealed(self) -> "EvidenceBundle":
        data = to_jsonable(self.body)
        data["schema"] = EVIDENCE_SCHEMA
        data["seal"] = seal(data)
        return EvidenceBundle(data)

    def verify(self) -> bool:
        return verify_bundle(self.body)

    def to_dict(self) -> dict[str, Any]:
        return self.body

    def to_json(self) -> str:
        return canonical_json(self.body)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "EvidenceBundle":
        if d.get("schema") != EVIDENCE_SCHEMA:
            raise IntegrityViolation("unknown evidence schema")
        return cls(dict(d))
