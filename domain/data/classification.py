"""Data classification, source and destination vocabularies."""

from __future__ import annotations

from enum import Enum

__all__ = ["DataClassification", "SourceClass", "DestinationClass", "DeliveryKind"]


class DataClassification(str, Enum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"

    @property
    def rank(self) -> int:
        return {"public": 0, "internal": 1, "confidential": 2, "restricted": 3}[self.value]

    @classmethod
    def parse(cls, value: "str | DataClassification | None", default: "DataClassification | None" = None) -> "DataClassification":
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value).strip().lower())
        except ValueError:
            return default or cls.INTERNAL


class SourceClass(str, Enum):
    PUBLISHED = "published"            # public manuals, docs
    INTERNAL_DOC = "internal_doc"      # internal knowledge base
    CUSTOMER_UPLOAD = "customer_upload"
    THIRD_PARTY = "third_party"
    GENERATED = "generated"            # model- or script-generated content
    UNKNOWN = "unknown"

    @classmethod
    def parse(cls, value: "str | SourceClass | None") -> "SourceClass":
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value).strip().lower())
        except ValueError:
            return cls.UNKNOWN


class DestinationClass(str, Enum):
    """Where an approved artifact is going. Exposure rank is monotonic: a more
    exposed destination can only tighten, never loosen, what is permitted."""

    LOCAL_INDEX = "local_index"
    INTERNAL_MODEL = "internal_model"
    TRAINING_SET = "training_set"
    EXTERNAL_MODEL = "external_model"
    PUBLIC_ENDPOINT = "public_endpoint"

    @property
    def exposure(self) -> int:
        return {"local_index": 0, "internal_model": 1, "training_set": 1,
                "external_model": 2, "public_endpoint": 3}[self.value]

    @property
    def is_external(self) -> bool:
        return self.exposure >= 2

    @classmethod
    def parse(cls, value: "str | DestinationClass | None") -> "DestinationClass":
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value).strip().lower())
        except ValueError:
            return cls.LOCAL_INDEX


class DeliveryKind(str, Enum):
    PULL = "pull"                 # consumer fetches the approved artifact
    WEBHOOK = "webhook"           # signed notification (+ fetch URL)
    OBJECT_STORE = "object_store"  # PUT to a customer-owned object store URL
