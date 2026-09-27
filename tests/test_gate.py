import pytest
from fastapi.testclient import TestClient
from dataclasses import replace
from app.main import create_app
from app.gate import Gate, TRIES


@pytest.fixture
def keyfile(tmp_path):
    p = tmp_path / "key"; p.write_text("# the gate key: one line\nSG-123TEACH\n"); return p


@pytest.fixture
def gated(fake, cfg, keyfile):
    return TestClient(create_app(vllm=fake, cfg=replace(cfg, gate_file=str(keyfile))), follow_redirects=False)


def test_no_key_file_means_no_gate(fake, cfg):
    c = TestClient(create_app(vllm=fake, cfg=cfg))
    assert c.get("/api/gate/check").status_code == 204          # Gonzaga: nothing configured, nothing asked


def test_a_missing_or_empty_file_is_an_open_gate(tmp_path):
    assert not Gate(str(tmp_path / "nope")).enabled
    (tmp_path / "blank").write_text("\n# only a comment\n")
    assert not Gate(str(tmp_path / "blank")).enabled


def test_a_page_is_sent_to_the_gate_and_a_fetch_is_told_no(gated):
    r = gated.get("/api/gate/check", headers={"accept": "text/html,*/*", "x-forwarded-uri": "/static/peek/wall.html?with=room", "x-forwarded-method": "GET"})
    assert r.status_code == 302 and r.headers["location"] == "/gate?next=%2Fstatic%2Fpeek%2Fwall.html%3Fwith%3Droom"
    assert gated.get("/api/gate/check", headers={"accept": "application/json", "x-forwarded-uri": "/api/health"}).status_code == 401
    assert gated.get("/api/gate/check", headers={"accept": "text/html", "x-forwarded-method": "POST"}).status_code == 401


def test_the_right_key_opens_it_in_any_case_and_with_spaces(gated):
    r = gated.post("/api/gate", json={"key": "  sg-123teach "})
    sc = r.headers["set-cookie"]
    assert r.status_code == 200 and "HttpOnly" in sc and "Secure" in sc and "Max-Age=2592000" in sc
    value = sc.split("gate=", 1)[1].split(";", 1)[0]                       # Secure: the test client (http) will not send it back by itself
    assert gated.get("/api/gate/check", headers={"accept": "text/html", "cookie": "gate=" + value}).status_code == 204
    assert gated.get("/api/gate/check", headers={"accept": "application/json", "cookie": "gate=forged"}).status_code == 401


def test_a_wrong_key_stays_out_and_the_page_never_holds_the_key(gated):
    assert gated.post("/api/gate", json={"key": "SG-000NOPE"}).status_code == 403
    assert gated.post("/api/gate", json={"key": ""}).status_code == 403
    page = gated.get("/gate")
    assert page.status_code == 200 and "123TEACH" not in page.text.upper()


def test_changing_the_file_changes_the_key_and_ends_old_cookies(gated, keyfile):
    old = gated.post("/api/gate", json={"key": "SG-123TEACH"}).headers["set-cookie"].split("gate=", 1)[1].split(";", 1)[0]
    assert gated.get("/api/gate/check", headers={"cookie": "gate=" + old}).status_code == 204
    keyfile.write_text("SG-RIVER26\n")                                                             # no restart
    assert gated.get("/api/gate/check", headers={"accept": "application/json", "cookie": "gate=" + old}).status_code == 401
    assert gated.post("/api/gate", json={"key": "SG-123TEACH"}).status_code == 403
    assert gated.post("/api/gate", json={"key": "sg-river26"}).status_code == 200


def test_guessing_is_slowed_per_address(gated):
    h = {"x-forwarded-for": "203.0.113.9"}
    for _ in range(TRIES):
        assert gated.post("/api/gate", json={"key": "nope"}, headers=h).status_code == 403
    assert gated.post("/api/gate", json={"key": "SG-123TEACH"}, headers=h).status_code == 429     # even the right key waits
    assert gated.post("/api/gate", json={"key": "SG-123TEACH"}, headers={"x-forwarded-for": "203.0.113.10"}).status_code == 200


def test_the_throttle_forgets_after_a_minute(tmp_path):
    (tmp_path / "k").write_text("SG-123TEACH"); t = [1000.0]
    g = Gate(str(tmp_path / "k"), now=lambda: t[0])
    for _ in range(TRIES): g.try_key("x", "a")
    assert g.throttled("a")
    t[0] += 61
    assert not g.throttled("a") and g.try_key("SG-123TEACH", "a")
