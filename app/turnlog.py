"""Turn log: one JSON line per question/answer, to a file, only when CTXDEMO_TURNLOG is set.

Off by default on purpose — what people type at the wall is theirs. Nothing here goes to the
container log; the file lives on the box (compose volume) and is read over ssh.
"""
import json
import logging
import threading
import time
from pathlib import Path

log = logging.getLogger("ctxdemo")


def hesitations(tokens: list[dict], n: int = 3) -> dict:
    """The act 6 numbers for a turn: how many pieces, how many the model was unsure of, and the worst few."""
    real = [t for t in tokens if t.get("t", "").strip()]
    worst = sorted((t for t in real if t.get("p", 1) < 0.9), key=lambda t: t["p"])[:n]
    return {"pieces": len(tokens),
            "unsure": sum(1 for t in real if t.get("p", 1) < 0.9),
            "flips": sum(1 for t in real if t.get("p", 1) < 0.5),
            "worst": [{"t": t["t"], "p": t["p"], "vs": [a["t"] for a in t.get("alts", [])[:2] if a["t"] != t["t"]][:1]}
                      for t in worst]}


class TurnLog:
    """`keep` seconds > 0 = a retention window: every write prunes older lines, and a daemon thread prunes every 30 s so the
    file empties on its own after the last question (NFCU: 5 minutes, so Simon can say exactly what the box holds)."""
    TS = "%Y-%m-%d %H:%M:%S"

    def __init__(self, path: str | Path | None, keep: int = 0):
        self.path = Path(path) if path else None
        self.enabled = self.path is not None
        self.keep = max(0, int(keep or 0))
        self._lock = threading.Lock()
        self._pruner = None

    def prune(self, now: float | None = None) -> int:
        """Drop lines older than `keep` seconds (by their own ts, same clock as write). Returns how many were dropped."""
        if not self.enabled or not self.keep or not self.path.exists():
            return 0
        cutoff = (now if now is not None else time.time()) - self.keep
        with self._lock:
            lines = self.path.read_text(encoding="utf-8").splitlines()
            keep = []
            for ln in lines:
                try:
                    ts = time.mktime(time.strptime(json.loads(ln)["ts"], self.TS))
                except (ValueError, KeyError, TypeError, OverflowError):
                    continue                                   # unparseable = not worth keeping
                if ts >= cutoff:
                    keep.append(ln)
            if len(keep) != len(lines):
                self.path.write_text("".join(k + "\n" for k in keep), encoding="utf-8")   # in place: same inode, the appender is per-write
        return len(lines) - len(keep)

    def start_pruner(self, every: int = 30) -> None:
        if not self.enabled or not self.keep or self._pruner:
            return
        def loop():
            while True:
                time.sleep(every)
                try:
                    self.prune()
                except OSError as e:
                    log.warning("turnlog prune: %s", e)
        self._pruner = threading.Thread(target=loop, name="turnlog-prune", daemon=True); self._pruner.start()

    def write(self, session_id: str, tab: str, user: str, answer: str | None, seconds: float,
              tokens: list[dict] | None = None, source: str = "typed", persona: str | None = None,
              full: dict | None = None, name: str | None = None) -> None:
        """`full` = everything else about the turn (every piece with its guesses, the chunks, tool calls,
        the system prompt, the counts) — Simon wants to study it later, so keep it all; ~300 KB for a 3k-piece answer."""
        if not self.enabled:
            return
        rec = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "session": session_id, "tab": tab, "source": source,
               "user": user, "answer": answer, "seconds": round(seconds, 2)}
        if tokens:
            rec["guesses"] = hesitations(tokens)
        if persona is not None:
            rec["persona"] = persona
        if name:
            rec["name"] = name
        if full:
            rec.update(full)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self._lock, self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            self.prune()
        except OSError as e:                      # a full disk must never break a turn
            log.warning("turnlog: %s", e)
