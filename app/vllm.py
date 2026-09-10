"""Thin client for the vLLM OpenAI-compatible server. Token counts come from vLLM, never estimated."""
from __future__ import annotations
import time
from dataclasses import dataclass
import httpx


@dataclass
class ChatResult:
    text: str
    prompt_tokens: int
    completion_tokens: int
    seconds: float


class VLLM:
    def __init__(self, url: str, model: str, transport: httpx.BaseTransport | None = None):
        self.url = url.rstrip("/")
        self.model = model
        self._c = httpx.Client(base_url=self.url, timeout=300, transport=transport)

    def health(self) -> bool:
        try:
            return self._c.get("/health", timeout=3).status_code == 200
        except httpx.HTTPError:
            return False

    def chat(self, messages: list[dict], max_tokens: int) -> ChatResult:
        body = {"model": self.model, "messages": messages, "max_tokens": max_tokens, "temperature": 0,
                "chat_template_kwargs": {"enable_thinking": False}}
        t0 = time.time()
        r = self._c.post("/v1/chat/completions", json=body)
        r.raise_for_status()
        j = r.json()
        u = j.get("usage", {})
        return ChatResult(text=(j["choices"][0]["message"].get("content") or "").strip(),
                          prompt_tokens=int(u.get("prompt_tokens", 0)), completion_tokens=int(u.get("completion_tokens", 0)),
                          seconds=time.time() - t0)

    def count(self, text: str) -> int:
        r = self._c.post("/tokenize", json={"model": self.model, "prompt": text})
        r.raise_for_status()
        return int(r.json()["count"])

    def count_messages(self, messages: list[dict]) -> int:
        r = self._c.post("/tokenize", json={"model": self.model, "messages": messages, "add_generation_prompt": True,
                                           "chat_template_kwargs": {"enable_thinking": False}})
        r.raise_for_status()
        return int(r.json()["count"])
