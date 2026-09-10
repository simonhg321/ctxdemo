"""Did the answer still contain the planted detail? Alias substring match, case/whitespace-insensitive."""
from __future__ import annotations
import re
from .script import Detail


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower())


def remembered(answer: str | None, detail: Detail) -> bool:
    if not answer:
        return False
    a = _norm(answer)
    return any(_norm(alias) in a for alias in detail.aliases)
