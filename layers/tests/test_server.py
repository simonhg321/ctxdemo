from fastapi.testclient import TestClient
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
