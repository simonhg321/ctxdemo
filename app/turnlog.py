"""Turn log: one JSON line per question/answer, to a file, only when CTXDEMO_TURNLOG is set.

Off by default on purpose — what people type at the wall is theirs. Nothing here goes to the
container log; the file lives on the box (compose volume) and is read over ssh.
"""
import json
import logging
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
    def __init__(self, path: str | Path | None):
        self.path = Path(path) if path else None
        self.enabled = self.path is not None

    def write(self, session_id: str, tab: str, user: str, answer: str | None, seconds: float,
              tokens: list[dict] | None = None, source: str = "typed", persona: str | None = None) -> None:
        if not self.enabled:
            return
        rec = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "session": session_id, "tab": tab, "source": source,
               "user": user, "answer": answer, "seconds": round(seconds, 2)}
        if tokens:
            rec["guesses"] = hesitations(tokens)
        if persona is not None:
            rec["persona"] = persona
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except OSError as e:                      # a full disk must never break a turn
            log.warning("turnlog: %s", e)
