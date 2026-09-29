"""Who is here (the shared wall): each open browser says "still here" every few seconds with an id it made up itself;
anyone silent for `ttl` seconds is gone. The gate has one key and no usernames, so this counts browsers, not people
by name. Nothing is stored but the id and the time of its last word."""
from __future__ import annotations
import time


class Presence:
    def __init__(self, ttl: float = 30, cap: int = 500, now=time.time):
        self.ttl, self.cap, self._now = ttl, cap, now
        self._seen: dict[str, float] = {}

    def _fresh(self) -> None:
        cutoff = self._now() - self.ttl
        for k in [k for k, t in self._seen.items() if t < cutoff]:
            del self._seen[k]

    def beat(self, who: str) -> int:
        """Still here. Returns how many are here now. A blank id is a reader without a seat."""
        who = (who or "").strip()[:64]
        self._fresh()
        if who and (who in self._seen or len(self._seen) < self.cap):
            self._seen[who] = self._now()
        return len(self._seen)

    def count(self, but: str = "") -> int:
        """How many are here; `but` leaves one id out ("the others")."""
        self._fresh()
        return len(self._seen) - (1 if (but or "").strip()[:64] in self._seen else 0)


def busy_line(others: int, queue: dict | None) -> str:
    """What a model switch would interrupt, in words; '' when the wall is free."""
    parts = []
    if others > 0:
        parts.append(f"{others} other " + ("person is here" if others == 1 else "people are here"))
    n = (queue or {}).get("running", 0) + (queue or {}).get("waiting", 0)
    if n > 0:
        parts.append(f"{n} " + ("answer is in progress" if n == 1 else "answers are in progress"))
    return " · ".join(parts)
