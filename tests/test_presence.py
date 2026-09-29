from app.presence import Presence, busy_line


def test_counts_open_browsers_and_forgets_the_silent():
    t = [1000.0]
    p = Presence(ttl=30, now=lambda: t[0])
    assert p.count() == 0
    assert p.beat("a") == 1
    assert p.beat("b") == 2
    assert p.beat("a") == 2                  # the same browser again is still one person
    t[0] += 20; p.beat("b")
    t[0] += 15                               # a has been silent 35 s, b 15 s
    assert p.count() == 1
    assert p.count(but="b") == 0             # "others": everyone except the one asking
    assert p.count(but="zzz") == 1


def test_ids_are_bounded():
    p = Presence(ttl=30, cap=3)
    assert p.beat("") == 0 and p.beat("   ") == 0     # no id, no seat
    p.beat("x" * 500)
    assert p.count(but="x" * 64) == 0                 # long ids are cut to 64
    for i in range(10):
        p.beat(f"id{i}")
    assert p.count() == 3                             # a flood cannot grow the table past its cap


def test_busy_line_says_who_a_switch_would_interrupt():
    assert busy_line(0, None) == ""
    assert busy_line(0, {"running": 0, "waiting": 0}) == ""
    assert busy_line(1, None) == "1 other person is here"
    assert busy_line(3, {"running": 0, "waiting": 0}) == "3 other people are here"
    assert busy_line(0, {"running": 1, "waiting": 0}) == "1 answer is in progress"
    assert busy_line(2, {"running": 2, "waiting": 1}) == "2 other people are here · 3 answers are in progress"
