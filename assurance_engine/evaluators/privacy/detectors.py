"""Local sensitive-data detectors with structural validation where a checksum exists.

All patterns are fixed, linear-time constructs written for this module (no
customer input), so scanning cost is bounded by input length.
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass

from ....domain.data.sensitivity import SensitiveType

__all__ = ["Hit", "scan_text", "luhn_ok", "iban_ok", "bsn_ok", "MAX_UNIT_CHARS"]

MAX_UNIT_CHARS = 2_000_000


@dataclass(frozen=True)
class Hit:
    type: SensitiveType
    start: int
    end: int
    validated: bool          # checksum/structure verified (vs. pattern-only)
    detail: str = ""


# ------------------------------------------------------------------------------------------ validators
def luhn_ok(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = ord(ch) - 48
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        alt = not alt
    return total % 10 == 0


_IBAN_LEN = {"NL": 18, "DE": 22, "BE": 16, "FR": 27, "GB": 22, "ES": 24, "IT": 27, "PT": 25, "IE": 22, "LU": 20,
             "AT": 20, "CH": 21, "DK": 18, "SE": 24, "NO": 15, "FI": 18, "PL": 28, "CZ": 24, "GR": 27, "HU": 28}


def iban_ok(raw: str) -> bool:
    s = re.sub(r"\s+", "", raw).upper()
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{11,30}", s):
        return False
    expected = _IBAN_LEN.get(s[:2])
    if expected is not None and len(s) != expected:
        return False
    rearranged = s[4:] + s[:4]
    num = "".join(str(int(c, 36)) for c in rearranged)
    return int(num) % 97 == 1


def bsn_ok(digits: str) -> bool:
    """Dutch BSN 11-proef."""
    if len(digits) != 9 or not digits.isdigit() or digits == "000000000":
        return False
    weights = (9, 8, 7, 6, 5, 4, 3, 2, -1)
    return sum(int(d) * w for d, w in zip(digits, weights)) % 11 == 0


def _ssn_ok(s: str) -> bool:
    a, g, n = s.split("-")
    return a not in ("000", "666") and not a.startswith("9") and g != "00" and n != "0000"


# ------------------------------------------------------------------------------------------ patterns
_EMAIL = re.compile(r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9-]{1,63}(?:\.[A-Za-z0-9-]{1,63}){1,6}(?![A-Za-z0-9-])")
_PHONE_INTL = re.compile(r"(?<![\w+])(?:\+|00)[1-9]\d{0,2}(?:[ .()-]?\d){7,12}(?!\d)")
_PHONE_NAT = re.compile(r"(?<![\w+])\(?0\d{1,3}\)?[ .-]\d{3,4}[ .-]?\d{3,4}(?!\d)")
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{4}){2,7}(?:[ ]?[A-Z0-9]{1,4})?\b")
_CARD = re.compile(r"(?<![\d-])(?:\d[ -]?){12,18}\d(?![\d-])")
_SSN = re.compile(r"(?<![\d-])\d{3}-\d{2}-\d{4}(?![\d-])")
_NATID_CTX = re.compile(r"(?i)\b(?:bsn|burgerservice(?:nummer)?|sofi(?:nummer)?|social security|ssn|national id|"
                        r"passport(?: number| no)?|identity (?:card|number))\b[^\n]{0,24}?(\d{9})\b")
_IPV4 = re.compile(r"(?<![\w.])(?:25[0-5]|2[0-4]\d|1?\d?\d)(?:\.(?:25[0-5]|2[0-4]\d|1?\d?\d)){3}(?![\w.])")
_DOB = re.compile(r"(?i)\b(?:date of birth|dob|birth ?date|born(?: on)?|geboortedatum|geboren)\b[^\n]{0,12}?"
                  r"(\d{4}-\d{2}-\d{2}|\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4})")

_SECRET_PATTERNS: tuple[tuple[SensitiveType, re.Pattern[str], str], ...] = (
    (SensitiveType.API_SECRET, re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), "AWS access key id"),
    (SensitiveType.ACCESS_TOKEN, re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,255}\b"), "GitHub token"),
    (SensitiveType.ACCESS_TOKEN, re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,200}\b"), "Slack token"),
    (SensitiveType.API_SECRET, re.compile(r"\b[sr]k_(?:live|test)_[A-Za-z0-9]{16,100}\b"), "Stripe secret key"),
    (SensitiveType.API_SECRET, re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"), "Google API key"),
    (SensitiveType.ACCESS_TOKEN, re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"), "JWT"),
    (SensitiveType.PRIVATE_KEY, re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP |ENCRYPTED )?PRIVATE KEY(?: BLOCK)?-----"),
     "private key block"),
)
_ASSIGN = re.compile(r"(?i)\b(password|passwd|pwd|secret|api[_-]?key|access[_-]?token|auth[_-]?token|client[_-]?secret)"
                     r"\b\s*[:=]\s*['\"]?([^\s'\",;<>]{6,128})")
_PLACEHOLDER = re.compile(r"(?i)^(?:x{3,}|\*{3,}|<.*>|\$\{.*\}|\{\{.*\}\}|changeme|example|your[_-]?.*|password|secret|"
                          r"test|dummy|placeholder|none|null|redacted.*|\.{3,}|n/a)$")


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s)


def scan_text(text: str, *, include_ip: bool = True) -> list[Hit]:
    """Return non-overlapping hits for one text unit, secrets first (highest priority)."""
    if not text:
        return []
    if len(text) > MAX_UNIT_CHARS:
        text = text[:MAX_UNIT_CHARS]
    hits: list[Hit] = []
    taken: list[tuple[int, int]] = []

    def free(a: int, b: int) -> bool:
        return all(b <= s or a >= e for s, e in taken)

    def add(h: Hit) -> None:
        if free(h.start, h.end):
            hits.append(h)
            taken.append((h.start, h.end))

    for stype, rx, label in _SECRET_PATTERNS:
        for m in rx.finditer(text):
            add(Hit(stype, m.start(), m.end(), True, label))
    for m in _ASSIGN.finditer(text):
        value = m.group(2)
        if _PLACEHOLDER.match(value):
            continue
        name = m.group(1).lower()
        stype = SensitiveType.PASSWORD_ASSIGNMENT if name in ("password", "passwd", "pwd") else SensitiveType.API_SECRET
        add(Hit(stype, m.start(2), m.end(2), False, f"{name} assignment"))
    for m in _IBAN.finditer(text):
        if iban_ok(m.group(0)):
            add(Hit(SensitiveType.IBAN, m.start(), m.end(), True, "mod-97 valid"))
    for m in _CARD.finditer(text):
        d = _digits(m.group(0))
        if 13 <= len(d) <= 19 and d[0] in "23456" and luhn_ok(d):
            add(Hit(SensitiveType.CREDIT_CARD, m.start(), m.end(), True, "Luhn valid"))
    for m in _SSN.finditer(text):
        if _ssn_ok(m.group(0)):
            add(Hit(SensitiveType.NATIONAL_ID, m.start(), m.end(), False, "US SSN format"))
    for m in _NATID_CTX.finditer(text):
        d = m.group(1)
        add(Hit(SensitiveType.NATIONAL_ID, m.start(1), m.end(1), bsn_ok(d), "labelled national id"))
    for m in _EMAIL.finditer(text):
        add(Hit(SensitiveType.EMAIL, m.start(), m.end(), True, "address syntax"))
    for rx in (_PHONE_INTL, _PHONE_NAT):
        for m in rx.finditer(text):
            d = _digits(m.group(0))
            if 8 <= len(d) <= 15:
                add(Hit(SensitiveType.PHONE, m.start(), m.end(), False, "phone-like number"))
    for m in _DOB.finditer(text):
        add(Hit(SensitiveType.DATE_OF_BIRTH, m.start(1), m.end(1), False, "labelled date of birth"))
    if include_ip:
        for m in _IPV4.finditer(text):
            try:
                ip = ipaddress.ip_address(m.group(0))
            except ValueError:
                continue
            if ip.is_unspecified or ip.is_multicast:
                continue
            ctx = text[max(0, m.start() - 12):m.start()].lower()
            if re.search(r"(?:version|ver\.?|rev(?:ision)?|release|v)\s*$", ctx):
                continue
            add(Hit(SensitiveType.IP_ADDRESS, m.start(), m.end(), True, "valid IPv4"))
    hits.sort(key=lambda h: h.start)
    return hits
