"""Split a sentence into the pieces (tokens) the model actually reads — act 6, 'the chunks'.
Done locally with the model's own tokenizer file so it works the same on Ollama and vLLM. Fails soft: no repo,
no library or no network -> available False and split() == [] (the wall hides the strip)."""
from __future__ import annotations
import logging
log = logging.getLogger("uvicorn.error")


def _load(repo: str):
    from tokenizers import Tokenizer
    return Tokenizer.from_pretrained(repo)


class Chunker:
    def __init__(self, repo: str | None, loader=None):
        self.repo = repo or ""
        self._loader = loader or _load
        self._tok = None
        self.available = bool(self.repo)

    def use(self, repo: str | None) -> None:
        """Switch to another model's tokenizer (the model switch); loads lazily on the next split."""
        self.repo = repo or ""
        self._tok = None
        self.available = bool(self.repo)

    def split(self, text: str) -> list[str]:
        if not self.available or not text:
            return []
        try:
            if self._tok is None:
                self._tok = self._loader(self.repo)
            out, last = [], None
            for a, b in self._tok.encode(text, add_special_tokens=False).offsets:
                if (a, b) != last and b > a:        # a character split across pieces reports the same span twice
                    out.append(text[a:b])
                last = (a, b)
            return out
        except Exception as e:                       # the chunks must never break a turn
            log.warning("chunks unavailable (%s): %s: %s", self.repo, type(e).__name__, e)
            self.available = False
            return []
