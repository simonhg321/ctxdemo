import asyncio
import time
import pytest
from fastapi.testclient import TestClient
import httpx
from layers.server import create_app
from layers.engine import Engine
from layers.tests.test_engine import StubRunner


def client():
    return TestClient(create_app(Engine("stub/model", device="cpu", loader=lambda n, d: StubRunner())))


def test_health_and_layers_roundtrip():
    c = client()
    h = c.get("/health").json()
    assert h["model"] == "stub/model" and h["n_layers"] == 3 and h["device"] == "cpu" and h["busy"] is False
    r = c.post("/layers", json={"messages": [{"role": "user", "content": "hi"}], "prefix": "Ye", "top_k": 2})
    assert r.status_code == 200
    j = r.json()
    assert j["final"] == {"t": "Yes", "p": 0.9} and j["decided_at"] == 2 and len(j["layers"][0]["top"]) == 2 and "seconds" in j


def test_layers_needs_input():
    assert client().post("/layers", json={}).status_code == 400


class RecordingEngine:
    """Engine wrapper that records analyze() arguments."""
    def __init__(self, wrapped_engine):
        self.wrapped = wrapped_engine
        self.model_name = wrapped_engine.model_name
        self.n_layers = wrapped_engine.n_layers
        self.device = wrapped_engine.device
        self.recorded_args = None

    def analyze(self, messages, prompt, prefix, top_k, max_tokens):
        self.recorded_args = (messages, prompt, prefix, top_k, max_tokens)
        return self.wrapped.analyze(messages, prompt, prefix, top_k, max_tokens)


def test_clamping():
    wrapped = Engine("stub/model", device="cpu", loader=lambda n, d: StubRunner())
    recording = RecordingEngine(wrapped)
    app = create_app(recording)
    c = TestClient(app)

    # Test top_k=50 → clamped to 10, max_tokens=1 → clamped to 64
    r = c.post("/layers", json={"messages": [{"role": "user", "content": "hi"}], "top_k": 50, "max_tokens": 1})
    assert r.status_code == 200
    _, _, _, recorded_top_k, recorded_max_tokens = recording.recorded_args
    assert recorded_top_k == 10 and recorded_max_tokens == 64

    # Test top_k=0 → clamped to 1, max_tokens=99999 → clamped to 4096
    r = c.post("/layers", json={"messages": [{"role": "user", "content": "hi"}], "top_k": 0, "max_tokens": 99999})
    assert r.status_code == 200
    _, _, _, recorded_top_k, recorded_max_tokens = recording.recorded_args
    assert recorded_top_k == 1 and recorded_max_tokens == 4096


class ErrorEngine:
    """Engine stub that raises ValueError."""
    def __init__(self):
        self.model_name = "error/model"
        self.n_layers = 1
        self.device = "cpu"

    def analyze(self, messages, prompt, prefix, top_k, max_tokens):
        raise ValueError("bad")


def test_valueerror_to_400():
    app = create_app(ErrorEngine())
    c = TestClient(app)
    r = c.post("/layers", json={"messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 400
    assert r.json()["detail"] == "bad"


class TimingEngine:
    """Engine stub that records timing around a sleep."""
    def __init__(self):
        self.model_name = "timing/model"
        self.n_layers = 1
        self.device = "cpu"
        self.calls = []

    def analyze(self, messages, prompt, prefix, top_k, max_tokens):
        start = time.time()
        time.sleep(0.2)
        end = time.time()
        self.calls.append((start, end))
        return {"final": {"t": "ok", "p": 1.0}, "decided_at": 0, "layers": []}


@pytest.mark.anyio
async def test_serialisation():
    engine = TimingEngine()
    app = create_app(engine)

    async def make_request():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test"
        ) as client:
            r = await client.post("/layers", json={"messages": [{"role": "user", "content": "hi"}]})
            assert r.status_code == 200

    await asyncio.gather(make_request(), make_request())

    # Assert requests ran sequentially: second start >= first end
    calls = sorted(engine.calls)
    assert len(calls) == 2
    assert calls[1][0] >= calls[0][1], f"Requests overlapped: {calls[0][1]} > {calls[1][0]}"
