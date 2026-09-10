from app import script, grader


def test_script_shape():
    s = script.load()
    assert len(s.turns) == 30 and len(s.details) == 12
    assert [t.n for t in s.turns] == list(range(1, 31))


def test_every_ask_was_planted_earlier():
    s = script.load()
    planted = set()
    for t in s.turns:
        for a in t.asks:
            assert a in planted, f"turn {t.n} asks {a} before it was planted"
        planted |= set(t.plants)
    assert planted == set(s.details), "every detail must be planted somewhere"


def test_grader():
    s = script.load()
    d = s.details["hdmi"]
    assert grader.remembered("Use HDMI 1 only; port 2 is dead.", d)
    assert grader.remembered("plug into hdmi   1", d)
    assert not grader.remembered("use the VGA cable", d)
    assert not grader.remembered(None, d)
    assert grader.remembered("Doors at 10AM in Herak 218", s.details["start"])
