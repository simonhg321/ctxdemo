import json

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
              "driver.js", "chunks.js", "answer.js", "almost.js", "tiles.js", "persona.js", "wire.js", "explain/25-wire.md"):
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


def test_peek_turn_carries_the_wire_and_plain_turns_do_not(fake, cfg):
    c = TestClient(create_app(vllm=fake, cfg=cfg))
    sid = c.post("/api/session", json={"mode": "compact", "board": True, "peek": True}).json()["session_id"]
    t = c.post("/api/turn", json={"session_id": sid, "text": "hi there"}).json()["turn"]
    assert t["wire"]["request"]["logprobs"] is True and t["wire"]["request"]["messages"][-1]["content"] == "hi there"
    assert "choices" in t["wire"]["response"] and t["wire"]["total"] == 3   # "Echo: hi there"
    sid2 = c.post("/api/session", json={"mode": "endless"}).json()["session_id"]
    assert c.post("/api/turn", json={"session_id": sid2, "text": "hi"}).json()["turn"]["wire"] is None


def test_wire_is_indexed_in_the_explain_bar_and_linked_from_personas(client):
    assert "25-wire.md" in client.get("/static/peek/explain.json").json()
    assert "'wire'" in client.get("/static/peek/persona.js").text          # the "how do we know?" link sends a wire message
    assert "show=wire" in client.get("/static/peek/wall.html").text        # the wall hosts it as an overlay


def test_audience_clamp_only_when_configured_and_no_presenter_header(fake, cfg):
    """NFCU Linode: plain visitors get a 4k backpack, a 600-token leash and no web search; /presenter/ (Caddy adds
    X-Presenter) gets the full set; Gonzaga (audience=False) is unchanged whatever the header says."""
    from dataclasses import replace
    c = TestClient(create_app(vllm=fake, cfg=replace(cfg, audience=True)))
    body = {"mode": "endless", "board": True, "peek": True, "tools": True, "window": 32768, "max_tokens": 10000}
    aud = c.post("/api/session", json=body).json()
    assert aud["state"]["window_tokens"] == 4096 and aud["state"]["max_tokens"] == 600 and aud["state"]["tools"] is False
    pres = c.post("/api/session", json=body, headers={"X-Presenter": "1"}).json()
    assert pres["state"]["window_tokens"] == 32768 and pres["state"]["max_tokens"] == 10000 and pres["state"]["tools"] is True
    assert c.get("/api/health").json()["audience"] is True
    assert c.get("/api/health", headers={"X-Presenter": "1"}).json()["audience"] is False
    g = TestClient(create_app(vllm=fake, cfg=cfg))                      # Gonzaga: no clamp, header ignored
    assert g.post("/api/session", json=body).json()["state"]["window_tokens"] == 32768
    assert g.get("/api/health").json()["audience"] is False


def test_audience_env_flag(monkeypatch):
    from app.config import load
    monkeypatch.setenv("CTXDEMO_AUDIENCE", "1")
    assert load().audience is True
    monkeypatch.delenv("CTXDEMO_AUDIENCE")
    assert load().audience is False


def test_driver_and_wall_use_the_audience_helpers(client):
    d = client.get("/static/peek/driver.js").text
    assert "peekLib.asksFor(" in d and "audience" in d
    w = client.get("/static/peek/wall.html").text
    assert "peekLib.wallFit(" in w and "stack" in w


def test_queue_endpoint_passes_through_or_says_none(fake, cfg):
    c = TestClient(create_app(vllm=fake, cfg=cfg))
    assert c.get("/api/queue").json() == {"queue": None}          # the fake has no /metrics
    fake.queue = lambda: {"running": 1, "waiting": 4, "kv_pct": 7}
    assert c.get("/api/queue").json() == {"queue": {"running": 1, "waiting": 4, "kv_pct": 7}}


def test_room_feed_keeps_recent_turns_with_optional_names_and_is_presenter_only(fake, cfg):
    from dataclasses import replace
    c = TestClient(create_app(vllm=fake, cfg=replace(cfg, audience=True)))
    sid = c.post("/api/session", json={"mode": "compact", "board": True, "peek": True}).json()["session_id"]
    c.post("/api/turn", json={"session_id": sid, "text": "hi there", "name": "  Priya <b>x</b> with a very long name indeed  "})
    c.post("/api/turn", json={"session_id": sid, "text": "again"})
    assert c.get("/api/room").status_code == 403                    # the audience cannot read the room
    r = c.get("/api/room", headers={"X-Presenter": "1"}).json()["turns"]
    assert len(r) == 2 and r[0]["user"] == "again" and r[1]["user"] == "hi there"          # newest first
    assert r[1]["name"] == "Priya <b>x</b> with a ve" and r[0]["name"] == r[1]["name"]      # trimmed to 24 chars; sticks to the session; the page escapes
    assert set(r[0]) >= {"ts", "name", "user", "answer", "seconds", "persona", "sure_pct", "worst", "session"}
    assert r[0]["session"] != sid                                    # a short public id, not the real session id
    g = TestClient(create_app(vllm=fake, cfg=cfg))                  # Gonzaga: no audience mode, room open (nobody hostile on the LAN)
    assert g.get("/api/room").json() == {"turns": []}


