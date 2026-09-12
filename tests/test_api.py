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
    assert j["vllm"] == "ok" and j["window_tokens"] == 400 and j["script_turns"] == 30


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
    fake.chat = lambda messages, max_tokens, tools=None, _f=fake: __import__("app.vllm", fromlist=["ChatResult"]).ChatResult(
        text=everything, prompt_tokens=_f.count_messages(messages), completion_tokens=40, seconds=0.0)
    jid = client.post("/api/race/run").json()["job_id"]
    j = client.get(f"/api/race/{jid}").json()
    assert j["status"] == "done", j.get("error")
    for side in ("left", "right"):
        assert len(j["sides"][side]["turns"]) == 30
        assert j["sides"][side]["totals"]["remembered"] == j["sides"][side]["totals"]["asked"] == 24
    assert [e["n"] for e in j["sides"]["right"]["events"] if e["event"] == "handoff"] == [10, 20]
    assert "Handoff every" in j["verdict"]


def test_look_reads_board_dedupes_and_commands(cfg):
    from fastapi.testclient import TestClient
    from app.main import create_app
    from tests.conftest import FakeVLLM
    fake = FakeVLLM(looks=["What's the weather in Spokane?", "Whats the weather in Spokane", "NONE", "COMPACT", "COMPACT", "How tall is Everest?"])
    c = TestClient(create_app(vllm=fake, cfg=cfg, vision=fake, tools=object()))
    sid = c.post("/api/session", json={"mode": "compact", "tools": True, "board": True}).json()["session_id"]
    look = lambda: c.post("/api/look", json={"session_id": sid, "image": "QUJD"}).json()
    r = look(); assert r["new"] and r["question"] == "What's the weather in Spokane?" and r["read_tokens"] == 1500
    r = look(); assert not r["new"] and r["question"] is None          # same board, slightly different read
    r = look(); assert not r["new"] and r["read"] == "NONE"
    r = look(); assert r["new"] and r["command"] == "COMPACT"
    r = look(); assert not r["new"]                                     # still holding COMPACT up
    r = look(); assert r["new"] and r["question"] == "How tall is Everest?"


def test_session_flags_pick_persona_and_tools(cfg):
    from fastapi.testclient import TestClient
    from app.main import create_app
    from app.session import SYSTEM_BOARD
    from tests.conftest import FakeVLLM
    fake = FakeVLLM()
    app = create_app(vllm=fake, cfg=cfg, vision=fake, tools=object())
    c = TestClient(app)
    sid = c.post("/api/session", json={"mode": "endless", "tools": True, "board": True}).json()["session_id"]
    s = app.state.sessions[sid]
    assert s.system == SYSTEM_BOARD and s.tools is not None
    assert s.cfg.window_tokens == cfg.board_window and s.cfg.window_tokens != cfg.window_tokens
    sid2 = c.post("/api/session", json={"mode": "endless"}).json()["session_id"]
    assert app.state.sessions[sid2].tools is None


def test_compact_now(cfg):
    from fastapi.testclient import TestClient
    from app.main import create_app
    from tests.conftest import FakeVLLM
    fake = FakeVLLM(responses=["ok", "SUMMARY: user said hi"])
    app = create_app(vllm=fake, cfg=cfg, vision=fake, tools=object())
    c = TestClient(app)
    sid = c.post("/api/session", json={"mode": "endless"}).json()["session_id"]
    assert c.post("/api/compact", json={"session_id": sid}).status_code == 409
    c.post("/api/turn", json={"session_id": sid, "text": "hi"})
    r = c.post("/api/compact", json={"session_id": sid}).json()
    assert r["summary"] == "SUMMARY: user said hi" and r["state"]["memory"]["text"] == "SUMMARY: user said hi"
    assert app.state.sessions[sid].transcript == []


def test_hear_wake_window_and_questions(cfg, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import create_app
    from tests.conftest import FakeVLLM
    from app.ears import HearResult
    class FakeEars:
        def __init__(self, texts): self.texts = list(texts)
        def health(self): return True
        def transcribe(self, audio, mime="audio/webm"): return HearResult(self.texts.pop(0), 0.3)
    ears = FakeEars(["what time is it", "High Compaq demo", "how tall is everest", "hi compact demo what is the weather", "um"])
    app = create_app(vllm=FakeVLLM(), cfg=cfg, vision=FakeVLLM(), tools=object(), ears=ears)
    c = TestClient(app)
    sid = c.post("/api/session", json={"mode": "endless", "board": True}).json()["session_id"]
    hear = lambda: c.post("/api/hear", json={"session_id": sid, "audio": "QUJD"}).json()
    r = hear(); assert not r["woke"] and not r["listening"] and r["question"] is None      # not awake: ignored
    r = hear(); assert r["woke"] and r["listening"] and r["question"] is None             # wake phrase alone
    r = hear(); assert not r["woke"] and r["question"] == "how tall is everest"           # inside the window
    r = hear(); assert r["woke"] and r["question"] == "what is the weather"               # wake + question in one breath
    r = hear(); assert r["question"] is None and r["listening"]                            # too short to be a question


def test_hear_without_ears_is_503(cfg):
    from fastapi.testclient import TestClient
    from app.main import create_app
    from tests.conftest import FakeVLLM
    c = TestClient(create_app(vllm=FakeVLLM(), cfg=cfg, vision=FakeVLLM(), tools=object()))
    sid = c.post("/api/session", json={"mode": "endless"}).json()["session_id"]
    assert c.post("/api/hear", json={"session_id": sid, "audio": "QUJD"}).status_code == 503
