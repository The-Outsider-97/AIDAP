"""Bounded loading of input bytes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import BinaryIO

__all__ = ["Limits", "InputTooLarge", "read_bounded"]


@dataclass(frozen=True)
class Limits:
    max_bytes: int = 10 * 1024 * 1024
    max_records: int = 200_000
    max_chars: int = 20_000_000
    parse_timeout_s: float = 20.0
    parse_memory_mb: int = 1024


class InputTooLarge(Exception):
    def __init__(self, limit: int) -> None:
        super().__init__(f"input exceeds the {limit} byte limit")
        self.limit = limit


def read_bounded(stream: BinaryIO, max_bytes: int, chunk: int = 1 << 20) -> bytes:
    """Read at most ``max_bytes``; fail (do not truncate silently) if more is available."""
    out = bytearray()
    while True:
        part = stream.read(min(chunk, max_bytes + 1 - len(out)))
        if not part:
            break
        out += part
        if len(out) > max_bytes:
            raise InputTooLarge(max_bytes)
    return bytes(out)
