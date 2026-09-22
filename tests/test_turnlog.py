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


def test_turn_writes_nothing_by_default(fake, cfg, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    c = TestClient(create_app(vllm=fake, cfg=cfg))
    sid = c.post("/api/session", json={"mode": "compact"}).json()["session_id"]
    c.post("/api/turn", json={"session_id": sid, "text": "say hi"})
    assert not list(tmp_path.iterdir())
