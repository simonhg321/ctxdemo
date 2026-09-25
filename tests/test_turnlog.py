import json
from dataclasses import replace

from fastapi.testclient import TestClient

from app.main import create_app
from app.turnlog import TurnLog, hesitations


def test_hesitations_counts_and_worst():
    toks = [{"t": "Hi", "p": 0.95, "alts": [{"t": "Hi", "p": 0.95}]},
            {"t": " ", "p": 0.2, "alts": []},                                        # whitespace never counts
            {"t": " there", "p": 0.4, "alts": [{"t": " you", "p": 0.5}, {"t": " there", "p": 0.4}]},
            {"t": "!", "p": 0.7, "alts": [{"t": "!", "p": 0.7}, {"t": ".", "p": 0.3}]}]
    h = hesitations(toks)
    assert (h["pieces"], h["unsure"], h["flips"]) == (4, 2, 1)
    assert h["worst"][0] == {"t": " there", "p": 0.4, "vs": [" you"]}


def test_turnlog_off_writes_nothing(tmp_path):
    tl = TurnLog(None)
    tl.write("s", "board", "hi", "hello", 0.1)
    assert not list(tmp_path.iterdir()) and tl.enabled is False


def test_turn_appends_one_line_when_enabled(fake, cfg, tmp_path):
    path = tmp_path / "logs" / "turns.jsonl"
    c = TestClient(create_app(vllm=fake, cfg=replace(cfg, turnlog=str(path))))
    sid = c.post("/api/session", json={"mode": "compact", "board": True, "peek": True}).json()["session_id"]
    fake.responses.append("Hello there")
    c.post("/api/turn", json={"session_id": sid, "text": "say hi"})
    lines = path.read_text().splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["session"] == sid and rec["tab"] == "board+peek" and rec["source"] == "typed"
    assert rec["user"] == "say hi" and rec["answer"] == "Hello there"
    assert rec["guesses"]["pieces"] == 2


def test_turn_log_line_carries_persona(fake, cfg, tmp_path):
    from app.personas import Persona
    path = tmp_path / "turns.jsonl"
    app = create_app(vllm=fake, cfg=replace(cfg, turnlog=str(path)), personas={"pirate": Persona("pirate", "Pirate", "b", "Arr.")})
    c = TestClient(app)
    sid = c.post("/api/session", json={"mode": "endless", "persona": "pirate"}).json()["session_id"]
    c.post("/api/turn", json={"session_id": sid, "text": "hi"})
    rec = json.loads(path.read_text().splitlines()[0])
    assert rec["persona"] == "pirate"


def test_turn_log_line_omits_persona_when_none(fake, cfg, tmp_path):
    path = tmp_path / "turns.jsonl"
    c = TestClient(create_app(vllm=fake, cfg=replace(cfg, turnlog=str(path))))
    sid = c.post("/api/session", json={"mode": "endless"}).json()["session_id"]
    c.post("/api/turn", json={"session_id": sid, "text": "hi"})
    rec = json.loads(path.read_text().splitlines()[0])
    assert "persona" not in rec


def test_turn_writes_nothing_by_default(fake, cfg, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    c = TestClient(create_app(vllm=fake, cfg=cfg))
    sid = c.post("/api/session", json={"mode": "compact"}).json()["session_id"]
    c.post("/api/turn", json={"session_id": sid, "text": "say hi"})
    assert not list(tmp_path.iterdir())


def test_turn_log_keeps_every_piece_and_the_system_prompt(fake, cfg, tmp_path):
    path = tmp_path / "turns.jsonl"
    c = TestClient(create_app(vllm=fake, cfg=replace(cfg, turnlog=str(path))))
    sid = c.post("/api/session", json={"mode": "compact", "board": True, "peek": True}).json()["session_id"]
    fake.responses.append("Hello there")
    c.post("/api/turn", json={"session_id": sid, "text": "say hi"})
    rec = json.loads(path.read_text().splitlines()[0])
    assert [p["t"] for p in rec["pieces"]] == ["Hello", "there"] and rec["pieces"][0]["alts"]
    assert "university lab" in rec["system"] and rec["window_tokens"] == 1600 and rec["max_tokens"] == cfg.answer_max_tokens
    assert rec["cut"] is False and rec["tool_uses"] == [] and rec["model"] == "fake"


def test_retention_prunes_old_lines_in_place_and_keeps_fresh_ones(tmp_path):
    import time
    path = tmp_path / "turns.jsonl"
    tl = TurnLog(path, keep=300)
    old = time.strftime(TurnLog.TS, time.localtime(time.time() - 600))
    path.write_text(json.dumps({"ts": old, "user": "old"}) + "\n" + "not json\n")
    ino = path.stat().st_ino
    tl.write("s", "board", "fresh", "hi", 0.1)
    recs = [json.loads(l) for l in path.read_text().splitlines()]
    assert [r["user"] for r in recs] == ["fresh"]                 # the old line and the junk line are gone, on the first write
    assert path.stat().st_ino == ino                               # rewritten in place: the container's appender never loses the file
    assert tl.prune(now=time.time() + 301) == 1 and path.read_text() == ""   # and the pruner empties it after the window


def test_no_retention_by_default_and_gonzaga_keeps_forever(tmp_path):
    path = tmp_path / "turns.jsonl"
    tl = TurnLog(path)
    tl.write("s", "board", "a", "b", 0.1); tl.write("s", "board", "c", "d", 0.1)
    assert tl.keep == 0 and tl.prune() == 0 and len(path.read_text().splitlines()) == 2
    tl.start_pruner(); assert tl._pruner is None                   # nothing to run


def test_room_feed_and_health_follow_the_retention_window(fake, cfg, tmp_path, monkeypatch):
    import time
    from app import main as m
    path = tmp_path / "turns.jsonl"
    c = TestClient(create_app(vllm=fake, cfg=replace(cfg, turnlog=str(path), turnlog_keep=300)))
    assert c.get("/api/health").json()["turnlog_keep"] == 300
    sid = c.post("/api/session", json={"mode": "compact", "board": True, "peek": True}).json()["session_id"]
    c.post("/api/turn", json={"session_id": sid, "text": "remember me"})
    assert [t["user"] for t in c.get("/api/room").json()["turns"]] == ["remember me"] and "at" not in c.get("/api/room").json()["turns"][0]
    real = time.time; monkeypatch.setattr(m.time, "time", lambda: real() + 301)
    assert c.get("/api/room").json()["turns"] == []               # five minutes later the room has forgotten it too


def test_retention_env_reaches_config(monkeypatch):
    from app.config import load
    assert load().turnlog_keep == 0
    monkeypatch.setenv("CTXDEMO_TURNLOG_KEEP", "300"); assert load().turnlog_keep == 300
    monkeypatch.setenv("CTXDEMO_TURNLOG_KEEP", "-5"); assert load().turnlog_keep == 0
