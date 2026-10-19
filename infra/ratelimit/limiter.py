"""Rate limiting: SLAI's token-bucket ``RateLimiter`` (memory by default; Redis when SLAI is configured for it)."""

from __future__ import annotations

from ...slai.runtime import functions

__all__ = ["SlaiRateLimiter"]


class SlaiRateLimiter:
    def __init__(self, per_minute: int) -> None:
        mod = functions("ratelimiter")
        per_minute = max(1, int(per_minute))
        self._rl = mod.RateLimiter(capacity=per_minute, refill_rate=per_minute / 60.0,
                                   store=mod.InMemoryStore(max_buckets=50_000))

    def check(self, key: str, tokens: int = 1) -> tuple[bool, float]:
        d = self._rl.evaluate(key[:200], tokens)
        return bool(d.allowed), float(d.retry_after or 0.0)
