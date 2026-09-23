"""Pure helpers for the layers sidecar. No torch here, so they test anywhere."""
from __future__ import annotations


def decided_at(tops: list[str]) -> int | None:
    """1-based layer from which the top-1 guess equals the final layer's and never changes again."""
    if not tops:
        return None
    final = tops[-1]
    n = len(tops)
    while n > 1 and tops[n - 2] == final:
        n -= 1
    return n


def heat(weights: list[float], drop_first: bool = True) -> list[float]:
    """Attention over prompt positions as 0..1 shades. The first token is an attention sink: drop it."""
    w = [float(x) for x in weights]
    if drop_first and w:
        w[0] = 0.0
    m = max(w) if w else 0.0
    return [x / m for x in w] if m > 0 else [0.0 for _ in w]


def cut_front(ids: list[int], max_tokens: int) -> list[int]:
    """Keep the end of a long prompt: the question and the answer so far are what matter."""
    return ids[-max_tokens:] if max_tokens > 0 and len(ids) > max_tokens else list(ids)
