from fastapi.testclient import TestClient

from app.main import create_app
from app.personas import ROOT, Persona, load
from app.session import Session


def test_load_parses_title_blurb_and_prompt(tmp_path):
    (tmp_path / "pirate.md").write_text("# Pirate\n> Same brain, different voice.\nYou are a pirate. Two sentences.\n")
    personas = load(tmp_path)
    assert personas["pirate"] == Persona(id="pirate", title="Pirate", blurb="Same brain, different voice.",
                                          prompt="You are a pirate. Two sentences.")


def test_load_allows_an_empty_prompt(tmp_path):
    (tmp_path / "plain.md").write_text("# No instructions\n> Nothing at all.\n")
    assert load(tmp_path)["plain"].prompt == ""


def test_load_skips_a_malformed_file(tmp_path):
    (tmp_path / "good.md").write_text("# Good\n> ok\nhi\n")
    (tmp_path / "bad.md").write_text("no header here at all\n")
    assert set(load(tmp_path)) == {"good"}


def test_load_sorts_wall_first_then_alphabetical(tmp_path):
    for pid, title in [("zeta", "Z"), ("wall", "W"), ("alpha", "A")]:
        (tmp_path / f"{pid}.md").write_text(f"# {title}\n> b\n")
    assert list(load(tmp_path)) == ["wall", "alpha", "zeta"]


def test_load_missing_dir_returns_empty():
    assert load(ROOT / "nope-does-not-exist") == {}


def test_empty_system_prompt_is_omitted_from_messages(fake, cfg):
    s = Session("endless", fake, cfg, system_prompt="")
    assert all(m["role"] != "system" for m in s.messages)


def test_empty_system_prompt_is_never_sent_to_the_model(fake, cfg):
    s = Session("endless", fake, cfg, system_prompt="")
    s.turn("hi")
    assert all(m["role"] != "system" for m in fake.calls[-1]["messages"])


def test_personas_endpoint_lists_seven_wall_first(fake, cfg):
    c = TestClient(create_app(vllm=fake, cfg=cfg))
    j = c.get("/api/personas").json()["personas"]
    assert len(j) == 7 and j[0]["id"] == "wall"
    assert {p["id"] for p in j} == {"wall", "pirate", "plain", "careful", "explain", "oneword", "skeptic"}
    assert set(j[0]) == {"id", "title", "blurb", "prompt"}


def test_session_with_plain_persona_sends_no_system_message(fake, cfg):
    app = create_app(vllm=fake, cfg=cfg, personas={"plain": Persona("plain", "Plain", "b", "")})
    c = TestClient(app)
    sid = c.post("/api/session", json={"mode": "endless", "persona": "plain"}).json()["session_id"]
    c.post("/api/turn", json={"session_id": sid, "text": "hi"})
    assert all(m["role"] != "system" for m in fake.calls[-1]["messages"])


def test_session_with_custom_system_wins_over_persona(fake, cfg):
    app = create_app(vllm=fake, cfg=cfg, personas={"pirate": Persona("pirate", "Pirate", "b", "Arr.")})
    c = TestClient(app)
    sid = c.post("/api/session", json={"mode": "endless", "persona": "pirate", "system": "custom words"}
                  ).json()["session_id"]
    c.post("/api/turn", json={"session_id": sid, "text": "hi"})
    assert fake.calls[-1]["messages"][0] == {"role": "system", "content": "custom words"}
    assert app.state.sessions[sid].persona == "custom"


def test_no_persona_or_system_is_unchanged(fake, cfg):
    from app.session import SYSTEM
    app = create_app(vllm=fake, cfg=cfg)
    c = TestClient(app)
    sid = c.post("/api/session", json={"mode": "endless"}).json()["session_id"]
    s = app.state.sessions[sid]
    assert s.system == SYSTEM and s.persona is None
