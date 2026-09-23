# layers/tests/test_engine.py
from layers.engine import Engine


class StubTok:
    def apply_chat_template(self, messages, tokenize=False, add_generation_prompt=True, enable_thinking=False):
        return "".join(f"<{m['role']}>{m['content']}" for m in messages) + "<assistant>"
    def encode(self, text, add_special_tokens=False): return [ord(c) for c in text]
    def decode(self, ids): return "".join(chr(i) for i in ids)
    def convert_ids_to_tokens(self, ids): return [chr(i) for i in ids]


class StubRunner:
    n_layers = 3
    tokenizer = StubTok()
    seen = None
    def forward(self, ids):
        StubRunner.seen = list(ids)
        tops = [[("a", 0.3), ("b", 0.2)], [("Yes", 0.5), ("a", 0.1)], [("Yes", 0.9), ("No", 0.05)]]
        attn = [[0.8, 0.1, 0.1] + [0.0] * (len(ids) - 3)] * 3
        return tops, attn


def make(): return Engine("stub/model", device="cpu", loader=lambda name, device: StubRunner())


def test_analyze_from_messages_applies_the_chat_template_and_the_prefix():
    r = make().analyze(messages=[{"role": "user", "content": "hi"}], prefix="Ye")
    assert r["model"] == "stub/model" and r["n_layers"] == 3
    assert "".join(r["tokens"]) == "<user>hi<assistant>Ye"                  # template + the answer so far
    assert r["final"] == {"t": "Yes", "p": 0.9}
    assert [l["n"] for l in r["layers"]] == [1, 2, 3] and r["layers"][1]["top"][0] == {"t": "Yes", "p": 0.5}
    assert r["decided_at"] == 2
    assert [a["layer"] for a in r["attention"]] == [1, 2, 3]                # early / decided / last (3 layers: all of them)
    assert r["attention"][0]["weights"][0] == 0.0 and max(r["attention"][0]["weights"]) == 1.0   # sink dropped, scaled
    assert r["cut"] is False


def test_analyze_from_a_raw_prompt_cuts_the_front():
    r = make().analyze(prompt="x" * 50, max_tokens=10)
    assert len(r["tokens"]) == 10 and r["cut"] is True and len(StubRunner.seen) == 10


def test_analyze_needs_messages_or_prompt():
    import pytest
    with pytest.raises(ValueError):
        make().analyze()


def test_analyze_attention_dedup_when_decided_at_equals_last():
    """Collision case: top-1 stabilises only at the last layer, so early and decided/last coincide."""
    class StubRunnerNoDecision:
        n_layers = 3
        tokenizer = StubTok()
        seen = None
        def forward(self, ids):
            StubRunnerNoDecision.seen = list(ids)
            tops = [[("a", 0.3), ("b", 0.2)], [("b", 0.4), ("a", 0.1)], [("Yes", 0.9), ("No", 0.05)]]
            attn = [[0.8, 0.1, 0.1] + [0.0] * (len(ids) - 3)] * 3
            return tops, attn
    engine = Engine("stub/no-decision", device="cpu", loader=lambda name, device: StubRunnerNoDecision())
    r = engine.analyze(messages=[{"role": "user", "content": "hi"}], prefix="X")
    assert r["decided_at"] == 3
    assert [a["layer"] for a in r["attention"]] == [1, 3]
