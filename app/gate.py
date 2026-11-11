"""The gate (NFCU Linode): one key, one box, no usernames. Caddy asks `GET /api/gate/check` before every request
(forward_auth); the gate page posts the key to `POST /api/gate` and gets a cookie. The key lives in a one-line file
on the host (cfg.gate_file), read on every check, so changing it is editing that file: no restart, and every old
cookie stops working because the cookie is an HMAC of the key. No file / empty file = the gate is open (Gonzaga).

A lab login (`name:password`, app/labauth.py) is also a key. Its cookie is `lab.<name>.<HMAC of the gate key, the name and
that user's stored hash>`: checking it is a file read, never a bcrypt, and it stops working when the user is removed, when
their password changes, or when the gate key changes. That cookie is the lab's one sign-in: `who()` names its user for the
typed box, the model switch and Caddy's /shell/* check. The shared key's cookie is nobody in particular and opens only the wall."""
from __future__ import annotations
import hashlib, hmac, re, time
from collections import defaultdict, deque
from pathlib import Path

COOKIE = "gate"
MAX_AGE = 30 * 24 * 3600          # a visitor types the key once a month at most
TRIES, WINDOW = 10, 60            # wrong guesses per address per minute
LAB = "lab."                      # a lab user's cookie starts with this
LAB_NAME = re.compile(r"[a-z][a-z0-9]{1,15}")   # nfcu-shell's valid_name: nothing in it can confuse the cookie's dots


def norm(key: str) -> str:
    return (key or "").strip().upper()


class Gate:
    def __init__(self, path: str = "", now=time.time, lab=None):
        self.path = Path(path) if path else None
        self.lab = lab                                # LabAuth or None: lab logins that may also open the gate
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

    def lab_token(self, name: str, key: str) -> str | None:
        """The cookie for lab user `name`, or None when there is no such user (or no lab file)."""
        h = self.lab.hash_of(name) if self.lab and LAB_NAME.fullmatch(name or "") else None
        if not h:
            return None
        return LAB + name + "." + hmac.new(key.encode(), f"ctxdemo-gate-lab-v1|{name}|{h}".encode(), hashlib.sha256).hexdigest()

    def who(self, cookie: str | None) -> str | None:
        """The lab user a cookie belongs to, or None (no gate, no cookie, the shared key's cookie, a forged or ended one).
        A file read and an HMAC, never a bcrypt: Caddy asks this on every /shell/* request."""
        k = self.key()
        if not k or not cookie or not cookie.startswith(LAB):
            return None
        name = cookie[len(LAB):].rpartition(".")[0]
        t = self.lab_token(name, k)
        return name if t and hmac.compare_digest(cookie.encode("utf-8", "replace"), t.encode()) else None

    def allows(self, cookie: str | None) -> bool:
        k = self.key()
        if not k:
            return True
        if not cookie:
            return False
        c = cookie.encode("utf-8", "replace")         # bytes: compare_digest refuses non-ASCII strings
        return hmac.compare_digest(c, self.token(k).encode()) or self.who(cookie) is not None

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
        if k and self.lab and ":" in (key or ""):     # a lab login: exact case, one bcrypt (and only when that name exists)
            name = self.lab.verify(key.strip())
            value = self.lab_token(name, k) if name else None
            if value:
                self._misses.pop(who, None)
                return value
        self._misses[who].append(self._now())
        return None

    def try_login(self, name: str, password: str, who: str) -> str | None:
        """The sign-in form: a lab user's name and password as two fields. The cookie value, or None (counted against `who`)."""
        k, name = self.key(), (name or "").strip()
        if k and self.lab and password and LAB_NAME.fullmatch(name) and self.lab.verify(name + ":" + password) == name:
            value = self.lab_token(name, k)
            if value:
                self._misses.pop(who, None)
                return value
        self._misses[who].append(self._now())
        return None
