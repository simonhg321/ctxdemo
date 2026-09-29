import json

from app.timings import Timings, light


def test_light_thresholds():
    assert light(None) is None
    assert light(0.4) == "green" and light(2.99) == "green"
    assert light(3) == "yellow" and light(10) == "yellow"
    assert light(10.01) == "red" and light(95) == "red"


def test_median_of_the_last_five_per_model():
    t = Timings()
    assert t.for_model("m") == {}
    for s in (2.0, 40.0, 3.0):
        t.record("m", "Pick a number", s)
    assert t.for_model("m") == {"Pick a number": {"seconds": 3.0, "light": "yellow", "n": 3}}
    for s in (1.0, 1.0, 1.0, 1.0):
        t.record("m", "Pick a number", s)              # the 2.0 and the 40.0 have aged out of the last five
    assert t.for_model("m")["Pick a number"] == {"seconds": 1.0, "light": "green", "n": 5}
    assert t.for_model("other") == {}                  # another model has its own clock
    t.record("other", "Pick a number", 12.34)
    assert t.for_model("other")["Pick a number"] == {"seconds": 12.3, "light": "red", "n": 1}


def test_bounded_and_ignores_nonsense():
    t = Timings(cap=3)
    t.record("m", "", 1.0); t.record("m", "q", None); t.record("m", "q", -1); t.record("", "q", 1.0)
    assert t.for_model("m") == {}
    t.record("m", "x" * 500, 1.0)
    assert list(t.for_model("m")) == ["x" * 200]      # question text is cut to 200
    for i in range(10):
        t.record("m", f"q{i}", 1.0)
    assert len(t.for_model("m")) == 3                  # the table cannot grow past its cap


def test_survives_a_restart_and_a_broken_file(tmp_path):
    f = tmp_path / "timings.json"
    a = Timings(str(f))
    a.record("m", "q", 4.2)
    assert json.loads(f.read_text())["m"]["q"] == [4.2]
    assert Timings(str(f)).for_model("m")["q"]["seconds"] == 4.2
    f.write_text("{not json")
    b = Timings(str(f))                                # a broken file is an empty table, never a crash
    assert b.for_model("m") == {}
    b.record("m", "q", 1.0)
    assert Timings(str(f)).for_model("m")["q"]["n"] == 1
    c = Timings(str(tmp_path / "no" / "such" / "dir" / "t.json"))
    c.record("m", "q", 1.0)                            # an unwritable path keeps timing in memory
    assert c.for_model("m")["q"]["n"] == 1
