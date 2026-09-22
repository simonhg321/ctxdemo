"""Client for an OpenAI-compatible chat server: vLLM (exact token counts via /tokenize) or Ollama (no
/tokenize — counts before sending are estimated, counts after sending are real from `usage`)."""
from __future__ import annotations
import json, math, re, time
from dataclasses import dataclass, field
import httpx


@dataclass
class ChatResult:
    text: str
    prompt_tokens: int
    completion_tokens: int
    seconds: float
    tool_calls: list[dict] = field(default_factory=list)   # OpenAI format: {id, type, function:{name, arguments}}
    tokens: list[dict] = field(default_factory=list)       # peek only: {t, p, alts:[{t, p}]} per generated piece
    cut: bool = False                                      # True when the server stopped it at max_tokens (finish_reason "length")


def text_of(content) -> str:
    """Message content may be a string, None, or a list of parts. Return the text part(s)."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    return " ".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text")


def estimate(text: str) -> int:
    """Rough token estimate for servers without /tokenize: ~3.6 chars per token for English."""
    return max(1, round(len(text) / 3.6)) if text else 0


TOP_GUESSES = 5


def _piece(it: dict) -> str:
    """Text of one piece. Prefer the raw bytes: a piece can be half a character, and must not crash the wall."""
    b = it.get("bytes")
    if isinstance(b, list) and b:
        return bytes(b).decode("utf-8", errors="replace")
    return str(it.get("token", ""))


def _prob(it: dict) -> float:
    return round(math.exp(min(0.0, float(it.get("logprob", 0.0)))), 4)


_SPECIAL = re.compile(r"<\|[a-z_]+\|>")


def parse_logprobs(choice: dict | None) -> list[dict]:
    """OpenAI-format logprobs (same from Ollama and vLLM) -> [{t, p, alts}]. Never raises; anything odd -> []."""
    try:
        out = []
        for it in ((choice or {}).get("logprobs") or {}).get("content") or []:
            me = {"t": _piece(it), "p": _prob(it)}
            if _SPECIAL.fullmatch(me["t"]):        # vLLM lists the end-of-turn marker (<|im_end|>) as a piece; it is not part of the answer
                continue
            alts = [{"t": _piece(a), "p": _prob(a)} for a in (it.get("top_logprobs") or [])]
            if me not in alts:
                alts.append(me)
            alts.sort(key=lambda a: -a["p"])
            out.append({**me, "alts": alts[:TOP_GUESSES]})
        return out
    except Exception:
        return []


class VLLM:
    def __init__(self, url: str, model: str, transport: httpx.BaseTransport | None = None):
        self.url = url.rstrip("/")
        self.model = model
        self._c = httpx.Client(base_url=self.url, timeout=300, transport=transport)
        self._tokenize: bool | None = None        # None = unknown yet; False = server has no /tokenize
        self.exact = True                          # False once we know counts are estimates

    def health(self) -> bool:
        try:
            if self._c.get("/health", timeout=3).status_code == 200:
                return True
            return self._c.get("/v1/models", timeout=3).status_code == 200
        except httpx.HTTPError:
            return False

    def _chat(self, body: dict) -> ChatResult:
        t0 = time.time()
        r = self._c.post("/v1/chat/completions", json=body)
        r.raise_for_status()
        j = r.json()
        choice = j["choices"][0]
        msg = choice["message"]
        u = j.get("usage") or {}
        return ChatResult(text=(text_of(msg.get("content"))).strip(),
                          prompt_tokens=int(u.get("prompt_tokens", 0)), completion_tokens=int(u.get("completion_tokens", 0)),
                          seconds=time.time() - t0, tool_calls=list(msg.get("tool_calls") or []),
                          tokens=parse_logprobs(choice), cut=choice.get("finish_reason") == "length")

    def chat(self, messages: list[dict], max_tokens: int, tools: list[dict] | None = None, peek: bool = False) -> ChatResult:
        body = {"model": self.model, "messages": messages, "max_tokens": max_tokens, "temperature": 0,
                "chat_template_kwargs": {"enable_thinking": False}}
        if tools:
            body["tools"] = tools
        if peek:                                   # ask for the ranked guesses behind every piece (act 6)
            body["logprobs"], body["top_logprobs"] = True, TOP_GUESSES
        return self._chat(body)

    def look(self, image_b64: str, prompt: str, max_tokens: int = 120, mime: str = "image/jpeg") -> ChatResult:
        """One vision call: the image plus a text prompt, no history."""
        content = [{"type": "text", "text": prompt},
                   {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{image_b64}"}}]
        return self._chat({"model": self.model, "messages": [{"role": "user", "content": content}],
                           "max_tokens": max_tokens, "temperature": 0,
                           "chat_template_kwargs": {"enable_thinking": False}})

    # ---- counting
    def _tok(self, body: dict) -> int | None:
        if self._tokenize is False:
            return None
        r = self._c.post("/tokenize", json=body)
        if r.status_code == 404:
            self._tokenize, self.exact = False, False
            return None
        r.raise_for_status()
        self._tokenize = True
        return int(r.json()["count"])

    def count(self, text: str) -> int:
        n = self._tok({"model": self.model, "prompt": text})
        return estimate(text) if n is None else n

    def count_messages(self, messages: list[dict]) -> int:
        n = self._tok({"model": self.model, "messages": messages, "add_generation_prompt": True,
                       "chat_template_kwargs": {"enable_thinking": False}})
        if n is not None:
            return n
        total = 0
        for m in messages:
            total += estimate(text_of(m.get("content"))) + 4
            for tc in m.get("tool_calls") or []:
                total += estimate(json.dumps(tc.get("function", {})))
        return total
