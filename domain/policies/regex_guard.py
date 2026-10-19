"""Conservative guard for customer-supplied regular expressions (ReDoS defence).

Python's ``re`` has no execution timeout, so patterns are restricted rather than
trusted: bounded length, no backreferences/lookarounds, and no nested or
adjacent unbounded quantifiers. Evaluators additionally cap the text length a
customer pattern may scan.
"""

from __future__ import annotations

import re

__all__ = ["check_regex", "compile_safe", "MAX_PATTERN_LEN", "MAX_SCAN_CHARS"]

MAX_PATTERN_LEN = 200
MAX_SCAN_CHARS = 2_000_000

_NESTED = re.compile(r"\((?:[^()\\]|\\.)*[+*](?:[^()\\]|\\.)*\)\s*[+*{]")
_BACKREF = re.compile(r"\\[1-9]|\(\?P=|\\k<")
_LOOK = re.compile(r"\(\?(?:=|!|<=|<!)")
_ADJ = re.compile(r"(?:\.\*|\.\+)(?:[^|)]{0,3})(?:\.\*|\.\+)")


def check_regex(pattern: str) -> str | None:
    """Return a reason the pattern is rejected, or ``None`` when acceptable."""
    if not isinstance(pattern, str) or not pattern:
        return "pattern must be a non-empty string"
    if len(pattern) > MAX_PATTERN_LEN:
        return f"pattern longer than {MAX_PATTERN_LEN} characters"
    if _BACKREF.search(pattern):
        return "backreferences are not allowed"
    if _LOOK.search(pattern):
        return "lookaround assertions are not allowed"
    if _NESTED.search(pattern):
        return "nested quantifiers are not allowed"
    if _ADJ.search(pattern):
        return "adjacent unbounded wildcards are not allowed"
    if re.search(r"\{\d{4,}", pattern) or re.search(r",\d{4,}\}", pattern):
        return "repetition bound too large"
    try:
        re.compile(pattern)
    except re.error as exc:
        return f"invalid pattern: {exc}"
    return None


def compile_safe(pattern: str, flags: int = re.IGNORECASE) -> "re.Pattern[str] | None":
    if check_regex(pattern) is not None:
        return None
    return re.compile(pattern, flags)
