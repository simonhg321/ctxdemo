import pytest
from fastapi.testclient import TestClient
from app.main import create_app


@pytest.fixture
def client(fake, cfg):
    app = create_app(vllm=fake, cfg=cfg)
    app.state.race_threads = False          # run the race synchronously in tests
    return TestClient(app)


def test_health(client):
    j = client.get("/api/health").json()
    assert j["vllm"] == "ok" and j["window_tokens"] == 400 and j["script_turns"] == 20


def test_session_and_scripted_turns(client, fake):
    fake.responses = ["It's on Saturday October 24th, doors at 10am."] * 30
    sid = client.post("/api/session", json={"mode": "endless"}).json()["session_id"]
    t1 = client.post("/api/turn", json={"session_id": sid}).json()["turn"]
    assert t1["n"] == 1 and t1["user"].startswith("Hey, I need help")
    t2 = client.post("/api/turn", json={"session_id": sid, "text": "free text"}).json()["turn"]
    assert t2["n"] == 2 and t2["user"] == "free text"
    st = client.get(f"/api/session/{sid}").json()
    assert st["n"] == 2 and st["totals"]["sent"] > 0 and "next_would_send" in st


def test_bad_mode(client):
    assert client.post("/api/session", json={"mode": "nope"}).status_code == 400


def test_handoff_route(client, fake):
    fake.responses = ["a", "b", "NOTE"]
    sid = client.post("/api/session", json={"mode": "handoff"}).json()["session_id"]
    client.post("/api/turn", json={"session_id": sid}); client.post("/api/turn", json={"session_id": sid})
    h = client.post("/api/handoff", json={"session_id": sid}).json()
    assert h["note"] == "NOTE" and h["session_id"] != sid
    assert client.get(f"/api/session/{h['session_id']}").json()["memory"]["text"] == "NOTE"


def test_race_completes_with_verdict(client, fake, cfg):
    # generous window so the fake conversation never overflows; answers always contain every detail
    cfg.window_tokens = 100000
    fake.responses = None
    everything = "Saturday October 24th, Herak 218, $1,850, Dr. Priya Raman, vegan, HDMI 1 port 2 is dead, 10am, 40 t-shirts Spokane Print Co, BULLDOG24, GPU wall dashboard, 12 pizzas Flying Goat, October 9th"
    fake.chat = lambda messages, max_tokens, _f=fake: __import__("app.vllm", fromlist=["ChatResult"]).ChatResult(
        text=everything, prompt_tokens=_f.count_messages(messages), completion_tokens=40, seconds=0.0)
    jid = client.post("/api/race/run").json()["job_id"]
    j = client.get(f"/api/race/{jid}").json()
    assert j["status"] == "done", j.get("error")
    for side in ("left", "right"):
        assert len(j["sides"][side]["turns"]) == 30
        assert j["sides"][side]["totals"]["remembered"] == j["sides"][side]["totals"]["asked"] == 24
    assert [e["n"] for e in j["sides"]["right"]["events"] if e["event"] == "handoff"] == [10, 20]
    assert "Handoff:" in j["verdict"]
