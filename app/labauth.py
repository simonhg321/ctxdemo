"""Lab logins (NFCU Linode): the lab's users live in Caddy's htpasswd file for /shell/* (one `name bcrypt-hash` line each,
written by nfcu-shell's add-shell-user / lab-user). A lab user may type `name:password` wherever the wall asks for the
switch password: it unlocks the typed-question box and may switch the model. The same login also opens the gate (app/gate.py). The file is re-read on every call (users come
and go; it is a few lines) and exactly one bcrypt comparison runs per call (cost 14 is about a second). Passwords are never logged."""
from __future__ import annotations
from pathlib import Path

import bcrypt


class LabAuth:
    def __init__(self, path: Path | str | None):
        self.path = Path(path) if path else None

    def hash_of(self, name: str) -> str | None:
        """That user's stored hash, or None (no file, unknown user, or a name listed twice: refuse rather than guess which
        line counts). No bcrypt here: the gate uses this to check a lab cookie on every request."""
        if not self.path or not name:
            return None
        try:
            lines = self.path.read_text().splitlines()
        except (OSError, UnicodeDecodeError):
            return None
        hits = [f[1] for f in (l.split() for l in lines) if len(f) == 2 and f[0] == name]
        return hits[0] if len(hits) == 1 else None

    def verify(self, credential: str) -> str | None:
        """`name:password` -> name when that user's line exists and the password matches; None otherwise (no colon,
        unknown user, a name listed twice, a bad hash, no file)."""
        name, colon, password = (credential or "").partition(":")
        if not colon or not name or not password:
            return None
        h = self.hash_of(name)
        if not h:
            return None
        try:
            ok = bcrypt.checkpw(password.encode(), h.encode())
        except ValueError:                            # not a bcrypt hash (or a password bcrypt refuses)
            return None
        return name if ok else None
