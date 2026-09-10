import pytest
from app.config import Config
from app.vllm import ChatResult


class FakeVLLM:
    """Deterministic stand-in: 1 token per whitespace word, +4 per message for chat framing."""
    def __init__(self, responses=None):
        self.responses = list(responses or [])
        self.calls = []
        self.model = "fake"

    def health(self): return True
    def count(self, text): return len(text.split())
    def count_messages(self, messages): return sum(self.count(m["content"]) + 4 for m in messages)

    def chat(self, messages, max_tokens):
        self.calls.append({"messages": [dict(m) for m in messages], "max_tokens": max_tokens})
        text = self.responses.pop(0) if self.responses else "Echo: " + messages[-1]["content"]
        return ChatResult(text=text, prompt_tokens=self.count_messages(messages),
                          completion_tokens=self.count(text), seconds=0.01)


@pytest.fixture
def fake(): return FakeVLLM()


@pytest.fixture
def cfg():
    return Config(window_tokens=400, compact_at=0.8, summary_max_tokens=40, handoff_max_tokens=30, handoff_turn=10,
                  prices={"Test": {"in": 1.0, "out": 2.0}})
