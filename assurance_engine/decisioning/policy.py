"""Hard rules that no customer policy can remove (the first rules in the ordered list)."""

from __future__ import annotations

from dataclasses import dataclass

from ...domain.decisions import Decision

__all__ = ["HardRule", "HARD_RULES", "match_hard_rule"]


@dataclass(frozen=True)
class HardRule:
    id: str
    prefix: str
    effect: Decision
    description: str
    quarantine_artifact: bool = False


HARD_RULES: tuple[HardRule, ...] = (
    HardRule("H1", "policy.prohibited_destination", Decision.BLOCK,
             "A prohibited destination blocks the requested operation."),
    HardRule("H2", "privacy.secret", Decision.BLOCK,
             "Credentials are never released; the artifact is kept in restricted storage.", True),
    HardRule("H3", "safety.malicious", Decision.QUARANTINE,
             "Malicious artifacts are isolated and cannot be waived.", True),
    HardRule("H4", "provenance.digest_mismatch", Decision.QUARANTINE,
             "An integrity mismatch isolates the artifact.", True),
    HardRule("H5", "safety.injection.tool", Decision.QUARANTINE,
             "Embedded tool/exfiltration directives isolate the artifact.", True),
)


def match_hard_rule(code: str) -> HardRule | None:
    for rule in HARD_RULES:
        if code.startswith(rule.prefix):
            return rule
    return None
