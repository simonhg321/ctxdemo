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
    ears = FakeEars(["what time is it", "High Compaq demo", "how tall is everest", "hi compact demo what is the weather", "[BLANK_AUDIO]"])
    app = create_app(vllm=FakeVLLM(), cfg=cfg, vision=FakeVLLM(), tools=object(), ears=ears)
    c = TestClient(app)
    sid = c.post("/api/session", json={"mode": "endless", "board": True}).json()["session_id"]
    hear = lambda: c.post("/api/hear", json={"session_id": sid, "audio": "QUJD"}).json()
    r = hear(); assert not r["woke"] and not r["listening"] and r["question"] is None      # not awake: ignored
    r = hear(); assert r["woke"] and r["listening"] and r["question"] is None             # wake phrase alone
    r = hear(); assert not r["woke"] and r["question"] == "how tall is everest"           # inside the window
    r = hear(); assert r["woke"] and r["question"] == "what is the weather"               # wake + question in one breath
    r = hear(); assert r["question"] is None and r["listening"] and r["heard"] == ""      # silence marker ignored


def test_hear_without_ears_is_503(cfg):
    from fastapi.testclient import TestClient
    from app.main import create_app
    from tests.conftest import FakeVLLM
    c = TestClient(create_app(vllm=FakeVLLM(), cfg=cfg, vision=FakeVLLM(), tools=object()))
    sid = c.post("/api/session", json={"mode": "endless"}).json()["session_id"]
    assert c.post("/api/hear", json={"session_id": sid, "audio": "QUJD"}).status_code == 503


# ---- the map
def test_graph_fields_on_routes(fake, cfg):
    from dataclasses import replace
    app = create_app(vllm=fake, cfg=replace(cfg, extract=True)); app.state.race_threads = False
    c = TestClient(app)
    fake.responses = ["a1", '{"concepts": ["alpha", "beta"], "links": []}', "summary: alpha", "NOTE beta"]
    sid = c.post("/api/session", json={"mode": "handoff"}).json()["session_id"]
    t = c.post("/api/turn", json={"session_id": sid, "text": "x"}).json()["turn"]
    assert t["graph_delta"]["added"] == ["alpha", "beta"]
    assert c.get(f"/api/session/{sid}").json()["graph"]["edges"] == [["alpha", "beta", 1]]
    j = c.post("/api/compact", json={"session_id": sid}).json()
    assert j["graph_survive"]["kept"] == [["alpha", 1]] and j["graph_survive"]["absorbed"] == [["beta", "alpha"]]
    h = c.post("/api/handoff", json={"session_id": sid}).json()
    assert h["graph_survive"] == {"kept": [], "absorbed": [["alpha", None]]} and h["graph_seed"]["nodes"] == []


def test_session_persona_sends_its_prompt_as_system(fake, cfg):
    from app.personas import Persona
    app = create_app(vllm=fake, cfg=cfg, personas={"pirate": Persona("pirate", "Pirate", "b", "Arr, be a pirate.")})
    c = TestClient(app)
    sid = c.post("/api/session", json={"mode": "endless", "persona": "pirate"}).json()["session_id"]
    c.post("/api/turn", json={"session_id": sid, "text": "hi"})
    assert fake.calls[-1]["messages"][0] == {"role": "system", "content": "Arr, be a pirate."}
    assert app.state.sessions[sid].persona == "pirate"


def test_session_unknown_persona_is_400(fake, cfg):
    app = create_app(vllm=fake, cfg=cfg, personas={})
    c = TestClient(app)
    assert c.post("/api/session", json={"mode": "endless", "persona": "nope"}).status_code == 400


def test_static_is_served(client):
    assert client.get("/static/replay.json").status_code in (200, 404)      # the mount exists (404 until the file lands)
    assert client.get("/static/../app/main.py").status_code in (403, 404)


def test_hear_returns_command_inside_window(fake, cfg):
    from app.ears import HearResult
    heard = iter(["hi compact demo", "compact", "hand off", "start over"])
    class FakeEars:
        def health(self): return True
        def transcribe(self, audio, mime): return HearResult(next(heard), 0.1)
    c = TestClient(create_app(vllm=fake, cfg=cfg, ears=FakeEars()))
    sid = c.post("/api/session", json={"mode": "compact", "board": True}).json()["session_id"]
    assert c.post("/api/hear", json={"session_id": sid, "audio": "AA==", "mime": "audio/webm"}).json()["woke"] is True
    for cmd in ("COMPACT", "HANDOFF", "RESET"):
        r = c.post("/api/hear", json={"session_id": sid, "audio": "AA==", "mime": "audio/webm"}).json()
        assert r["command"] == cmd and r["question"] is None


def test_hear_ignores_command_when_window_closed(fake, cfg):
    from app.ears import HearResult
    class FakeEars:
        def health(self): return True
        def transcribe(self, audio, mime): return HearResult("compact", 0.1)
    c = TestClient(create_app(vllm=fake, cfg=cfg, ears=FakeEars()))
    sid = c.post("/api/session", json={"mode": "compact", "board": True}).json()["session_id"]
    r = c.post("/api/hear", json={"session_id": sid, "audio": "AA==", "mime": "audio/webm"}).json()
    assert r["command"] is None and r["listening"] is False


def test_teach_session_uses_the_map_prompt(fake, cfg):
    from app.session import SYSTEM_MAP
    c = TestClient(create_app(vllm=fake, cfg=cfg))
    sid = c.post("/api/session", json={"mode": "compact", "board": True, "teach": True}).json()["session_id"]
    c.post("/api/turn", json={"session_id": sid, "text": "hi"})
    assert fake.calls[-1]["messages"][0]["content"] == SYSTEM_MAP


