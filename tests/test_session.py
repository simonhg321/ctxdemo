import pytest
from dataclasses import replace
from app.session import Session
from app.chunks import Chunker


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


# ---- the map: extraction per turn, survive on compaction / handoff
from dataclasses import replace as _replace


def test_extract_runs_once_per_turn_and_charges_tokens(fake, cfg):
    c = _replace(cfg, extract=True)
    ex = '{"concepts": ["quantization", "int8"], "links": []}'
    fake.responses = ["The answer about quantization.", ex]
    s = Session("endless", fake, c)
    t = s.turn("tell me about quantization")
    assert len(fake.calls) == 2 and fake.calls[1]["max_tokens"] == c.extract_max_tokens
    assert t.graph_delta["added"] == ["quantization", "int8"]
    assert t.breakdown["extract"] > 0 and sum(t.breakdown.values()) + 4 * 2 == t.sent_tokens   # main call: 2 framed messages in the fake
    assert t.new_tokens == fake.count("The answer about quantization.") + fake.count(ex)
    assert s.state()["graph"]["nodes"][0]["label"] == "quantization"


def test_extract_off_means_no_extra_call(fake, cfg):
    s = Session("endless", fake, cfg)
    t = s.turn("hello")
    assert len(fake.calls) == 1 and t.graph_delta == {"added": [], "bumped": [], "edges": []}


def test_extract_failure_is_swallowed(fake, cfg):
    c = _replace(cfg, extract=True)
    fake.responses = ["ok", "not json at all"]
    t = Session("endless", fake, c).turn("hi")
    assert t.graph_delta["added"] == []


def test_compaction_survives_graph(fake, cfg):
    c = _replace(cfg, extract=True, window_tokens=80, compact_at=0.5)
    fake.responses = ["a1", '{"concepts": ["alpha", "beta"], "links": []}',
                      "summary mentions alpha only",                        # the compaction call
                      "a2", '{"concepts": ["gamma"], "links": []}']
    s = Session("compact", fake, c)
    s.turn("one two three four five six seven eight nine ten eleven twelve")
    t = s.turn("thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty")
    assert t.event == "compacted"
    assert t.graph_delta["survive"] == {"kept": [["alpha", 1]], "absorbed": [["beta", "alpha"]]}
    assert set(n["label"] for n in s.state()["graph"]["nodes"]) == {"alpha", "gamma"}


def test_handoff_seeds_graph_from_note(fake, cfg):
    c = _replace(cfg, extract=True)
    fake.responses = ["a1", '{"concepts": ["alpha", "beta"], "links": [["alpha","beta"]]}', "NOTE: alpha matters"]
    s = Session("handoff", fake, c); s.turn("x")
    h = s.handoff()
    assert h.graph_survive == {"kept": [["alpha", 1]], "absorbed": [["beta", "alpha"]]}
    assert [n["label"] for n in h.new_session.state()["graph"]["nodes"]] == ["alpha"]
    assert set(s.graph.nodes) == {"alpha", "beta"}          # old session untouched


class WordChunker:
    available = True
    def split(self, text): return text.split()


def test_peek_session_carries_pieces_and_chunks(fake, cfg):
    s = Session("endless", fake, cfg, peek=True, chunker=WordChunker())
    tr = s.turn("pick a number")
    assert [t["t"] for t in tr.tokens] == ["Echo:", "pick", "a", "number"]
    assert tr.user_chunks == ["pick", "a", "number"]
    assert fake.calls[-1]["peek"] is True


def test_only_answer_calls_peek(fake, cfg):
    s = Session("compact", fake, replace(cfg, extract=True), peek=True)      # window 400, compacts at 320
    for i in range(16):
        s.turn("tell me a long story about lighthouses and fog please")
    assert any(c["max_tokens"] == cfg.summary_max_tokens for c in fake.calls)      # it did compact at least once
    side = [c["peek"] for c in fake.calls if c["max_tokens"] in (cfg.summary_max_tokens, cfg.extract_max_tokens)]
    assert side and not any(side)                             # compaction + extraction never peek
    assert all(c["peek"] for c in fake.calls if c["max_tokens"] == cfg.answer_max_tokens)


def test_plain_session_is_untouched(fake, cfg):
    tr = Session("endless", fake, cfg).turn("hello")
    assert tr.tokens == [] and tr.user_chunks == [] and fake.calls[-1]["peek"] is False
