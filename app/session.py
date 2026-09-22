"""The backpack. One conversation, three behaviours: endless / compact / handoff.

Every turn reports what the user typed vs what the model actually received (real vLLM token counts)."""
from __future__ import annotations
import copy, logging, uuid
from dataclasses import dataclass, field, asdict
from typing import Literal
from .config import Config
from .vllm import text_of, trim_wire
from .tools import TOOLS
from .graph import Graph, EXTRACT_PROMPT, parse_extract

log = logging.getLogger("uvicorn.error")

MAX_TOOL_ROUNDS = 3

Mode = Literal["endless", "compact", "handoff"]

SYSTEM = ("You are a helpful assistant helping plan a university lab open house. "
          "Answer briefly and concretely. Use the details the user has given you.")
SYSTEM_BOARD = ("You are a friendly assistant in a university lab. People write questions on a whiteboard and hold it up "
                "to a camera; you answer for a wall display. Keep answers short (2-4 sentences), plain, and concrete. "
                "Use web_search for anything current (weather, news, scores) and say where the answer came from.")
SYSTEM_MAP = ("You are a friendly guide in a university lab. People talk to you out loud and a wall display draws a map of "
              "what you are holding in memory. Explain things in 4-6 plain, concrete sentences, like a good lab tour. "
              "Use web_search for anything current (weather, news, scores) and say where the answer came from. "
              "End every answer by naming one related thing they could ask about next, in one short sentence.")
SUMMARY_PROMPT = ("Summarize the conversation below so that an assistant can continue it. "
                  "List EVERY concrete fact exactly as stated (dates, names, numbers, codes, places, rules) — do not paraphrase or drop any. "
                  "Plain text, no preamble.\n\nCONVERSATION:\n")
HANDOFF_PROMPT = ("Write a handoff note for a fresh assistant who will continue this conversation. "
                  "FIRST list EVERY concrete fact exactly as stated (dates, names, numbers, codes, places, rules, deadlines) — do not paraphrase or drop any. "
                  "THEN the goal, what has been produced so far (one line each), and the next step. Plain text, no preamble.\n\nCONVERSATION:\n")


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
    tool_uses: list[dict] = field(default_factory=list)   # {name, args, result} per tool call this turn
    graph_delta: dict = field(default_factory=lambda: {"added": [], "bumped": [], "edges": []})   # the map
    tokens: list[dict] = field(default_factory=list)        # act 6: {t, p, alts} per piece of the answer (peek sessions only)
    cut: bool = False                                       # the answer hit answer_max_tokens: the server stopped it, the model did not
    user_chunks: list[str] = field(default_factory=list)    # act 6: the user's sentence split into the model's pieces
    wire: dict | None = None                                # act 6: the exact request/response of the final model call (peek sessions only, trimmed)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class HandoffResult:
    note: str
    note_tokens: int
    new_session: "Session"
    graph_survive: dict = field(default_factory=dict)     # what the map kept / absorbed on the way over