def test_room_panel_and_driver_name_box_are_served(client):
    assert client.get("/static/peek/room.js").status_code == 200
    d = client.get("/static/peek/driver.js").text
    assert "queueLine" in d and "'queue'" in d and 'id="name"' in d and "h.room" in d
    assert "gpu" in client.get("/static/peek/tiles.js").text


def test_room_flag_and_gpu_endpoint(fake, cfg, monkeypatch):
    """NFCU without the clamp: CTXDEMO_ROOM=1 turns the name box on (health.room); /api/gpu reads Netdata's GPU busy %."""
    from dataclasses import replace
    import httpx
    c = TestClient(create_app(vllm=fake, cfg=cfg))
    assert c.get("/api/health").json()["room"] is False and c.get("/api/gpu").json() == {"gpu": None}
    def handler(req):
        assert "nvidia_smi.gpu_utilization" in str(req.url)
        return httpx.Response(200, json={"labels": ["time", "gpu"], "data": [[1700000000, 37.4]]})
    c2 = TestClient(create_app(vllm=fake, cfg=replace(cfg, room=True, netdata_url="http://nd"), netdata_transport=httpx.MockTransport(handler)))
    assert c2.get("/api/health").json()["room"] is True
    assert c2.get("/api/gpu").json() == {"gpu": {"busy": 37}}
    from app.config import load
    monkeypatch.setenv("CTXDEMO_ROOM", "1"); monkeypatch.setenv("NETDATA_URL", "http://x:19999")
    l = load(); assert l.room is True and l.netdata_url == "http://x:19999"


def test_model_endpoints(fake, cfg, tmp_path):
    from dataclasses import replace
    from app.models import Switcher
    calls = []
    sw = Switcher(models=[{"id": "fake", "label": "Fake", "note": "", "args": "", "tools": True, "tokenizer": "x"},
                          {"id": "other", "label": "Other", "note": "", "args": "--y", "tools": False, "tokenizer": "y"}],
                  env_file=tmp_path / ".env", compose_dir=tmp_path, hub_dir=tmp_path, password="pw",
                  runner=lambda cmd, cwd: calls.append(cmd) or 0, wait_for=lambda mid: True, on_switched=lambda m: None)
    c = TestClient(create_app(vllm=fake, cfg=cfg, switcher=sw))
    j = c.get("/api/models").json()
    assert j["current"] == "fake" and j["switching"] is None and [m["id"] for m in j["models"]] == ["fake", "other"]
    assert c.get("/api/health").json()["switching"] is None
    assert c.post("/api/model", json={"id": "other", "password": "nope"}).status_code == 403
    assert c.post("/api/model", json={"id": "zzz", "password": "pw"}).status_code == 400
    r = c.post("/api/model", json={"id": "other", "password": "pw"})
    assert r.status_code == 200 and r.json()["switching"]["target"] == "other"
    sw.join(5)
    assert calls and calls[0][:2] == ["docker", "compose"]
    assert c.get("/static/peek/tiles.js").text.count("api/models") >= 1
    plain = TestClient(create_app(vllm=fake, cfg=cfg))                 # no switcher configured: read-only list, switch disabled
    assert plain.get("/api/models").json()["models"] == [] and plain.post("/api/model", json={"id": "x", "password": "p"}).status_code == 403


def test_vocab_flag_reaches_health_and_the_panels_use_it(client, monkeypatch):
    assert client.get("/api/health").json()["vocab"] == "wall"
    from app.config import load
    monkeypatch.setenv("CTXDEMO_VOCAB", "plain"); assert load().vocab == "plain"
    monkeypatch.setenv("CTXDEMO_VOCAB", "weird"); assert load().vocab == "wall"        # anything else = the default words
    assert "setVocab(" in client.get("/static/peek/panel.html").text                     # every panel learns the words before it mounts
    for f in ("tiles.js", "chunks.js", "driver.js", "wire.js", "answer.js", "almost.js"):
        assert "peekLib.words(" in client.get(f"/static/peek/{f}").text, f
    assert "plainText(" in client.get("/static/peek/explain.js").text                   # the explain cards too


