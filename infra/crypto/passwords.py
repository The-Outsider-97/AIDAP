"""Password policy + hashing: SLAI's scrypt ``PasswordHasher`` and ``CredentialPolicy`` behind AIDAP's port."""

from __future__ import annotations

from ...domain.utils.domain_errors import ValidationFailed
from ...slai.runtime import functions

__all__ = ["SlaiPasswordService"]


class SlaiPasswordService:
    def __init__(self, pepper: str, min_length: int = 12) -> None:
        mem = functions("functions_memory")
        self._hasher = mem.PasswordHasher(pepper=pepper)
        self._policy = mem.CredentialPolicy(min_length=min_length)
        self._policy_error = mem.CredentialPolicyError

    def validate(self, password: str) -> None:
        try:
            self._policy.validate(password)
        except self._policy_error as exc:
            violations = list(getattr(exc, "violations", None) or [str(exc)])
            raise ValidationFailed("password does not meet the credential policy",
                                   details={"fields": {"password": "; ".join(violations)}}) from exc

    def hash(self, password: str) -> tuple[str, str]:
        return self._hasher.hash_password(password)

    def verify(self, password: str, salt: str, digest: str) -> bool:
        return bool(self._hasher.verify_password(password, salt, digest))
