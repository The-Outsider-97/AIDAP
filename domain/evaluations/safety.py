"""Safety, provenance and SLAI-backed checks in the AIDAP catalog."""

from __future__ import annotations

from .models import Category, CheckSpec, FailureClass, Origin

__all__ = ["SAFETY_CHECKS", "PROVENANCE_CHECKS", "SLAI_CHECKS"]

SAFETY_CHECKS: tuple[CheckSpec, ...] = (
    CheckSpec("safety.file", Category.SAFETY, 10, "File safety", "D",
              "Executable/archive signatures, macro containers, malware scan result.",
              FailureClass.ADVERSARIAL, default_mandatory=True),
    CheckSpec("safety.injection", Category.SAFETY, 10, "Embedded instructions", "D",
              "Prompt-injection and tool-hijack patterns, hidden text, control characters.",
              FailureClass.ADVERSARIAL, default_mandatory=True),
)

PROVENANCE_CHECKS: tuple[CheckSpec, ...] = (
    CheckSpec("provenance.origin", Category.PROVENANCE, 11, "Origin and ownership", "D",
              "Source identity, owner and revision metadata. Asserted origin is not verified origin.",
              FailureClass.PROVENANCE),
    CheckSpec("provenance.upstream", Category.PROVENANCE, 11, "Upstream monitoring signals", "D",
              "Results that data-quality and observability tools reported about the input (Great Expectations, Soda, "
              "Monte Carlo and similar). Asserted by the submitter: a failure adds a finding, a pass proves nothing.",
              FailureClass.PROVENANCE),
)

SLAI_CHECKS: tuple[CheckSpec, ...] = (
    CheckSpec("slai.quality", Category.QUALITY, 4, "SLAI Quality Agent", "D",
              "SLAI structural, statistical and semantic quality subsystems via the governed adapter.",
              FailureClass.POPULATION, origin=Origin.SLAI),
    CheckSpec("slai.semantic", Category.SEMANTIC, 8, "SLAI semantic reasoning", "M",
              "Optional SLAI Reasoning/Knowledge-assisted contradiction and relevance review. "
              "Findings are capped at REVIEW.", FailureClass.SEMANTIC, origin=Origin.MODEL, external=True),
    CheckSpec("slai.privacy", Category.PRIVACY, 9, "SLAI Privacy Agent", "D",
              "SLAI data identification, consent/purpose and minimization checks.",
              FailureClass.PRIVACY, origin=Origin.SLAI),
    CheckSpec("slai.safety", Category.SAFETY, 10, "SLAI Safety Agent", "D",
              "SLAI safety, cyber-safety and sanitization checks over untrusted input.",
              FailureClass.ADVERSARIAL, origin=Origin.SLAI),
    CheckSpec("slai.provenance", Category.PROVENANCE, 11, "SLAI provenance", "D",
              "SLAI provenance lineage and custody assessment of declared origin metadata.",
              FailureClass.PROVENANCE, origin=Origin.SLAI),
)