def test_api_layers_sends_the_sessions_real_messages_and_the_answer_prefix(fake, cfg):
    """Piece 4: the panel asks how token i of the last answer formed; we send the messages as sent + tokens[:i] to the sidecar."""
    from dataclasses import replace
    import httpx
    seen = {}
    def sidecar(req: httpx.Request):
        if req.url.path == "/health":
            return httpx.Response(200, json={"model": "Qwen/Qwen3-4B", "n_layers": 36, "device": "cuda", "busy": False})
        seen["path"] = req.url.path
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json={"tokens": ["a"], "final": {"t": "Yes", "p": 0.9}, "layers": [], "decided_at": 20,
                                         "attention": [], "cut": False, "model": "Qwen/Qwen3-4B", "n_layers": 36, "seconds": 0.2})
    c = TestClient(create_app(vllm=fake, cfg=replace(cfg, layers_url="http://layers"), layers_transport=httpx.MockTransport(sidecar)))
    assert c.get("/api/health").json()["layers"] == "ok"
    sid = c.post("/api/session", json={"mode": "compact", "board": True, "peek": True, "persona": "wall"}).json()["session_id"]
    assert c.post("/api/layers", json={"session_id": sid, "index": 0}).status_code == 400          # no answer yet
    c.post("/api/turn", json={"session_id": sid, "text": "hi there"})                                # fake answers "Echo: hi there" → tokens Echo: / hi / there
    r = c.post("/api/layers", json={"session_id": sid, "index": 2}).json()
    assert r["decided_at"] == 20 and r["index"] == 2 and r["wall_token"] == "there"
    assert seen["path"] == "/layers"
    msgs = seen["body"]["messages"]
    assert msgs[0]["role"] == "system" and msgs[-1] == {"role": "user", "content": "hi there"}          # the messages as sent, ending with the user turn
    assert seen["body"]["prefix"] == "Echo:hi"                                                       # tokens[:2] joined as text
    assert seen["body"]["top_k"] == 5
    r0 = c.post("/api/layers", json={"session_id": sid}).json()                                      # index omitted = the first token
    assert r0["index"] == 0 and r0["wall_token"] == "Echo:"
    assert c.post("/api/layers", json={"session_id": sid, "index": 99}).status_code == 400
    assert c.post("/api/layers", json={"session_id": "nope", "index": 0}).status_code == 404


def test_api_layers_off_and_down(fake, cfg):
    from dataclasses import replace
    import httpx
    off = TestClient(create_app(vllm=fake, cfg=cfg))
    assert off.get("/api/health").json()["layers"] == "none"
    assert off.post("/api/layers", json={"session_id": "x", "index": 0}).status_code == 503
    down = TestClient(create_app(vllm=fake, cfg=replace(cfg, layers_url="http://layers"),
                                 layers_transport=httpx.MockTransport(lambda r: httpx.Response(500, text="boom"))))
    assert down.get("/api/health").json()["layers"] == "down"
    sid = down.post("/api/session", json={"mode": "compact", "board": True, "peek": True}).json()["session_id"]
    down.post("/api/turn", json={"session_id": sid, "text": "hi"})
    assert down.post("/api/layers", json={"session_id": sid, "index": 0}).status_code == 502
    def bad_json(req: httpx.Request):
        if req.url.path == "/health":
            return httpx.Response(200, json={"model": "Qwen/Qwen3-4B", "n_layers": 36, "device": "cuda", "busy": False})
        return httpx.Response(200, text="not json")
    badjson = TestClient(create_app(vllm=fake, cfg=replace(cfg, layers_url="http://layers"),
                                    layers_transport=httpx.MockTransport(bad_json)))
    assert badjson.get("/api/health").json()["layers"] == "ok"
    sid2 = badjson.post("/api/session", json={"mode": "compact", "board": True, "peek": True}).json()["session_id"]
    badjson.post("/api/turn", json={"session_id": sid2, "text": "hi"})
    assert badjson.post("/api/layers", json={"session_id": sid2, "index": 0}).status_code == 502


