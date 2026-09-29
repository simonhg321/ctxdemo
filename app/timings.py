"""How long each prepared question takes on each model: the traffic lights on the ask buttons. The wall times a
prepared question whenever someone runs it on the plain wall (default persona, greedy), keeps the last five per
model, and reports the median. Optional JSON file so the lights survive a restart; no file = memory only."""
from __future__ import annotations
import json, logging, statistics, threading
from pathlib import Path

log = logging.getLogger("ctxdemo")
KEEP = 5                           # samples per question
GREEN_UNDER, RED_OVER = 3.0, 10.0  # seconds: green < 3 <= yellow <= 10 < red


def light(seconds: float | None) -> str | None:
    if seconds is None:
        return None
    return "green" if seconds < GREEN_UNDER else "red" if seconds > RED_OVER else "yellow"


class Timings:
    def __init__(self, path: str = "", cap: int = 40):
        self.path = Path(path) if path else None
        self.cap = cap                                  # questions per model
        self._lock = threading.Lock()
        self._t: dict[str, dict[str, list[float]]] = self._load()

    def _load(self) -> dict:
        try:
            raw = json.loads(self.path.read_text()) if self.path and self.path.exists() else {}
            return {str(m): {str(q): [float(s) for s in v][-KEEP:] for q, v in qs.items()} for m, qs in raw.items()}
        except (OSError, ValueError, TypeError, AttributeError):
            return {}

    def record(self, model: str, question: str, seconds: float | None) -> None:
        question = (question or "").strip()[:200]
        if not model or not question or seconds is None or seconds < 0:
            return
        with self._lock:
            qs = self._t.setdefault(model, {})
            if question not in qs and len(qs) >= self.cap:
                return
            qs[question] = (qs.get(question, []) + [round(float(seconds), 2)])[-KEEP:]
            if self.path:
                try:
                    self.path.write_text(json.dumps(self._t))
                except OSError as e:                    # the lights must never break a turn
                    log.warning("timings not saved: %s: %s", type(e).__name__, e)

    def for_model(self, model: str) -> dict[str, dict]:
        with self._lock:
            out = {}
            for q, v in self._t.get(model, {}).items():
                s = round(statistics.median(v), 1)
                out[q] = {"seconds": s, "light": light(s), "n": len(v)}
            return out