class Session:
    def __init__(self, mode: Mode, vllm, cfg: Config, system_prompt: str = SYSTEM,
                 memory: tuple[str, str] | None = None, carried: tuple[int, int, int] = (0, 0, 0),
                 tools=None, peek: bool = False, chunker=None, persona: str | None = None):
        self.id = uuid.uuid4().hex[:12]
        self.tools = tools                        # a Tools instance, or None = no web access
        self.peek = peek                          # act 6: ask for the guesses behind the answer
        self.chunker = chunker                    # act 6: splits the user's sentence into pieces, or None
        self.persona = persona                    # act 6: persona file id, "custom" (free-text system), or None
        self.mode: Mode = mode
        self.vllm = vllm
        self.cfg = cfg
        self.system = system_prompt
        # memory = (label, text) — a summary or handoff note that replaced the transcript
        self.memory: tuple[str, str] | None = memory
        self.transcript: list[dict] = []          # user/assistant messages since the last memory block
        self.turns: list[TurnResult] = []
        self.carried_n, self.carried_sent, self.carried_new = carried
        self.carried_typed = 0
        self.script_pos = 0
        self.events: list[dict] = []              # {"n", "event", "text"} for the UI
        self.last_board: str = ""                 # last question read off the whiteboard (dedupe)
        self.listening_until: float = 0.0         # mic: open window after the wake phrase (epoch seconds)
        self.graph = Graph()                      # the map: concepts this session is holding
        self.last_survive: dict | None = None     # set by _compact, picked up by turn() / the compact route

    # ---- what would be sent next
    @property
    def messages(self) -> list[dict]:
        msgs = [{"role": "system", "content": self.system}] if self.system else []   # a persona may carry no prompt at all
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
            body = text_of(m.get("content"))
            if m.get("tool_calls"):
                body = (body + " " if body else "") + "[called " + ", ".join(tc["function"]["name"] for tc in m["tool_calls"]) + "]"
            parts.append(f"{m['role'].upper()}: {body}")
        return "\n\n".join(parts)

    def _breakdown(self, user_text: str) -> dict[str, int]:
        c = self.vllm.count
        return {"system": c(self.system),
                "memory": c(self.memory[1]) if self.memory else 0,
                "transcript": sum(c(text_of(m.get("content"))) for m in self.transcript),
                "message": c(user_text)}

    def _cost(self, sent: int, new: int) -> dict[str, float]:
        return {name: round((sent * p["in"] + new * p["out"]) / 1e6, 5) for name, p in self.cfg.prices.items()}

    def _peek_kw(self) -> dict:
        return {"peek": True} if self.peek else {}      # plain sessions call chat() exactly as before

    # ---- compaction (compact mode only)
    def _compact(self) -> str:
        r = self.vllm.chat([{"role": "user", "content": SUMMARY_PROMPT + self._transcript_text()}],
                           self.cfg.summary_max_tokens)
        self.memory = ("Summary of our conversation so far", r.text)
        self.last_survive = self.graph.survive(r.text)
        self.transcript = []
        return r.text

    # ---- one turn
    def _extract(self, n: int, user_text: str, answer: str) -> tuple[dict, int, int, float]:
        """One small model call -> (delta, prompt_tokens, completion_tokens, seconds). Never raises."""
        empty = {"added": [], "bumped": [], "edges": []}
        if not self.cfg.extract or not answer:
            return empty, 0, 0, 0.0
        try:
            r = self.vllm.chat([{"role": "user", "content": f"{EXTRACT_PROMPT}USER: {user_text}\n\nASSISTANT: {answer}"}],
                               self.cfg.extract_max_tokens)
            concepts, links = parse_extract(r.text)
            return self.graph.apply(n, concepts, links), r.prompt_tokens, r.completion_tokens, r.seconds
        except Exception as e:      # the map must never break a turn
            log.warning("extract failed: %s: %s", type(e).__name__, e)
            return empty, 0, 0, 0.0

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
        tools = TOOLS if self.tools else None
        self.transcript.append({"role": "user", "content": user_text})
        sent = new = 0
        secs = 0.0
        uses: list[dict] = []
        r = self.vllm.chat(self.messages, self.cfg.answer_max_tokens, tools=tools, **self._peek_kw())
        rounds = 0
        while r.tool_calls and self.tools and rounds < MAX_TOOL_ROUNDS:
            rounds += 1
            sent += r.prompt_tokens; new += r.completion_tokens; secs += r.seconds
            self.transcript.append({"role": "assistant", "content": r.text or None, "tool_calls": r.tool_calls})
            for tc in r.tool_calls:
                fn = tc.get("function", {})
                result = self.tools.run(fn.get("name", ""), fn.get("arguments", "{}"))
                uses.append({"name": fn.get("name"), "args": fn.get("arguments"), "result": result})
                self.transcript.append({"role": "tool", "tool_call_id": tc.get("id", f"call_{rounds}"), "content": result})
            r = self.vllm.chat(self.messages, self.cfg.answer_max_tokens, tools=tools, **self._peek_kw())
        sent += r.prompt_tokens; new += r.completion_tokens; secs += r.seconds
        self.transcript.append({"role": "assistant", "content": r.text})
        delta, xp, xc, xs = self._extract(n, user_text, r.text)
        sent += xp; new += xc; secs += xs
        breakdown["extract"] = xp
        if event == "compacted" and self.last_survive is not None:
            delta["survive"] = self.last_survive; self.last_survive = None
        tr = TurnResult(n=n, user=user_text, answer=r.text, sent_tokens=sent, new_tokens=new,
                        typed_words=typed, seconds=round(secs, 2), breakdown=breakdown,
                        event=event, event_text=event_text, cost_usd=self._cost(sent, new),
                        total_sent=self.total_sent + sent, total_new=self.total_new + new, tool_uses=uses,
                        graph_delta=delta,
                        tokens=r.tokens if self.peek else [], cut=r.cut,
                        user_chunks=self.chunker.split(user_text) if (self.peek and self.chunker) else [],
                        wire=trim_wire(r.wire) if self.peek else None)
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

    @property
    def total_typed(self) -> int:
        return self.carried_typed + sum(t.typed_words for t in self.turns)

    # ---- end this session on purpose, hand off to a fresh one
    def handoff(self) -> HandoffResult:
        r = self.vllm.chat([{"role": "user", "content": HANDOFF_PROMPT + self._transcript_text()}],
                           self.cfg.handoff_max_tokens)
        # the handoff call itself costs tokens; charge it to the old session's totals
        self.carried_sent += r.prompt_tokens
        self.carried_new += r.completion_tokens
        new = Session(self.mode, self.vllm, self.cfg, self.system,
                      memory=("Handoff note from my previous session", r.text),
                      carried=(self.n, self.total_sent, self.total_new),
                      tools=self.tools, peek=self.peek, chunker=self.chunker, persona=self.persona)
        new.script_pos = self.script_pos
        new.carried_typed = self.total_typed
        new.events.append({"n": self.n, "event": "handoff", "text": r.text})
        g = copy.deepcopy(self.graph); surv = g.survive(r.text); new.graph = g      # only what the note says carries over
        return HandoffResult(note=r.text, note_tokens=self.vllm.count(r.text), new_session=new, graph_survive=surv)

    def state(self) -> dict:
        return {"id": self.id, "mode": self.mode, "n": self.n, "turns": [t.to_dict() for t in self.turns],
                "events": self.events, "memory": {"label": self.memory[0], "text": self.memory[1]} if self.memory else None,
                "totals": {"sent": self.total_sent, "new": self.total_new, "typed": self.total_typed,
                           "cost_usd": self._cost(self.total_sent, self.total_new)},
                "window_tokens": self.cfg.window_tokens, "next_would_send": self.vllm.count_messages(self.messages),
                "max_tokens": self.cfg.answer_max_tokens, "tools": self.tools is not None,
                "graph": self.graph.to_dict()}