def test_layers_panel_chip_and_wall_slot_are_served(client):
    assert client.get("/static/peek/layers.js").status_code == 200
    assert "45-layers.md" in client.get("/static/peek/explain.json").json()
    assert client.get("/static/peek/explain/45-layers.md").status_code == 200
    assert "'layers'" in client.get("/static/peek/wall.html").text            # ?with=layers slot
    d = client.get("/static/peek/driver.js").text
    assert "session_id" in d and "'turn', slim" in d and "sid" in d           # the driver puts the session id on the turn message (Step 3)
    js = client.get("/static/peek/layers.js").text
    assert "api/layers" in js and "peekLib.layersModel(" in js and "peekLib.words(" in js and "fetch('/" not in js
    assert "&quot;" in js
    assert "cache[" in js or "cache =" in js
    assert "wall_token" in js


def test_explain_bar_tells_the_story_in_order(client):
    # a first-time human meets "tokens" before "every token is a bet": tokens -> guesses -> almost said -> the chooser trio -> persona ...
    files = client.get("/static/peek/explain.json").json()
    assert files[0] == "10-pieces.md" and files[-1] == "60-wall.md"
    order = [files.index(f) for f in ("20-guesses.md", "30-almost.md", "02-chooser.md", "04-temperature.md", "06-loops.md", "40-persona.md", "50-backpack.md")]
    assert order == sorted(order)
    for f in ("02-chooser.md", "04-temperature.md", "06-loops.md"):
        body = client.get(f"/static/peek/explain/{f}").text
        assert body.startswith("# ")
        assert "piece" in body               # wall vocabulary; plainText swaps it to "token" under CTXDEMO_VOCAB=plain


def test_this_wall_card_is_venue_neutral_and_filled_from_health(client, monkeypatch):
    # the same card serves Gonzaga (L40, nothing leaves the building) and a rented Linode: model + host come from /api/health
    assert client.get("/api/health").json()["host"] == "a single GPU"
    from app.config import load
    monkeypatch.setenv("CTXDEMO_HOST_BLURB", "one rented GPU in Seattle"); assert load().host_blurb == "one rented GPU in Seattle"
    body = client.get("/static/peek/explain/60-wall.md").text
    assert "{{model}}" in body and "{{host}}" in body
    assert "L40" not in body and "Qwen3-8B" not in body and "nothing leaves" not in body
    assert "fillVars(" in client.get("/static/peek/explain.js").text and "chipsFor(" in client.get("/static/peek/explain.js").text


def test_default_persona_and_context_card_are_venue_neutral(client):
    # laptops have no camera and no whiteboard; the wall has no tabs any more
    p = {x["id"]: x for x in client.get("/api/personas").json()["personas"]}
    assert p["wall"]["title"] == "Short answers"
    assert "camera" not in p["wall"]["prompt"] and "whiteboard" not in p["wall"]["prompt"]
    assert "Tab 4" not in client.get("/static/peek/explain/50-backpack.md").text


def test_model_leash_caps_the_session_max_tokens(fake, cfg, tmp_path):
    # a model that runs away under greedy decoding (DeepSeek R1) gets a shorter leash in config/models.json: "max_tokens"
    from app.models import Switcher
    sw = Switcher(models=[{"id": "fake", "label": "Fake", "note": "", "args": "", "tools": True, "tokenizer": "x", "max_tokens": 2000}],
                  env_file=tmp_path / ".env", compose_dir=tmp_path, hub_dir=tmp_path, password="pw")
    c = TestClient(create_app(vllm=fake, cfg=cfg, switcher=sw))
    sid = c.post("/api/session", json={"mode": "endless", "max_tokens": 10000}).json()["session_id"]
    c.post("/api/turn", json={"session_id": sid, "text": "hi"})
    assert fake.calls[-1]["max_tokens"] == 2000
    sid = c.post("/api/session", json={"mode": "endless", "max_tokens": 500}).json()["session_id"]   # under the cap: untouched
    c.post("/api/turn", json={"session_id": sid, "text": "hi"})
    assert fake.calls[-1]["max_tokens"] == 500


def test_deepseek_has_a_short_leash_in_the_allow_list():
    from app.models import load_models
    ds = next(m for m in load_models() if "DeepSeek" in m["id"])
    assert ds["max_tokens"] == 2000


def test_layers_layout_scales_the_short_right_column_panels(client):
    # ?with=layers squeezes "what it almost said" and the layers panel into short boxes; their type scales from the
    # iframe's own size, so the layout hands them a bigger unit via panel.html?scale=
    src = client.get("/static/peek/wall.html").text
    assert "almost: [64, 30, 34, 20, 1.35]" in src and "layers: [64, 51, 34, 27, 1.3]" in src
    assert "&scale=" in src