def test_listen_restarts_a_recent_window_only(fake, cfg):
    from app.ears import HearResult
    class FakeEars:
        def health(self): return True
        def transcribe(self, audio, mime): return HearResult("hi compact demo", 0.1)
    app = create_app(vllm=fake, cfg=cfg, ears=FakeEars())
    c = TestClient(app)
    sid = c.post("/api/session", json={"mode": "endless", "board": True}).json()["session_id"]
    assert c.post("/api/listen", json={"session_id": sid}).json()["listening"] is False      # never woken: stays shut
    c.post("/api/hear", json={"session_id": sid, "audio": "QUJD"})
    r = c.post("/api/listen", json={"session_id": sid}).json()
    assert r["listening"] is True and r["listen_left"] == cfg.followup_seconds


def test_board_session_window_override_is_clamped(fake, cfg):
    c = TestClient(create_app(vllm=fake, cfg=cfg))
    win = lambda body: c.post("/api/session", json=body).json()["state"]["window_tokens"]
    assert win({"mode": "endless", "board": True, "window": 2048}) == 2048
    assert win({"mode": "endless", "board": True, "window": 50}) == 1024
    assert win({"mode": "endless", "board": True, "window": 32768}) == 32768          # act 6: overflow on purpose
    assert win({"mode": "endless", "board": True, "window": 99999}) == 32768
    assert win({"mode": "endless", "board": True}) == cfg.board_window
    assert win({"mode": "endless", "window": 2048}) == cfg.window_tokens                      # only the board tab


def test_spoken_stop_closes_the_window_and_followup_is_short(fake, cfg):
    from app.ears import HearResult
    heard = iter(["hi compact demo", "Thank you.", "what is a token anyway"])
    class FakeEars:
        def health(self): return True
        def transcribe(self, audio, mime): return HearResult(next(heard), 0.1)
    c = TestClient(create_app(vllm=fake, cfg=cfg, ears=FakeEars()))
    sid = c.post("/api/session", json={"mode": "endless", "board": True}).json()["session_id"]
    hear = lambda: c.post("/api/hear", json={"session_id": sid, "audio": "QUJD"}).json()
    assert hear()["woke"]
    assert c.post("/api/listen", json={"session_id": sid}).json()["listen_left"] == cfg.followup_seconds
    r = hear(); assert r["command"] == "SLEEP" and r["listening"] is False
    r = hear(); assert r["question"] is None and not r["listening"]                          # asleep: room chatter is ignored
    assert c.post("/api/listen", json={"session_id": sid}).json()["listening"] is False       # and the answer-over ping cannot reopen it


def test_peek_turn_and_health_chunks(fake, cfg):
    class WordChunker:
        available = True
        def split(self, text): return text.split()
    c = TestClient(create_app(vllm=fake, cfg=cfg, chunker=WordChunker()))
    assert c.get("/api/health").json()["chunks"] is True
    sid = c.post("/api/session", json={"mode": "compact", "board": True, "peek": True}).json()["session_id"]
    t = c.post("/api/turn", json={"session_id": sid, "text": "hi there"}).json()["turn"]
    assert t["user_chunks"] == ["hi", "there"] and t["tokens"][0]["alts"][0]["p"] == 0.9
    sid2 = c.post("/api/session", json={"mode": "endless"}).json()["session_id"]
    assert c.post("/api/turn", json={"session_id": sid2, "text": "hi"}).json()["turn"]["tokens"] == []


def test_health_chunks_false_without_a_tokenizer(client):
    assert client.get("/api/health").json()["chunks"] is False


def test_act6_pages_are_served(client):
    html = client.get("/").text
    assert 'data-tab="guess"' in html and 'id="tab-guess"' in html
    for f in ("panel.html", "wall.html", "bus.js", "lib.js", "peek.css", "replay.json",
              "driver.js", "chunks.js", "answer.js", "almost.js", "tiles.js", "persona.js"):
        assert client.get(f"/static/peek/{f}").status_code == 200, f
    for f in ("wall.html", "panel.html", "driver.js"):
        body = client.get(f"/static/peek/{f}").text
        assert 'src="/' not in body and "fetch('/" not in body and "'/api" not in body, f
    assert "panel.html?show=" in client.get("/static/peek/wall.html").text


def test_session_max_tokens_is_clamped_and_used(fake, cfg):
    c = TestClient(create_app(vllm=fake, cfg=cfg))
    sid = c.post("/api/session", json={"mode": "endless", "max_tokens": 90000}).json()["session_id"]
    c.post("/api/turn", json={"session_id": sid, "text": "hi"})
    assert fake.calls[-1]["max_tokens"] == 10000                      # clamped to the ceiling
    sid = c.post("/api/session", json={"mode": "endless"}).json()["session_id"]
    c.post("/api/turn", json={"session_id": sid, "text": "hi"})
    assert fake.calls[-1]["max_tokens"] == cfg.answer_max_tokens      # unset: unchanged


def test_turn_reports_cut_when_server_stopped_it(fake, cfg):
    from app.vllm import ChatResult
    c = TestClient(create_app(vllm=fake, cfg=cfg))
    sid = c.post("/api/session", json={"mode": "endless"}).json()["session_id"]
    fake.responses.append(ChatResult(text="long answer that", prompt_tokens=0, completion_tokens=3, seconds=0.1, cut=True))
    assert c.post("/api/turn", json={"session_id": sid, "text": "hi"}).json()["turn"]["cut"] is True
    assert c.post("/api/turn", json={"session_id": sid, "text": "hi"}).json()["turn"]["cut"] is False
