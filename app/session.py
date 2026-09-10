"""The backpack. One conversation, three behaviours: endless / compact / handoff.

Every turn reports what the user typed vs what the model actually received (real vLLM token counts)."""
from __future__ import annotations
import uuid
from dataclasses import dataclass, field, asdict
from typing import Literal
from .config import Config

Mode = Literal["endless", "compact", "handoff"]

SYSTEM = ("You are a helpful assistant helping plan a university lab open house. "
          "Answer briefly and concretely. Use the details the user has given you.")
SUMMARY_PROMPT = ("Summarize the conversation below so that an assistant can continue it. "
                  "Keep every concrete fact (dates, names, numbers, places, rules) in a compact list. "
                  "Plain text, no preamble.\n\nCONVERSATION:\n")
HANDOFF_PROMPT = ("Write a handoff note for a fresh assistant who will continue this conversation. "
                  "Include: the goal, every decision and concrete fact so far (dates, names, numbers, places, rules), "
                  "and the next step. Plain text, no preamble.\n\nCONVERSATION:\n")


@dataclass
class TurnResult:
    n: int
    user: str
    answer: str | None
    sent_tokens: int
    new_tokens: int
    typed_words: int
    seconds: float
    breakdown: dict[str, int]
    event: str | None
    event_text: str | None
    cost_usd: dict[str, float]
    total_sent: int
    total_new: int

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class HandoffResult:
    note: str
    note_tokens: int
    new_session: "Session"


class Session:
    def __init__(self, mode: Mode, vllm, cfg: Config, system_prompt: str = SYSTEM,
                 memory: tuple[str, str] | None = None, carried: tuple[int, int, int] = (0, 0, 0)):
        self.id = uuid.uuid4().hex[:12]
        self.mode: Mode = mode
        self.vllm = vllm
        self.cfg = cfg
        self.system = system_prompt
        # memory = (label, text) — a summary or handoff note that replaced the transcript
        self.memory: tuple[str, str] | None = memory
        self.transcript: list[dict] = []          # user/assistant messages since the last memory block
        self.turns: list[TurnResult] = []
        self.carried_n, self.carried_sent, self.carried_new = carried
        self.script_pos = 0
        self.events: list[dict] = []              # {"n", "event", "text"} for the UI

    # ---- what would be sent next
    @property
    def messages(self) -> list[dict]:
        msgs = [{"role": "system", "content": self.system}]
        if self.memory:
            label, text = self.memory
            msgs.append({"role": "user", "content": f"[{label}]\n{text}"})
            msgs.append({"role": "assistant", "content": "Got it, continuing from that."})
        return msgs + self.transcript

    @property
    def n(self) -> int:
        return self.carried_n + len(self.turns)

    def _transcript_text(self) -> str:
        parts = []
        if self.memory:
            parts.append(f"[{self.memory[0]}]\n{self.memory[1]}")
        for m in self.transcript:
            parts.append(f"{m['role'].upper()}: {m['content']}")
        return "\n\n".join(parts)

    def _breakdown(self, user_text: str) -> dict[str, int]:
        c = self.vllm.count
        return {"system": c(self.system),
                "memory": c(self.memory[1]) if self.memory else 0,
                "transcript": sum(c(m["content"]) for m in self.transcript),
                "message": c(user_text)}

    def _cost(self, sent: int, new: int) -> dict[str, float]:
        return {name: round((sent * p["in"] + new * p["out"]) / 1e6, 5) for name, p in self.cfg.prices.items()}

    # ---- compaction (compact mode only)
    def _compact(self) -> str:
        r = self.vllm.chat([{"role": "user", "content": SUMMARY_PROMPT + self._transcript_text()}],
                           self.cfg.summary_max_tokens)
        self.memory = ("Summary of our conversation so far", r.text)
        self.transcript = []
        return r.text

    # ---- one turn
    def turn(self, user_text: str) -> TurnResult:
        n = self.n + 1
        typed = len(user_text.split())
        event = event_text = None
        candidate = self.messages + [{"role": "user", "content": user_text}]
        would = self.vllm.count_messages(candidate)
        limit = self.cfg.window_tokens

        if self.mode == "compact" and would >= self.cfg.compact_at * limit and self.transcript:
            event, event_text = "compacted", self._compact()
            candidate = self.messages + [{"role": "user", "content": user_text}]
            would = self.vllm.count_messages(candidate)

        if would > limit:
            tr = TurnResult(n=n, user=user_text, answer=None, sent_tokens=would, new_tokens=0, typed_words=typed,
                            seconds=0.0, breakdown=self._breakdown(user_text), event="over_limit",
                            event_text=f"This message would be {would:,} tokens; the window holds {limit:,}.",
                            cost_usd=self._cost(0, 0), total_sent=self.total_sent, total_new=self.total_new)
            self.turns.append(tr)
            self.events.append({"n": n, "event": "over_limit", "text": tr.event_text})
            return tr

        breakdown = self._breakdown(user_text)
        r = self.vllm.chat(candidate, self.cfg.answer_max_tokens)
        self.transcript.append({"role": "user", "content": user_text})
        self.transcript.append({"role": "assistant", "content": r.text})
        tr = TurnResult(n=n, user=user_text, answer=r.text, sent_tokens=r.prompt_tokens, new_tokens=r.completion_tokens,
                        typed_words=typed, seconds=round(r.seconds, 2), breakdown=breakdown,
                        event=event, event_text=event_text, cost_usd=self._cost(r.prompt_tokens, r.completion_tokens),
                        total_sent=self.total_sent + r.prompt_tokens, total_new=self.total_new + r.completion_tokens)
        self.turns.append(tr)
        if event:
            self.events.append({"n": n, "event": event, "text": event_text})
        return tr

    @property
    def total_sent(self) -> int:
        return self.carried_sent + sum(t.sent_tokens for t in self.turns if t.answer is not None)

    @property
    def total_new(self) -> int:
        return self.carried_new + sum(t.new_tokens for t in self.turns)

    # ---- end this session on purpose, hand off to a fresh one
    def handoff(self) -> HandoffResult:
        r = self.vllm.chat([{"role": "user", "content": HANDOFF_PROMPT + self._transcript_text()}],
                           self.cfg.handoff_max_tokens)
        # the handoff call itself costs tokens; charge it to the old session's totals
        self.carried_sent += r.prompt_tokens
        self.carried_new += r.completion_tokens
        new = Session(self.mode, self.vllm, self.cfg, self.system,
                      memory=("Handoff note from my previous session", r.text),
                      carried=(self.n, self.total_sent, self.total_new))
        new.script_pos = self.script_pos
        new.events.append({"n": self.n, "event": "handoff", "text": r.text})
        return HandoffResult(note=r.text, note_tokens=self.vllm.count(r.text), new_session=new)

    def state(self) -> dict:
        return {"id": self.id, "mode": self.mode, "n": self.n, "turns": [t.to_dict() for t in self.turns],
                "events": self.events, "memory": {"label": self.memory[0], "text": self.memory[1]} if self.memory else None,
                "totals": {"sent": self.total_sent, "new": self.total_new,
                           "cost_usd": self._cost(self.total_sent, self.total_new)},
                "window_tokens": self.cfg.window_tokens, "next_would_send": self.vllm.count_messages(self.messages)}
