"""Background jobs: the side-by-side race (compact vs handoff) through the scripted conversation."""
from __future__ import annotations
import threading, uuid
from dataclasses import replace
from .session import Session
from .script import Script
from . import grader


class RaceJob:
    def __init__(self, vllm, cfg, script: Script):
        self.id = uuid.uuid4().hex[:8]
        self.vllm, self.cfg, self.script = vllm, cfg, script
        self.status = "running"
        self.error: str | None = None
        self.sides = {"left": {"mode": "endless", "label": "one long session, never resets", "turns": [], "events": [], "totals": {}},
                      "right": {"mode": "handoff", "label": f"handoff every {cfg.handoff_turn} messages", "turns": [], "events": [], "totals": {}}}
        self.verdict: str | None = None
        self._lock = threading.Lock()

    def _grade(self, turn, answer):
        return {d: grader.remembered(answer, self.script.details[d]) for d in turn.asks}

    def _run_side(self, key: str):
        side = self.sides[key]
        # both sides get the real, big window: the only difference is the handoff discipline
        cfg = replace(self.cfg, window_tokens=self.cfg.race_long_window)
        s = Session(side["mode"], self.vllm, cfg)
        for t in self.script.turns:
            if side["mode"] == "handoff" and t.n > 1 and (t.n - 1) % self.cfg.handoff_turn == 0:
                h = s.handoff()
                s = h.new_session
                with self._lock:
                    side["events"].append({"n": t.n - 1, "event": "handoff", "text": h.note})
            tr = s.turn(t.user)
            d = tr.to_dict()
            d["asks"] = t.asks
            d["remembered"] = self._grade(t, tr.answer)
            with self._lock:
                side["turns"].append(d)
                if tr.event:
                    side["events"].append({"n": tr.n, "event": tr.event, "text": tr.event_text})
                side["totals"] = self._totals(side)

    def _totals(self, side):
        turns = side["turns"]
        asked = sum(len(t["remembered"]) for t in turns)
        got = sum(sum(1 for v in t["remembered"].values() if v) for t in turns)
        sent = sum(t["sent_tokens"] for t in turns if t["answer"] is not None)
        new = sum(t["new_tokens"] for t in turns)
        # handoff/summary calls are charged inside the session totals; take the max seen
        last = turns[-1] if turns else {"total_sent": 0, "total_new": 0}
        sent = max(sent, last["total_sent"]); new = max(new, last["total_new"])
        return {"sent": sent, "new": new, "typed": sum(t["typed_words"] for t in turns),
                "seconds": round(sum(t["seconds"] for t in turns), 1),
                "remembered": got, "asked": asked,
                "cost_usd": {k: round((sent * p["in"] + new * p["out"]) / 1e6, 4) for k, p in self.cfg.prices.items()},
                "failed_turns": sum(1 for t in turns if t["answer"] is None)}

    def run(self, threads: bool = True):
        def go():
            try:
                ts = [threading.Thread(target=self._run_side, args=(k,), daemon=True) for k in self.sides]
                for t in ts: t.start()
                for t in ts: t.join()
                self.verdict = self._verdict()
                self.status = "done"
            except Exception as e:  # surfaced to the UI
                self.error, self.status = f"{type(e).__name__}: {e}", "error"
        if threads:
            threading.Thread(target=go, daemon=True).start()
        else:
            go()
        return self

    def _verdict(self) -> str:
        L, R = self.sides["left"]["totals"], self.sides["right"]["totals"]
        ratio = (L["sent"] / R["sent"]) if R.get("sent") else 0
        n = len(self.script.turns)
        return (f"Same {n}-message conversation. Handoff every {self.cfg.handoff_turn}: {R['sent']:,} tokens sent, "
                f"{R['remembered']}/{R['asked']} details remembered. One long session: {L['sent']:,} tokens sent "
                f"({ratio:.1f}× more), {L['remembered']}/{L['asked']} remembered.")

    def state(self) -> dict:
        with self._lock:
            return {"id": self.id, "status": self.status, "error": self.error, "sides": self.sides, "verdict": self.verdict,
                    "window_tokens": self.cfg.window_tokens, "script_turns": len(self.script.turns)}
