import pytest
from app.config import Config
from app.vllm import ChatResult, text_of


class FakeVLLM:
    """Deterministic stand-in: 1 token per whitespace word, +4 per message for chat framing."""
    def __init__(self, responses=None, looks=None):
        self.responses = list(responses or [])   # str, or ChatResult (to return tool_calls)
        self.looks = list(looks or [])           # what the whiteboard "says", in order
        self.calls = []
        self.model = "fake"
        self.exact = True

    def health(self): return True
    def count(self, text): return len((text or "").split())
    def count_messages(self, messages): return sum(self.count(text_of(m.get("content"))) + 4 for m in messages)

    def chat(self, messages, max_tokens, tools=None):
        self.calls.append({"messages": [dict(m) for m in messages], "max_tokens": max_tokens, "tools": tools})
        nxt = self.responses.pop(0) if self.responses else "Echo: " + text_of(messages[-1].get("content"))
        if isinstance(nxt, ChatResult):
            nxt.prompt_tokens = self.count_messages(messages); return nxt
        return ChatResult(text=nxt, prompt_tokens=self.count_messages(messages),
                          completion_tokens=self.count(nxt), seconds=0.01)

    def look(self, image_b64, prompt, max_tokens=120, mime="image/jpeg"):
        text = self.looks.pop(0) if self.looks else "NONE"
        return ChatResult(text=text, prompt_tokens=1500, completion_tokens=self.count(text), seconds=0.5)


@pytest.fixture
def fake(): return FakeVLLM()


@pytest.fixture
def cfg():
    return Config(window_tokens=400, compact_at=0.8, summary_max_tokens=40, handoff_max_tokens=30, handoff_turn=10,
                  prices={"Test": {"in": 1.0, "out": 2.0}})
