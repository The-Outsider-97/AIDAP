"""A tiny generic base for plain dataclass records (dict round-tripping)."""

from __future__ import annotations

import dataclasses
import enum
import typing
from datetime import datetime
from typing import Any

from .domain_helpers import parse_iso, to_jsonable

__all__ = ["Record"]


def _unwrap(tp: Any) -> tuple[Any, bool]:
    """Return (inner type, is_list) with Optional/``X | None`` removed."""
    origin = typing.get_origin(tp)
    if origin is typing.Union or (origin is not None and str(origin) == "<class 'types.UnionType'>"):
        args = [a for a in typing.get_args(tp) if a is not type(None)]
        if len(args) == 1:
            return _unwrap(args[0])
        return tp, False
    if origin in (list, typing.List):
        args = typing.get_args(tp)
        return (args[0] if args else Any), True
    return tp, False


def _convert(tp: Any, value: Any) -> Any:
    if value is None:
        return None
    inner, is_list = _unwrap(tp)
    if is_list:
        return [_convert(inner, v) for v in (value or [])]
    if inner is datetime:
        return parse_iso(value) if isinstance(value, str) else value
    if isinstance(inner, type):
        if issubclass(inner, enum.Enum):
            return inner(value) if not isinstance(value, inner) else value
        if dataclasses.is_dataclass(inner) and isinstance(value, dict) and hasattr(inner, "from_dict"):
            return inner.from_dict(value)
    return value


class Record:
    """Mixin: ``to_dict`` / ``from_dict`` for dataclasses."""

    def to_dict(self) -> dict[str, Any]:
        return {f.name: to_jsonable(getattr(self, f.name)) for f in dataclasses.fields(self)}  # type: ignore[arg-type]

    @classmethod
    def from_dict(cls, data: dict[str, Any]):
        hints = typing.get_type_hints(cls)
        kwargs = {}
        for f in dataclasses.fields(cls):  # type: ignore[arg-type]
            if f.name in data:
                kwargs[f.name] = _convert(hints.get(f.name, Any), data[f.name])
        return cls(**kwargs)
