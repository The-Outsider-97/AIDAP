"""A small, strict request-validation DSL.

Every API body is described by a ``dict[str, Field]`` and validated *before* any
service runs. Unknown keys are rejected (not ignored), strings are bounded, and all
problems are reported together, keyed by path, so a client can fix them in one pass.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable

from ..domain.utils.domain_errors import ValidationFailed
from ..domain.utils.domain_helpers import EMAIL_RE, parse_iso

__all__ = ["Field", "s", "i", "f", "b", "email", "url", "ts", "lst", "obj", "free", "enum", "validate"]

_MISSING = object()
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


@dataclass
class Field:
    kind: str
    required: bool = False
    default: Any = None
    min: float | None = None
    max: float | None = None
    choices: tuple[Any, ...] | None = None
    pattern: re.Pattern[str] | None = None
    item: "Field | None" = None
    schema: dict[str, "Field"] | None = None
    strip: bool = True
    nullable: bool = False
    allow_empty: bool = True
    doc: str = ""
    check: Callable[[Any], str | None] | None = None


def s(max: int = 500, *, min: int = 0, required: bool = False, default: Any = "", choices: Any = None,
      pattern: str | None = None, strip: bool = True, nullable: bool = False, doc: str = "") -> Field:
    return Field("string", required, default, min, max, tuple(choices) if choices else None,
                 re.compile(pattern) if pattern else None, strip=strip, nullable=nullable, doc=doc)


def enum(choices: Any, *, required: bool = False, default: Any = None, nullable: bool = False) -> Field:
    return Field("string", required, default if default is not None else ("" if not nullable else None), 0, 80,
                 tuple(choices), nullable=nullable)


def i(min: int | None = None, max: int | None = None, *, required: bool = False, default: Any = None,
      nullable: bool = False) -> Field:
    return Field("integer", required, default, min, max, nullable=nullable)


def f(min: float | None = None, max: float | None = None, *, required: bool = False, default: Any = None,
      nullable: bool = False) -> Field:
    return Field("number", required, default, min, max, nullable=nullable)


def b(*, default: bool = False, required: bool = False) -> Field:
    return Field("boolean", required, default)


def email(*, required: bool = True) -> Field:
    return Field("email", required, "", 3, 254)


def url(*, required: bool = False, max: int = 2000) -> Field:
    return Field("url", required, "", 0, max)


def ts(*, required: bool = False, nullable: bool = True) -> Field:
    return Field("timestamp", required, None, nullable=nullable)


def lst(item: Field, *, max: int = 100, min: int = 0, required: bool = False) -> Field:
    return Field("list", required, [], min, max, item=item)


def obj(schema: dict[str, Field], *, required: bool = False, default: Any = None) -> Field:
    return Field("object", required, default if default is not None else {}, schema=schema)


def free(*, max_keys: int = 200, max_depth: int = 6, required: bool = False) -> Field:
    """Free-form JSON object (e.g. policy documents) with depth and size bounds; semantics are checked by lint."""
    return Field("free", required, {}, max_keys, max_depth)


def _fail(errors: dict[str, str], path: str, msg: str) -> None:
    errors.setdefault(path or "$", msg)


def _depth_ok(value: Any, depth: int, max_keys: int, budget: list[int]) -> bool:
    budget[0] -= 1
    if budget[0] < 0 or depth < 0:
        return False
    if isinstance(value, dict):
        if len(value) > max_keys:
            return False
        return all(isinstance(k, str) and len(k) <= 200 and _depth_ok(v, depth - 1, max_keys, budget)
                   for k, v in value.items())
    if isinstance(value, list):
        return all(_depth_ok(v, depth - 1, max_keys, budget) for v in value)
    if isinstance(value, str):
        return len(value) <= 20_000
    return value is None or isinstance(value, (bool, int, float))


def _one(spec: Field, value: Any, path: str, errors: dict[str, str]) -> Any:
    if value is None:
        if spec.nullable:
            return None
        if spec.required:
            _fail(errors, path, "is required")
            return None
        return spec.default
    k = spec.kind
    if k in ("string", "email", "url"):
        if not isinstance(value, str):
            _fail(errors, path, "must be a string")
            return spec.default
        v = value.strip() if spec.strip else value
        if _CONTROL.search(v):
            _fail(errors, path, "contains control characters")
            return spec.default
        if spec.required and not v:
            _fail(errors, path, "is required")
            return spec.default
        if spec.max is not None and len(v) > spec.max:
            _fail(errors, path, f"must be at most {int(spec.max)} characters")
            return spec.default
        if spec.min and len(v) < spec.min and (v or spec.required):
            _fail(errors, path, f"must be at least {int(spec.min)} characters")
            return spec.default
        if k == "email":
            v = v.lower()
            if not EMAIL_RE.fullmatch(v):
                _fail(errors, path, "must be a valid email address")
        elif k == "url" and v:
            if not re.fullmatch(r"https?://[^\s]+", v):
                _fail(errors, path, "must be an http(s) URL")
        if v and spec.choices is not None and v not in spec.choices:
            _fail(errors, path, "must be one of: " + ", ".join(map(str, spec.choices)))
        if v and spec.pattern is not None and not spec.pattern.fullmatch(v):
            _fail(errors, path, "has an invalid format")
        return v
    if k in ("integer", "number"):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or (k == "integer" and isinstance(value, float)
                                                                                and not value.is_integer()):
            _fail(errors, path, "must be " + ("an integer" if k == "integer" else "a number"))
            return spec.default
        v2: Any = int(value) if k == "integer" else float(value)
        if v2 != v2 or v2 in (float("inf"), float("-inf")):
            _fail(errors, path, "must be finite")
            return spec.default
        if spec.min is not None and v2 < spec.min:
            _fail(errors, path, f"must be at least {spec.min:g}")
        if spec.max is not None and v2 > spec.max:
            _fail(errors, path, f"must be at most {spec.max:g}")
        return v2
    if k == "boolean":
        if not isinstance(value, bool):
            _fail(errors, path, "must be true or false")
            return spec.default
        return value
    if k == "timestamp":
        dt = parse_iso(value) if isinstance(value, str) else None
        if dt is None:
            _fail(errors, path, "must be an ISO-8601 timestamp")
        return value if dt is not None else None
    if k == "list":
        if not isinstance(value, list):
            _fail(errors, path, "must be a list")
            return []
        if spec.max is not None and len(value) > spec.max:
            _fail(errors, path, f"must contain at most {int(spec.max)} items")
            return []
        if spec.min and len(value) < spec.min:
            _fail(errors, path, f"must contain at least {int(spec.min)} items")
        return [_one(spec.item, v, f"{path}[{n}]", errors) for n, v in enumerate(value)] if spec.item else list(value)
    if k == "object":
        if not isinstance(value, dict):
            _fail(errors, path, "must be an object")
            return {}
        return _object(spec.schema or {}, value, path, errors)
    if k == "free":
        if not isinstance(value, dict):
            _fail(errors, path, "must be an object")
            return {}
        if not _depth_ok(value, int(spec.max or 6), int(spec.min or 200), [20_000]):
            _fail(errors, path, "is too large or too deeply nested")
            return {}
        return value
    _fail(errors, path, "unsupported field kind")
    return None


def _object(schema: dict[str, Field], data: dict[str, Any], path: str, errors: dict[str, str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in data:
        if key not in schema:
            _fail(errors, f"{path}.{key}" if path else key, "is not a recognised field")
    for key, spec in schema.items():
        p = f"{path}.{key}" if path else key
        raw = data.get(key, _MISSING)
        if raw is _MISSING:
            if spec.required:
                _fail(errors, p, "is required")
            out[key] = _copy_default(spec.default)
            continue
        out[key] = _one(spec, raw, p, errors)
        if spec.check and key not in {k.split(".")[-1] for k in errors}:
            msg = spec.check(out[key])
            if msg:
                _fail(errors, p, msg)
    return out


def _copy_default(d: Any) -> Any:
    return list(d) if isinstance(d, list) else dict(d) if isinstance(d, dict) else d


def validate(schema: dict[str, Field], data: Any) -> dict[str, Any]:
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ValidationFailed("request body must be a JSON object")
    errors: dict[str, str] = {}
    out = _object(schema, data, "", errors)
    if errors:
        raise ValidationFailed("request validation failed", details={"fields": errors})
    return out
