"""Near-duplicate detection by shingle overlap.

Each unit becomes a set of word 3-grams. Candidate pairs come from bottom-k sketches (the 16 smallest shingle hashes)
indexed in an inverted map; every candidate is then verified with the exact Jaccard similarity of the full shingle
sets, so the sketch only narrows the search and never decides. Deterministic: same input, same output. The result is a
similarity observation, not a verdict that content is redundant.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter, defaultdict

__all__ = ["shingles", "jaccard", "near_duplicates", "MAX_UNITS"]

MAX_UNITS = 20_000
_TOKEN = re.compile(r"\w+", re.UNICODE)
_SKETCH = 16
_MIN_SHARED = 3
_BUCKET_CAP = 64


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


def shingles(tokens: list[str]) -> frozenset[int]:
    n = len(tokens)
    grams = [" ".join(tokens[i:i + 3]) for i in range(max(n - 2, 1))] if n >= 3 else [" ".join(tokens)]
    return frozenset(int.from_bytes(hashlib.blake2b(g.encode("utf-8"), digest_size=8).digest(), "big") for g in grams)


def jaccard(a: frozenset[int], b: frozenset[int]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    return inter / (len(a) + len(b) - inter)


def near_duplicates(units: list[str], *, threshold: float = 0.8, min_tokens: int = 12) -> dict[int, tuple[int, float]]:
    """Map each unit index to ``(earlier index, similarity)`` for its closest earlier near-copy.

    Exact repeats (identical after normalising case and whitespace) are left to the exact-duplicate check. Units shorter
    than ``min_tokens`` words are not compared: the similarity of very short strings is not informative.
    """
    threshold = min(max(threshold, 0.5), 0.99)
    sets: list[frozenset[int] | None] = []
    norms: list[str] = []
    for u in units[:MAX_UNITS]:
        toks = _tokens(u)
        norms.append(" ".join(toks))
        sets.append(shingles(toks) if len(toks) >= min_tokens else None)
    index: dict[int, list[int]] = defaultdict(list)
    found: dict[int, tuple[int, float]] = {}
    seen: set[str] = set()
    for i, sh in enumerate(sets):
        if sh is None:
            continue
        if norms[i] in seen:
            continue                              # an exact repeat of an earlier unit: the exact check owns it
        seen.add(norms[i])
        sketch = sorted(sh)[:_SKETCH]
        shared: Counter[int] = Counter()
        for h in sketch:
            for j in index[h][-_BUCKET_CAP:]:
                shared[j] += 1
        need = min(_MIN_SHARED, len(sketch))
        best: tuple[float, int] | None = None
        for j, c in shared.items():
            if c < need:
                continue
            sim = jaccard(sh, sets[j])          # type: ignore[arg-type]
            if sim >= threshold and (best is None or (-sim, j) < (-best[0], best[1])):
                best = (sim, j)
        for h in sketch:
            index[h].append(i)
        if best is not None:
            found[i] = (best[1], round(best[0], 3))
    return found
