import pytest
from app.session import Session


def words(n): return " ".join(["w"] * n)


def test_endless_grows_and_hits_limit(fake, cfg):
    s = Session("endless", fake, cfg)             # window 400, fake: +4 per msg
    fake.responses = [words(50)] * 20
    sent = []
    for i in range(20):
        t = s.turn(words(30))
        if t.event == "over_limit":
            break
        sent.append(t.sent_tokens)
    assert sent == sorted(sent) and len(set(sent)) == len(sent), "each turn sends more than the last"
    assert t.event == "over_limit" and t.answer is None
    calls_before = len(fake.calls)
    s.turn(words(30))                              # still over; must not call the model
    assert len(fake.calls) == calls_before
    assert "tokens" in t.event_text


def test_compact_fires_at_80pct_and_shrinks(fake, cfg):
    s = Session("compact", fake, cfg)
    fake.responses = [words(50)] * 3 + ["SUMMARY date room budget"] + [words(20)] * 10
    events = []
    for i in range(6):
        t = s.turn(words(30))
        if t.event: events.append((t.n, t.event))
    assert events and events[0][1] == "compacted"
    assert s.memory and s.memory[1].startswith("SUMMARY")
    # after compaction, the backpack is: system + memory pair + the turns since
    n_since = sum(1 for x in s.turns if x.n > events[0][0]) + 1
    assert len(s.messages) == 3 + 2 * n_since
    assert s.events[0]["event"] == "compacted" and "SUMMARY" in s.events[0]["text"]


def test_handoff_starts_fresh_and_continues_totals(fake, cfg):
    s = Session("handoff", fake, cfg)
    fake.responses = ["a1", "a2", "NOTE: date is oct 24"]
    s.turn("first"); s.turn("second")
    old_total = s.total_sent
    h = s.handoff()
    assert h.note.startswith("NOTE")
    new = h.new_session
    assert new.id != s.id and new.turns == [] and new.n == 2
    assert [m["role"] for m in new.messages] == ["system", "user", "assistant"]
    assert "Handoff note" in new.messages[1]["content"] and "oct 24" in new.messages[1]["content"]
    assert new.total_sent > old_total, "the handoff call itself is charged"
    t = new.turn("third")
    assert t.n == 3 and t.total_sent == new.total_sent


def test_breakdown_sums_to_sent(fake, cfg):
    s = Session("endless", fake, cfg)
    fake.responses = ["x y z"]
    t = s.turn("a b c d")
    parts = sum(t.breakdown.values())
    assert t.sent_tokens == parts + 4 * 2                 # 2 messages of framing in the fake


def test_cost_uses_prices(fake, cfg):
    s = Session("endless", fake, cfg)
    fake.responses = ["one two"]
    t = s.turn("hello there")
    assert t.cost_usd == {"Test": round((t.sent_tokens * 1.0 + 2 * 2.0) / 1e6, 5)}


def test_tool_loop_runs_tools_and_sums_tokens(cfg):
    from app.vllm import ChatResult
    from app.session import Session
    from tests.conftest import FakeVLLM
    class FakeTools:
        def __init__(self): self.calls = []
        def run(self, name, args): self.calls.append((name, args)); return "1. Spokane weather: sunny 71F"
    call = ChatResult(text="", prompt_tokens=0, completion_tokens=2, seconds=0.1,
                      tool_calls=[{"id": "c1", "type": "function", "function": {"name": "web_search", "arguments": '{"query":"spokane weather"}'}}])
    fake = FakeVLLM(responses=[call, "Sunny and 71F in Spokane (web)."])
    tools = FakeTools()
    s = Session("endless", fake, cfg, tools=tools)
    tr = s.turn("weather in spokane?")
    assert tools.calls == [("web_search", '{"query":"spokane weather"}')]
    assert tr.answer.startswith("Sunny") and tr.tool_uses[0]["name"] == "web_search"
    assert fake.calls[0]["tools"] is not None and len(fake.calls) == 2
    # the second call carried the tool result in the backpack, and the turn charges both calls
    assert fake.calls[1]["messages"][-1]["role"] == "tool"
    assert tr.sent_tokens == sum(fake.count_messages(c["messages"]) for c in fake.calls)
    roles = [m["role"] for m in s.transcript]
    assert roles == ["user", "assistant", "tool", "assistant"]
    assert "[called web_search]" in s._transcript_text()


def test_no_tools_means_no_tools_param(cfg):
    from app.session import Session
    from tests.conftest import FakeVLLM
    fake = FakeVLLM()
    Session("endless", fake, cfg).turn("hi")
    assert fake.calls[0]["tools"] is None
