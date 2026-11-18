"""Sign-in log (NFCU lab): who signed in, from which address, and whether it worked. Off unless CTXDEMO_AUTHLOG names a
directory. One file per UTC day, `signins-YYYY-MM-DD.log`, same shape as the host's command log:

    2026-11-18T16:20:01Z  lab3   signin  ok       ip=203.0.113.9
    2026-11-18T16:20:09Z  -      signin  refused  ip=203.0.113.9  name=lab33
    2026-11-18T16:21:00Z  lab3   seen             ip=198.51.100.4

`seen` is written the first time each day a signed-in user (or the shared key, written as `(key)`) turns up from an address,
so a cookie used from somewhere new shows. Never a password, never a key, never a cookie: a refused try on the key box
logs no text at all, because a mistyped key or password is still a secret. The host prunes old files (lab-audit-snap).
"""
import logging
import os
import re
import threading
import time
from pathlib import Path

log = logging.getLogger("ctxdemo")
_UNSAFE = re.compile(r"[^A-Za-z0-9._:()\-]")


def clean(s: str, n: int = 64) -> str:
    return _UNSAFE.sub("?", str(s or ""))[:n] or "-"


class AuthLog:
    def __init__(self, directory: str | Path | None = "", now=time.time):
        self.dir = Path(directory) if directory else None
        self.enabled = self.dir is not None
        self._now = now
        self._lock = threading.Lock()
        self._day, self._seen = "", set()

    def _write(self, user: str, event: str, result: str, ip: str, extra: str = "") -> None:
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self._now()))
        line = f"{ts}  {clean(user, 32):<6} {event:<7} {result:<8} ip={clean(ip)}{extra}\n"
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            fd = os.open(self.dir / f"signins-{ts[:10]}.log", os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
            try:
                os.write(fd, line.encode())
            finally:
                os.close(fd)
        except OSError as e:                       # a full disk must not lock people out of the wall
            log.warning("authlog: %s", e)

    def signin(self, ip: str, user: str | None, ok: bool, tried: str = "") -> None:
        """One try at the gate. `user` = who got in (`(key)` for the shared key); `tried` = the name typed in the name box
        on a refused sign-in (never anything from the key box)."""
        if not self.enabled:
            return
        with self._lock:
            if ok:
                self._write(user or "(key)", "signin", "ok", ip)
                self._mark(user or "(key)", ip)
            else:
                self._write("-", "signin", "refused", ip, f"  name={clean(tried, 32)}" if tried else "")

    def _mark(self, user: str, ip: str) -> bool:
        day = time.strftime("%Y-%m-%d", time.gmtime(self._now()))
        if day != self._day:
            self._day, self._seen = day, set()
        if (user, ip) in self._seen or len(self._seen) > 20000:    # a cap, so a flood of addresses cannot grow this forever
            return False
        self._seen.add((user, ip))
        return True

    def seen(self, user: str | None, ip: str) -> None:
        """A request that passed the gate: logged once per user and address per day."""
        if not self.enabled:
            return
        with self._lock:
            if self._mark(user or "(key)", ip):
                self._write(user or "(key)", "seen", "", ip)
