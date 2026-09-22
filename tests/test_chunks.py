from types import SimpleNamespace
from app.chunks import Chunker


class StubTok:
    """Splits on spaces the way the real tokenizer does: the space belongs to the word after it."""
    def encode(self, text, add_special_tokens=False):
        offs, start = [], 0
        for i, ch in enumerate(text):
            if ch == " " and i > start:
                offs.append((start, i)); start = i
        if text:
            offs.append((start, len(text)))
        return SimpleNamespace(offsets=offs)


def test_split_slices_the_original_text():
    c = Chunker("any/repo", loader=lambda repo: StubTok())
    assert c.split("the capital of") == ["the", " capital", " of"]
    assert c.split("") == [] and c.available is True


def test_split_collapses_repeated_offsets():
    tok = SimpleNamespace(encode=lambda text, add_special_tokens=False: SimpleNamespace(offsets=[(0, 1), (0, 1), (1, 3)]))
    assert Chunker("r", loader=lambda repo: tok).split("abc") == ["a", "bc"]


def test_no_repo_or_broken_loader_fails_soft():
    assert Chunker(None).split("hello") == [] and Chunker("").available is False
    def boom(repo): raise OSError("no network")
    c = Chunker("x/y", loader=boom)
    assert c.split("hello") == [] and c.available is False
    assert c.split("again") == []          # does not retry the load every turn
