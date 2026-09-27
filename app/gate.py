"""The gate (NFCU Linode): one key, one box, no usernames. Caddy asks `GET /api/gate/check` before every request
(forward_auth); the gate page posts the key to `POST /api/gate` and gets a cookie. The key lives in a one-line file
on the host (cfg.gate_file), read on every check, so changing it is editing that file: no restart, and every old
cookie stops working because the cookie is an HMAC of the key. No file / empty file = the gate is open (Gonzaga)."""
from __future__ import annotations
import hashlib, hmac, time
from collections import defaultdict, deque
from pathlib import Path

COOKIE = "gate"
MAX_AGE = 30 * 24 * 3600          # a visitor types the key once a month at most
TRIES, WINDOW = 10, 60            # wrong guesses per address per minute


def norm(key: str) -> str:
    return (key or "").strip().upper()


class Gate:
    def __init__(self, path: str = "", now=time.time):
        self.path = Path(path) if path else None
        self._now = now
        self._misses: dict[str, deque] = defaultdict(deque)

    def key(self) -> str:
        """The current key, or '' when the gate is open. Read each time: the file is the control."""
        if not self.path:
            return ""
        try:
            lines = [l for l in self.path.read_text().splitlines() if l.strip() and not l.lstrip().startswith("#")]
            return norm(lines[0]) if lines else ""
        except OSError:
            return ""

    @property
    def enabled(self) -> bool:
        return bool(self.key())

    def token(self, key: str | None = None) -> str:
        return hmac.new(norm(key if key is not None else self.key()).encode(), b"ctxdemo-gate-v1", hashlib.sha256).hexdigest()

    def allows(self, cookie: str | None) -> bool:
        k = self.key()
        return not k or (bool(cookie) and hmac.compare_digest(cookie, self.token(k)))

    def throttled(self, who: str) -> bool:
        q, t = self._misses[who], self._now()
        while q and q[0] < t - WINDOW:
            q.popleft()
        return len(q) >= TRIES

    def try_key(self, key: str, who: str) -> str | None:
        """The cookie value for a right key; None for a wrong one (counted against `who`)."""
        k = self.key()
        if k and hmac.compare_digest(norm(key).encode(), k.encode()):
            self._misses.pop(who, None)
            return self.token(k)
        self._misses[who].append(self._now())
        return None
