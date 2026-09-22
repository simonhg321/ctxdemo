# ctxdemo "The guesses" (act 6) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show, as standalone wall panels, how the model splits a sentence into pieces and how sure it was about every piece of its answer (with what it almost said).

**Architecture:** The server adds an opt-in `peek` flag that asks the chat server for per-piece guess lists on the same `/v1/chat/completions` call it already makes (identical on Ollama and vLLM), and splits the user's sentence with a local tokenizer. The browser side is a set of tiny panels (one page, `?show=<name>`) that talk over an in-browser `BroadcastChannel` bus; only the `driver` panel talks to the server. Tab 6 and the wall page are just arrangements of those panels in iframes.

**Tech Stack:** Python 3.12 / FastAPI / httpx / pytest (existing); `tokenizers` (new, small); vanilla JS, no build step; `node --test` for the pure JS helpers (node 26 is installed; dev-only, not a runtime dependency).

**Spec:** `docs/specs/2026-09-21-ctxdemo-guesses-design.md` — read it first.

## Global Constraints

- Work in `/Users/project/iiat/ctxdemo`, branch `map`. Python tests: `.venv/bin/python -m pytest -q` (52 pass before you start; all must still pass after every task).
- **Acts 1–5 must not change behaviour.** With `peek=False` the request body sent to the chat server is byte-for-byte what it is today. Do not edit `static/map.js`. The only edits to `static/index.html` are in Task 7.
- The page is served behind Caddy at `/demo/` with the prefix stripped, so **every URL in the browser code is relative** — never start a path with `/`. From `static/peek/*.html` the API is `../../api/`.
- One Chrome instance, one machine: the bus is `BroadcastChannel`. No server relay, no websockets, no streaming.
- Wall wording: say "piece" and "guess", not "token" and "logprob" (the glossary line in tab 6 gives the real terms once).
- Colours come from the existing tokens: `--ground #0f1216`, `--panel #171c22`, `--line #262d36`, `--bone #e6e1d6`, `--dim #6b7480`, `--amber #f2a93b`, `--ice #7fc8e8`, `--red #e0553c`, `--moss #9bbf6a`. Sure = moss, unsure = amber, coin-flip = red.
- Thresholds: `p >= 0.9` sure, `0.5 <= p < 0.9` unsure, `p < 0.5` coin-flip. Top guesses kept: 5. Hesitations ringed: 3. Reveal capped at 8 s.
- Nothing in this plan raises into a turn: guesses and chunks fail soft to `[]`.
- Commit after each task with the message given. Do not push (no remote).

## File map

| File | Responsibility |
|---|---|
| `app/vllm.py` (modify) | `parse_logprobs`, `ChatResult.tokens`, `chat(..., peek=False)` |
| `app/chunks.py` (create) | `Chunker`: split text into the model's pieces, fail soft |
| `app/config.py` (modify) | `tokenizer_repo` + env `CTXDEMO_TOKENIZER` |
| `app/session.py` (modify) | `Session(peek=, chunker=)`, `TurnResult.tokens`, `TurnResult.user_chunks` |
| `app/main.py` (modify) | `NewSession.peek`, build the `Chunker`, `/api/health` → `chunks` |
| `tests/conftest.py` (modify) | `FakeVLLM.chat(..., peek=False)` + canned pieces |
| `tests/test_vllm.py`, `tests/test_session.py`, `tests/test_api.py` (modify), `tests/test_chunks.py` (create) | tests |
| `requirements.txt`, `Dockerfile`, `run-typhoon.sh`, `docker-compose.yaml` (modify) | dependency + tokenizer env |
| `static/peek/lib.js` (create) | pure helpers (tone, pct, hesitations, stats, revealDelay) — browser + node |
| `static/peek/lib.test.mjs` (create) | `node --test` for lib.js |
| `static/peek/bus.js` (create) | `window.peekBus` |
| `static/peek/panel.html` (create) | the one page: loads a panel by `?show=`, replay, auto-select |
| `static/peek/peek.css` (create) | shared panel styles |
| `static/peek/{chunks,answer,almost,tiles,driver}.js` (create) | one panel each |
| `static/peek/replay.json` (create) | three canned turns (hand-made in Task 4, replaced by a real capture in Task 8) |
| `static/peek/wall.html` (create) | arrangement of panels from `?layout=` |
| `static/index.html` (modify) | nav button 6 + section of iframes |
| `README.md` (modify) | short "Act 6" section |

---

### Task 1: The guess list from the chat server

**Files:**
- Modify: `app/vllm.py`
- Test: `tests/test_vllm.py`

**Interfaces:**
- Produces: `parse_logprobs(choice: dict) -> list[dict]` where each item is `{"t": str, "p": float, "alts": [{"t": str, "p": float}, ...]}` (`p` in 0–1, 4 decimals; `alts` sorted high→low, max 5, always contains the chosen piece). `ChatResult.tokens: list[dict]` (default `[]`). `VLLM.chat(messages, max_tokens, tools=None, peek=False)`.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_vllm.py`:

```python
from app.vllm import parse_logprobs

OLLAMA_CHOICE = {"message": {"content": "Hi there"}, "logprobs": {"content": [
    {"token": "Hi", "logprob": -0.32893359661102295, "bytes": [72, 105], "top_logprobs": [
        {"token": "Hi", "logprob": -0.32893359661102295, "bytes": [72, 105]},
        {"token": "Hello", "logprob": -1.271865725517273, "bytes": [72, 101, 108, 108, 111]}]},
    {"token": " there", "logprob": -4.768372718899627e-07, "bytes": [32, 116, 104, 101, 114, 101], "top_logprobs": [
        {"token": " there", "logprob": -4.768372718899627e-07, "bytes": [32, 116, 104, 101, 114, 101]},
        {"token": " هناك", "logprob": -15.563672065734863, "bytes": [32, 217, 135, 217, 134, 216, 167, 217, 131]}]}]}}


def test_parse_logprobs_real_ollama_shape():
    toks = parse_logprobs(OLLAMA_CHOICE)
    assert [t["t"] for t in toks] == ["Hi", " there"]
    assert toks[0]["p"] == 0.7197 and toks[0]["alts"] == [{"t": "Hi", "p": 0.7197}, {"t": "Hello", "p": 0.2803}]
    assert toks[1]["p"] == 1.0 and toks[1]["alts"][1]["t"] == " هناك"


def test_parse_logprobs_is_tolerant():
    assert parse_logprobs({}) == [] and parse_logprobs({"logprobs": None}) == [] and parse_logprobs(None) == []
    assert parse_logprobs({"logprobs": {"content": "garbage"}}) == []
    # half a UTF-8 character must not crash; no bytes -> falls back to the token string
    half = {"logprobs": {"content": [{"token": "x", "logprob": -0.1, "bytes": [240, 159], "top_logprobs": []},
                                     {"token": "plain", "logprob": -0.2}]}}
    toks = parse_logprobs(half)
    assert toks[0]["t"] == "�" and toks[1]["t"] == "plain"
    # the chosen piece is always in alts, even if the server left it out
    assert toks[0]["alts"] == [{"t": "�", "p": 0.9048}]


def test_peek_adds_fields_and_default_body_is_unchanged():
    bodies = []
    def handler(req: httpx.Request):
        bodies.append(json.loads(req.content))
        return httpx.Response(200, json={"choices": [OLLAMA_CHOICE], "usage": {"prompt_tokens": 3, "completion_tokens": 2}})
    v = VLLM("http://x", "m", transport=httpx.MockTransport(handler))
    plain = v.chat([{"role": "user", "content": "hello"}], max_tokens=5)
    peeked = v.chat([{"role": "user", "content": "hello"}], max_tokens=5, peek=True)
    assert bodies[0] == {"model": "m", "messages": [{"role": "user", "content": "hello"}], "max_tokens": 5,
                         "temperature": 0, "chat_template_kwargs": {"enable_thinking": False}}
    assert bodies[1]["logprobs"] is True and bodies[1]["top_logprobs"] == 5
    assert plain.tokens == [] and [t["t"] for t in peeked.tokens] == ["Hi", " there"]
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_vllm.py -q`
Expected: FAIL — `ImportError: cannot import name 'parse_logprobs'`.

- [ ] **Step 3: Implement** — in `app/vllm.py`:

Change the import line to `import json, math, time`. Add a field to `ChatResult` after `tool_calls`:

```python
    tokens: list[dict] = field(default_factory=list)       # peek only: {t, p, alts:[{t, p}]} per generated piece
```

Add below `estimate()`:

```python
TOP_GUESSES = 5


def _piece(it: dict) -> str:
    """Text of one piece. Prefer the raw bytes: a piece can be half a character, and must not crash the wall."""
    b = it.get("bytes")
    if isinstance(b, list) and b:
        return bytes(b).decode("utf-8", errors="replace")
    return str(it.get("token", ""))


def _prob(it: dict) -> float:
    return round(math.exp(min(0.0, float(it.get("logprob", 0.0)))), 4)


def parse_logprobs(choice: dict | None) -> list[dict]:
    """OpenAI-format logprobs (same from Ollama and vLLM) -> [{t, p, alts}]. Never raises; anything odd -> []."""
    try:
        out = []
        for it in ((choice or {}).get("logprobs") or {}).get("content") or []:
            me = {"t": _piece(it), "p": _prob(it)}
            alts = [{"t": _piece(a), "p": _prob(a)} for a in (it.get("top_logprobs") or [])]
            if me not in alts:
                alts.append(me)
            alts.sort(key=lambda a: -a["p"])
            out.append({**me, "alts": alts[:TOP_GUESSES]})
        return out
    except Exception:
        return []
```

In `_chat`, keep the choice and fill `tokens` (parsing an absent field gives `[]`):

```python
        j = r.json()
        choice = j["choices"][0]
        msg = choice["message"]
        u = j.get("usage") or {}
        return ChatResult(text=(text_of(msg.get("content"))).strip(),
                          prompt_tokens=int(u.get("prompt_tokens", 0)), completion_tokens=int(u.get("completion_tokens", 0)),
                          seconds=time.time() - t0, tool_calls=list(msg.get("tool_calls") or []),
                          tokens=parse_logprobs(choice))
```

Replace `chat`:

```python
    def chat(self, messages: list[dict], max_tokens: int, tools: list[dict] | None = None, peek: bool = False) -> ChatResult:
        body = {"model": self.model, "messages": messages, "max_tokens": max_tokens, "temperature": 0,
                "chat_template_kwargs": {"enable_thinking": False}}
        if tools:
            body["tools"] = tools
        if peek:                                   # ask for the ranked guesses behind every piece (act 6)
            body["logprobs"], body["top_logprobs"] = True, TOP_GUESSES
        return self._chat(body)
```

- [ ] **Step 4: Run the whole suite**

Run: `.venv/bin/python -m pytest -q`
Expected: 55 passed.

- [ ] **Step 5: Commit**

```bash
git add app/vllm.py tests/test_vllm.py
git commit -m "guesses: opt-in peek on the chat call returns the ranked guesses per piece"
```

---

### Task 2: The chunker

**Files:**
- Create: `app/chunks.py`, `tests/test_chunks.py`
- Modify: `app/config.py`, `requirements.txt`, `Dockerfile`, `run-typhoon.sh`, `docker-compose.yaml`

**Interfaces:**
- Produces: `Chunker(repo: str | None, loader=None)` with `.split(text: str) -> list[str]` and `.available: bool`. `loader(repo)` returns an object whose `.encode(text, add_special_tokens=False).offsets` is a list of `(start, end)` character offsets (that is the `tokenizers.Tokenizer` API). `Config.tokenizer_repo: str = ""`.

- [ ] **Step 1: Write the failing tests** — create `tests/test_chunks.py`:

```python
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
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_chunks.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.chunks'`.

- [ ] **Step 3: Implement** — create `app/chunks.py`:

```python
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
```

In `app/config.py`, add a field after `extract_max_tokens`:

```python
    tokenizer_repo: str = ""             # act 6 chunks: HF repo whose tokenizer matches the chat model; empty = strip hidden
```

and in `load()`, before `url = ...`:

```python
    if os.environ.get("CTXDEMO_TOKENIZER"):
        demo["tokenizer_repo"] = os.environ["CTXDEMO_TOKENIZER"]
```

`requirements.txt` — add a line: `tokenizers==0.22.*` (then run `.venv/bin/pip install -r requirements.txt`; if pip reports no matching 0.22 release, use the newest `0.2x.*` it offers and write that in the file).

`Dockerfile` — after the `pip install` line add (bakes the box's tokenizer in at build, so the container needs no internet at run time; failure here must not fail the build):

```dockerfile
ENV HF_HOME=/srv/hf
RUN python -c "from tokenizers import Tokenizer; Tokenizer.from_pretrained('Qwen/Qwen3-8B')" || echo "tokenizer prefetch failed; chunks strip will be hidden"
```

`run-typhoon.sh` — add after the `VISION_MODEL` line:

```bash
export CTXDEMO_TOKENIZER=Qwen/Qwen2.5-14B-Instruct   # act 6 chunks: same pieces the chat model reads
```

`docker-compose.yaml` — in the `ctxdemo` service `environment:` list add `- CTXDEMO_TOKENIZER=Qwen/Qwen3-8B` and `- HF_HUB_OFFLINE=1`, matching the existing list style.

- [ ] **Step 4: Run tests, then check the real tokenizer once**

Run: `.venv/bin/python -m pytest -q` → Expected: 58 passed.
Run: `.venv/bin/python -c "from app.chunks import Chunker; print(Chunker('Qwen/Qwen2.5-14B-Instruct').split(\"What's the capital of Australia?\"))"`
Expected: `['What', "'s", ' the', ' capital', ' of', ' Australia', '?']`

- [ ] **Step 5: Commit**

```bash
git add app/chunks.py app/config.py tests/test_chunks.py requirements.txt Dockerfile run-typhoon.sh docker-compose.yaml
git commit -m "chunks: split a sentence into the model's pieces with its own tokenizer; fails soft"
```

---

### Task 3: Wire peek and chunks through a turn

**Files:**
- Modify: `app/session.py`, `app/main.py`, `tests/conftest.py`
- Test: `tests/test_session.py`, `tests/test_api.py`

**Interfaces:**
- Consumes: `VLLM.chat(..., peek=)`, `ChatResult.tokens`, `Chunker.split`, `Chunker.available`, `Config.tokenizer_repo`.
- Produces: `Session(..., peek: bool = False, chunker=None)`; `TurnResult.tokens: list[dict]`, `TurnResult.user_chunks: list[str]`; `POST /api/session` accepts `peek: bool`; `GET /api/health` returns `"chunks": bool`. `create_app(..., chunker=None)`.

- [ ] **Step 1: Teach the fake** — in `tests/conftest.py` replace `FakeVLLM.chat` with:

```python
    def chat(self, messages, max_tokens, tools=None, peek=False):
        self.calls.append({"messages": [dict(m) for m in messages], "max_tokens": max_tokens, "tools": tools, "peek": peek})
        nxt = self.responses.pop(0) if self.responses else "Echo: " + text_of(messages[-1].get("content"))
        if isinstance(nxt, ChatResult):
            nxt.prompt_tokens = self.count_messages(messages); return nxt
        toks = [{"t": w, "p": 0.9, "alts": [{"t": w, "p": 0.9}]} for w in nxt.split()] if peek else []
        return ChatResult(text=nxt, prompt_tokens=self.count_messages(messages),
                          completion_tokens=self.count(nxt), seconds=0.01, tokens=toks)
```

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_session.py` (it already imports `Session`; add `from dataclasses import replace` and `from app.chunks import Chunker` at the top if missing):

```python
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
```

Append to `tests/test_api.py`:

```python
def test_peek_turn_and_health_chunks(fake, cfg):
    class WordChunker:
        available = True
        def split(self, text): return text.split()
    c = TestClient(create_app(vllm=fake, cfg=cfg, chunker=WordChunker()))
    assert c.get("/api/health").json()["chunks"] is True
    sid = c.post("/api/session", json={"mode": "compact", "board": True, "peek": True}).json()["session_id"]
    t = c.post("/api/turn", json={"session_id": sid, "text": "hi there"}).json()["turn"]
    assert t["user_chunks"] == ["hi", "there"] and t["tokens"][0]["alts"][0]["p"] == 0.9
    sid2 = c.post("/api/session", json={"mode": "endless"}).json()["session_id"]
    assert c.post("/api/turn", json={"session_id": sid2, "text": "hi"}).json()["turn"]["tokens"] == []


def test_health_chunks_false_without_a_tokenizer(client):
    assert client.get("/api/health").json()["chunks"] is False
```

- [ ] **Step 3: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_session.py tests/test_api.py -q`
Expected: FAIL — `TypeError: Session.__init__() got an unexpected keyword argument 'peek'` and `create_app() got an unexpected keyword argument 'chunker'`.

- [ ] **Step 4: Implement**

`app/session.py` — `TurnResult`, after `graph_delta`:

```python
    tokens: list[dict] = field(default_factory=list)        # act 6: {t, p, alts} per piece of the answer (peek sessions only)
    user_chunks: list[str] = field(default_factory=list)    # act 6: the user's sentence split into the model's pieces
```

`Session.__init__` signature and two new attributes:

```python
    def __init__(self, mode: Mode, vllm, cfg: Config, system_prompt: str = SYSTEM,
                 memory: tuple[str, str] | None = None, carried: tuple[int, int, int] = (0, 0, 0),
                 tools=None, peek: bool = False, chunker=None):
```
```python
        self.peek = peek                          # act 6: ask for the guesses behind the answer
        self.chunker = chunker                    # act 6: splits the user's sentence into pieces, or None
```

In `turn()`: both answer calls become `self.vllm.chat(self.messages, self.cfg.answer_max_tokens, tools=tools, **self._peek_kw())` and add the helper next to `_cost`:

```python
    def _peek_kw(self) -> dict:
        return {"peek": True} if self.peek else {}      # plain sessions call chat() exactly as before
```

In the final `TurnResult(...)` of `turn()` add:

```python
                        tokens=r.tokens if self.peek else [],
                        user_chunks=self.chunker.split(user_text) if (self.peek and self.chunker) else [],
```

In `handoff()`, pass them on: `tools=self.tools, peek=self.peek, chunker=self.chunker)`.

Note: `FakeVLLM.chat` records `peek` from its default, so `fake.calls[-1]["peek"] is False` holds for plain sessions.

`app/main.py`:
- import: `from .chunks import Chunker`
- `NewSession` gains `peek: bool = False           # act 6: return the guesses behind each piece of the answer`
- `def create_app(vllm=None, cfg=None, vision=None, tools=None, ears=None, chunker=None) -> FastAPI:` and, after `tools = tools or Tools()`: `chunker = chunker or Chunker(cfg.tokenizer_repo)`
- `/api/health` dict gains `"chunks": bool(getattr(chunker, "available", False)),`
- in `new_session`, the `Session(...)` call gains `peek=req.peek, chunker=chunker`.

- [ ] **Step 5: Run the whole suite**

Run: `.venv/bin/python -m pytest -q`
Expected: 63 passed.

- [ ] **Step 6: Commit**

```bash
git add app/session.py app/main.py tests/conftest.py tests/test_session.py tests/test_api.py
git commit -m "guesses: peek sessions carry the answer's pieces and the user's chunks through /api/turn"
```

---

### Task 4: Panel runtime — helpers, bus, the one page, replay

**Files:**
- Create: `static/peek/lib.js`, `static/peek/lib.test.mjs`, `static/peek/bus.js`, `static/peek/peek.css`, `static/peek/panel.html`, `static/peek/replay.json`

**Interfaces:**
- Produces (browser globals):
  - `peekLib = {tone(p) -> 'sure'|'unsure'|'flip', pct(p) -> '72%', isBlank(t) -> bool, hesitations(tokens, k=3) -> number[], stats(tokens) -> {sure_pct: number, worst: {i, chosen, runner}|null}, revealDelay(seconds, n) -> ms}`
  - `peekBus = {join(room), send(type, data), on(type, fn), last(type)}` — `send` also calls local handlers (BroadcastChannel does not echo to the sender).
  - `peekPanels[name] = {mount(el), onTurn(msg), onSelect(i)}` — each panel file registers itself here. `msg = {turn, state}` exactly as `/api/turn` returns it.
  - Bus message types: `turn`, `select` (`{index}`), `clear`, `hello`.

- [ ] **Step 1: Write the failing helper tests** — create `static/peek/lib.test.mjs`:

```js
import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
const L = createRequire(import.meta.url)('./lib.js');

const T = (t, p, runner) => ({ t, p, alts: runner ? [{ t, p }, { t: runner, p: 1 - p }] : [{ t, p }] });

test('tone thresholds', () => {
  assert.equal(L.tone(0.9), 'sure'); assert.equal(L.tone(0.89), 'unsure');
  assert.equal(L.tone(0.5), 'unsure'); assert.equal(L.tone(0.49), 'flip');
});
test('pct', () => { assert.equal(L.pct(0.7197), '72%'); assert.equal(L.pct(0.0004), '<1%'); assert.equal(L.pct(1), '100%'); });
test('hesitations: lowest first, skips blank pieces', () => {
  const toks = [T('A', 0.99), T(' ', 0.1), T('B', 0.4, 'C'), T('D', 0.6, 'E'), T('\n', 0.2), T('F', 0.95)];
  assert.deepEqual(L.hesitations(toks, 2), [2, 3]);
  assert.deepEqual(L.hesitations([], 3), []);
});
test('stats', () => {
  const s = L.stats([T('A', 0.99), T('B', 0.4, 'C'), T('D', 0.95)]);
  assert.equal(s.sure_pct, 67); assert.deepEqual(s.worst, { i: 1, chosen: 'B', runner: 'C' });
  assert.deepEqual(L.stats([]), { sure_pct: 0, worst: null });
});
test('revealDelay: real pace, capped at 8 s total, floor 15 ms', () => {
  assert.equal(L.revealDelay(2, 40), 50); assert.equal(L.revealDelay(30, 100), 80); assert.equal(L.revealDelay(0.01, 100), 15);
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `node --test static/peek/`
Expected: FAIL — `Cannot find module './lib.js'`.

- [ ] **Step 3: Implement `static/peek/lib.js`**

```js
// Pure helpers for the act-6 panels. Loaded by <script> in the browser (window.peekLib) and by node for tests.
(function (root) {
  const tone = p => (p >= 0.9 ? 'sure' : p >= 0.5 ? 'unsure' : 'flip');
  const pct = p => (p > 0 && p < 0.005 ? '<1%' : Math.round(p * 100) + '%');
  const isBlank = t => !String(t || '').trim();
  function hesitations(tokens, k = 3) {
    return (tokens || []).map((t, i) => ({ i, p: t.p, t: t.t })).filter(x => !isBlank(x.t))
      .sort((a, b) => a.p - b.p || a.i - b.i).slice(0, k).map(x => x.i).sort((a, b) => a - b);
  }
  function stats(tokens) {
    const real = (tokens || []).map((t, i) => ({ ...t, i })).filter(t => !isBlank(t.t));
    if (!real.length) return { sure_pct: 0, worst: null };
    const w = real.reduce((a, b) => (b.p < a.p ? b : a));
    const runner = (w.alts || []).find(a => a.t !== w.t);
    return { sure_pct: Math.round(100 * real.filter(t => t.p >= 0.9).length / real.length),
             worst: { i: w.i, chosen: w.t, runner: runner ? runner.t : null } };
  }
  const revealDelay = (seconds, n) => Math.max(15, Math.round(Math.min(seconds, 8) * 1000 / Math.max(1, n)));
  const api = { tone, pct, isBlank, hesitations, stats, revealDelay };
  if (typeof module !== 'undefined' && module.exports) module.exports = api; else root.peekLib = api;
})(typeof window !== 'undefined' ? window : globalThis);
```

Note `hesitations(toks, 2)` in the test returns `[2, 3]`: lowest two by `p` are index 2 (0.4) and 3 (0.6), returned in reading order.

- [ ] **Step 4: Run helper tests**

Run: `node --test static/peek/`
Expected: 5 pass, 0 fail.

- [ ] **Step 5: Create `static/peek/bus.js`**

```js
// The bus: panels in separate windows/iframes of ONE Chrome talk over BroadcastChannel. No server involved.
(function () {
  const handlers = {}, cache = {};
  let ch = null;
  function deliver(msg) {
    if (!msg || msg.v !== 1) return;
    cache[msg.type] = msg.data;
    (handlers[msg.type] || []).forEach(fn => { try { fn(msg.data); } catch (e) { console.error('peek panel', e); } });
  }
  window.peekBus = {
    join(room) { ch = new BroadcastChannel('ctxdemo-peek-' + (room || 'wall')); ch.onmessage = e => deliver(e.data); },
    send(type, data) { const msg = { v: 1, type, data }; deliver(msg); if (ch) ch.postMessage(msg); },   // BroadcastChannel never echoes to the sender
    on(type, fn) { (handlers[type] = handlers[type] || []).push(fn); },
    last(type) { return cache[type]; },
  };
})();
```

- [ ] **Step 6: Create `static/peek/peek.css`**

```css
:root { --ground: #0f1216; --panel: #171c22; --line: #262d36; --bone: #e6e1d6; --dim: #6b7480; --amber: #f2a93b; --ice: #7fc8e8; --red: #e0553c; --moss: #9bbf6a;
  --u: clamp(12px, calc(1.1vw + 1.1vh), 40px); }   /* one unit that grows with the frame, so resizing a window rescales the panel */
* { box-sizing: border-box; }
html, body { height: 100%; margin: 0; }
body { background: var(--ground); color: var(--bone); font: var(--u)/1.45 "Helvetica Neue", "Segoe UI", system-ui, sans-serif; font-variant-numeric: tabular-nums; overflow: hidden; }
#panel { height: 100%; padding: calc(var(--u) * .8); display: flex; flex-direction: column; gap: calc(var(--u) * .5); overflow: hidden; }
.cap { color: var(--dim); font-size: .7em; letter-spacing: .06em; text-transform: uppercase; }
.dim { color: var(--dim); }
.piece { border-radius: .2em; padding: .05em 0; cursor: pointer; white-space: pre-wrap; border-bottom: .12em solid transparent; }
.piece.sure { border-bottom-color: var(--moss); }
.piece.unsure { border-bottom-color: var(--amber); background: rgba(242,169,59,.14); }
.piece.flip { border-bottom-color: var(--red); background: rgba(224,85,60,.22); }
.piece.ring { outline: .1em solid var(--ice); outline-offset: .1em; }
.piece.focus { outline: .14em solid var(--bone); outline-offset: .1em; }
.chunk { white-space: pre-wrap; border-radius: .2em; padding: .1em .05em; }
.chunk:nth-child(odd) { background: rgba(127,200,232,.20); }
.chunk:nth-child(even) { background: rgba(155,191,106,.20); }
.bar-row { display: grid; grid-template-columns: minmax(4em, 38%) 1fr 3.2em; gap: .6em; align-items: center; }
.bar-row .w { white-space: pre; overflow: hidden; text-overflow: ellipsis; text-align: right; }
.bar-row .b { height: 1.1em; background: var(--line); border-radius: .2em; overflow: hidden; }
.bar-row .b i { display: block; height: 100%; background: var(--dim); transition: width 500ms; }
.bar-row.chosen .b i { background: var(--moss); } .bar-row.chosen .w { font-weight: 600; }
.tile { border: 1px solid var(--line); background: var(--panel); border-radius: .3em; padding: .5em .7em; }
.tile .big { font-size: 1.9em; font-weight: 600; line-height: 1.1; }
button, input[type=text] { font: inherit; color: var(--bone); background: var(--panel); border: 1px solid var(--line); border-radius: .25em; padding: .4em .7em; }
button { cursor: pointer; } button:hover { border-color: var(--dim); } button:disabled { opacity: .4; }
input[type=text] { width: 100%; }
```

- [ ] **Step 7: Create `static/peek/panel.html`**

```html
<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>ctxdemo panel</title><link rel="stylesheet" href="peek.css"></head>
<body><div id="panel"></div>
<script src="lib.js"></script><script src="bus.js"></script>
<script>
  // One page, many panels:  panel.html?show=answer&room=wall   (&replay=1 plays replay.json with no model, &bg=, &scale=)
  window.peekPanels = {};
  const q = new URLSearchParams(location.search);
  const show = (q.get('show') || 'answer').replace(/[^a-z]/g, ''), room = q.get('room') || 'wall';
  const selfReplay = q.get('replay') === '1' && show !== 'driver';     // the driver replays for everyone; any other panel replays alone
  if (q.get('bg')) document.body.style.background = q.get('bg');
  if (q.get('scale')) document.documentElement.style.setProperty('--u', `calc(${parseFloat(q.get('scale')) || 1} * clamp(12px, calc(1.1vw + 1.1vh), 40px))`);
  document.title = 'ctxdemo · ' + show;

  let cycle = null;
  function stopCycle() { clearInterval(cycle); cycle = null; }
  window.peekStopCycle = stopCycle;
  // After a turn, walk the focus through the least-sure pieces so an unattended wall still teaches.
  function autoSelect(msg, pick) {
    stopCycle();
    const toks = (msg.turn && msg.turn.tokens) || [], hs = peekLib.hesitations(toks, 3);
    if (!hs.length) return;
    const wait = peekLib.revealDelay(msg.turn.seconds || 2, toks.length) * toks.length + 600;
    let k = 0;
    setTimeout(() => { pick(hs[0]); cycle = setInterval(() => pick(hs[++k % hs.length]), 4000); }, wait);
  }

  const s = document.createElement('script');
  s.src = show + '.js';
  s.onerror = () => { document.getElementById('panel').textContent = 'no such panel: ' + show; };
  s.onload = async () => {
    const p = peekPanels[show]; if (!p) return;
    p.mount(document.getElementById('panel'));
    if (selfReplay) {                                  // alone, no bus: for arranging the wall
      const rp = await (await fetch('replay.json')).json(); let i = 0;
      const play = () => { const msg = rp.turns[i++ % rp.turns.length]; p.onTurn(msg); autoSelect(msg, n => p.onSelect && p.onSelect(n)); };
      play(); setInterval(play, 16000); return;
    }
    peekBus.join(room);
    peekBus.on('turn', msg => { p.onTurn(msg); if (show === 'answer') autoSelect(msg, n => peekBus.send('select', { index: n })); });
    peekBus.on('select', d => p.onSelect && p.onSelect(d.index));
    peekBus.on('clear', () => { stopCycle(); p.onTurn({ turn: null, state: null }); });
    if (show !== 'driver') peekBus.send('hello', {});   // late joiner: ask the driver to repeat the last turn
  };
  document.body.appendChild(s);
</script></body></html>
```

- [ ] **Step 8: Create a hand-made `static/peek/replay.json`** (Task 8 replaces it with a real capture; the shape is exactly `/api/turn`'s, trimmed to the fields panels read)

```json
{"turns": [
 {"turn": {"n": 1, "user": "Say hi", "answer": "Hi there!", "seconds": 1.2, "event": null, "event_text": null,
   "user_chunks": ["Say", " hi"],
   "tokens": [{"t": "Hi", "p": 0.7197, "alts": [{"t": "Hi", "p": 0.7197}, {"t": "Hello", "p": 0.2803}]},
              {"t": " there", "p": 1.0, "alts": [{"t": " there", "p": 1.0}, {"t": " هناك", "p": 0.0}]},
              {"t": "!", "p": 1.0, "alts": [{"t": "!", "p": 1.0}, {"t": "!\n", "p": 0.0}]}]},
  "state": {"window_tokens": 4096, "next_would_send": 48}},
 {"turn": {"n": 2, "user": "The Eiffel Tower is in the city of", "answer": "Paris, France.", "seconds": 1.6, "event": null, "event_text": null,
   "user_chunks": ["The", " E", "iff", "el", " Tower", " is", " in", " the", " city", " of"],
   "tokens": [{"t": "Paris", "p": 0.94, "alts": [{"t": "Paris", "p": 0.94}, {"t": "The", "p": 0.04}, {"t": "巴黎", "p": 0.01}]},
              {"t": ",", "p": 0.62, "alts": [{"t": ",", "p": 0.62}, {"t": ".", "p": 0.37}]},
              {"t": " France", "p": 0.97, "alts": [{"t": " France", "p": 0.97}, {"t": " the", "p": 0.02}]},
              {"t": ".", "p": 0.99, "alts": [{"t": ".", "p": 0.99}, {"t": "!", "p": 0.01}]}]},
  "state": {"window_tokens": 4096, "next_would_send": 96}},
 {"turn": {"n": 3, "user": "Pick a number between 1 and 10", "answer": "7", "seconds": 0.9, "event": null, "event_text": null,
   "user_chunks": ["Pick", " a", " number", " between", " ", "1", " and", " ", "1", "0"],
   "tokens": [{"t": "7", "p": 0.41, "alts": [{"t": "7", "p": 0.41}, {"t": "5", "p": 0.22}, {"t": "3", "p": 0.17}, {"t": "4", "p": 0.11}, {"t": "8", "p": 0.06}]}]},
  "state": {"window_tokens": 4096, "next_would_send": 131}}
]}
```

- [ ] **Step 9: Smoke the runtime** — start the app (`VLLM_URL=http://127.0.0.1:9 CTXDEMO_EXTRACT=0 .venv/bin/uvicorn app.main:app --port 8200 &`), then:

Run: `curl -s -o /dev/null -w "%{http_code}\n" "http://127.0.0.1:8200/static/peek/panel.html?show=nope"`
Expected: `200` (and in a browser that URL shows "no such panel: nope"). Stop the app (`kill %1`).

- [ ] **Step 10: Commit**

```bash
git add static/peek
git commit -m "peek panels: shared helpers (node-tested), BroadcastChannel bus, one-page panel runtime with self-replay"
```

---

### Task 5: The four display panels

**Files:**
- Create: `static/peek/chunks.js`, `static/peek/answer.js`, `static/peek/almost.js`, `static/peek/tiles.js`

**Interfaces:**
- Consumes: `peekLib`, `peekBus`, `peekPanels`, `window.peekStopCycle`, message shape `{turn, state}` (either may be `null` on `clear`).
- Produces: `peekPanels.chunks`, `.answer`, `.almost`, `.tiles`. `answer` sends `select {index}` on tap.

- [ ] **Step 1: `static/peek/chunks.js`**

```js
// "The chunks": the student's sentence cut into the pieces the model actually reads.
peekPanels.chunks = (function () {
  let el;
  const esc = s => s.replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));
  return {
    mount(root) { el = root; el.innerHTML = '<div class="cap">what the model reads</div><div id="strip" class="dim">ask something…</div><div id="count" class="dim"></div>'; },
    onTurn(msg) {
      const t = msg && msg.turn, strip = el.querySelector('#strip'), count = el.querySelector('#count');
      if (!t) { strip.textContent = 'ask something…'; strip.className = 'dim'; count.textContent = ''; return; }
      const ch = t.user_chunks || [];
      strip.className = '';
      if (!ch.length) { strip.textContent = t.user; count.textContent = ''; return; }     // no tokenizer on this server: show the sentence plain
      strip.innerHTML = ch.map(c => `<span class="chunk">${esc(c)}</span>`).join('');
      const words = t.user.trim().split(/\s+/).length;
      count.textContent = `${words} word${words === 1 ? '' : 's'} → ${ch.length} pieces`;
    },
  };
})();
```

- [ ] **Step 2: `static/peek/answer.js`**

```js
// "The answer": revealed piece by piece at the speed it was really generated, coloured by how sure the model was.
peekPanels.answer = (function () {
  let el, timer = null, toks = [];
  function paint(i) {
    el.querySelectorAll('.piece').forEach(s => s.classList.toggle('focus', +s.dataset.i === i));
  }
  return {
    mount(root) {
      el = root;
      el.innerHTML = '<div class="cap">the answer · <span style="color:var(--moss)">sure</span> · <span style="color:var(--amber)">unsure</span> · <span style="color:var(--red)">coin-flip</span></div><div id="out" class="dim">…</div>';
      el.addEventListener('click', e => {
        const s = e.target.closest('.piece'); if (!s) return;
        window.peekStopCycle && window.peekStopCycle();            // a person took over: stop the automatic tour
        const alone = new URLSearchParams(location.search).get('replay') === '1';   // self-replay: no bus joined
        if (alone) paint(+s.dataset.i); else peekBus.send('select', { index: +s.dataset.i });
      });
    },
    onTurn(msg) {
      clearInterval(timer);
      const out = el.querySelector('#out'), t = msg && msg.turn;
      out.className = ''; out.innerHTML = '';
      if (!t) { out.className = 'dim'; out.textContent = '…'; return; }
      toks = t.tokens || [];
      if (!toks.length) { out.textContent = t.answer || t.event_text || ''; return; }       // non-peek turn or over-limit: plain text
      let i = 0;
      const ring = new Set(peekLib.hesitations(toks, 3));
      timer = setInterval(() => {
        if (i >= toks.length) { clearInterval(timer); out.querySelectorAll('.piece').forEach(s => ring.has(+s.dataset.i) && s.classList.add('ring')); return; }
        const s = document.createElement('span');
        s.className = 'piece ' + peekLib.tone(toks[i].p); s.dataset.i = i; s.textContent = toks[i].t;
        out.appendChild(s); i++;
      }, peekLib.revealDelay(t.seconds || 2, toks.length));
    },
    onSelect(i) { paint(i); },
  };
})();
```

- [ ] **Step 3: `static/peek/almost.js`**

```js
// "What it almost said": the ranked guesses behind the piece in focus.
peekPanels.almost = (function () {
  let el, toks = [], sawForeign = false;
  const vis = t => t.replace(/ /g, '␣').replace(/\n/g, '⏎');                       // make spaces and newlines visible
  const foreign = t => /[^\u0000-ɏ -⁯]/.test(t);                    // outside Latin + punctuation
  return {
    mount(root) { el = root; el.innerHTML = '<div class="cap">what it almost said</div><div id="rows" class="dim">tap a piece of the answer</div><div id="note" class="dim" style="font-size:.75em"></div>'; },
    onTurn(msg) { toks = (msg && msg.turn && msg.turn.tokens) || []; el.querySelector('#rows').innerHTML = '<span class="dim">…</span>'; },
    onSelect(i) {
      const t = toks[i]; if (!t) return;
      el.querySelector('#rows').innerHTML = t.alts.map(a =>
        `<div class="bar-row${a.t === t.t ? ' chosen' : ''}"><span class="w"></span><span class="b"><i style="width:${Math.max(1, a.p * 100)}%"></i></span><span>${peekLib.pct(a.p)}</span></div>`).join('');
      el.querySelectorAll('.bar-row .w').forEach((w, k) => { w.textContent = vis(t.alts[k].t); });
      if (!sawForeign && t.alts.some(a => foreign(a.t))) {
        sawForeign = true;
        el.querySelector('#note').textContent = 'Guesses in other languages are real: the model learned many languages at once, and they all compete for every piece.';
      }
    },
  };
})();
```

- [ ] **Step 4: `static/peek/tiles.js`**

```js
// Three numbers: how sure, the biggest hesitation, how full the backpack is.
peekPanels.tiles = (function () {
  let el;
  const vis = t => (t == null ? '—' : '“' + t.trim() + '”');
  return {
    mount(root) {
      el = root;
      el.innerHTML = ['sure', 'worst', 'pack'].map(k => `<div class="tile"><div class="cap" id="${k}-cap"></div><div class="big" id="${k}-big">—</div></div>`).join('');
      el.querySelector('#sure-cap').textContent = 'pieces it was sure about';
      el.querySelector('#worst-cap').textContent = 'biggest hesitation';
      el.querySelector('#pack-cap').textContent = 'backpack full';
    },
    onTurn(msg) {
      const t = msg && msg.turn, st = msg && msg.state, s = peekLib.stats(t && t.tokens);
      el.querySelector('#sure-big').textContent = t && t.tokens && t.tokens.length ? s.sure_pct + '%' : '—';
      el.querySelector('#worst-big').textContent = s.worst ? `${vis(s.worst.chosen)} vs ${vis(s.worst.runner)}` : '—';
      el.querySelector('#pack-big').textContent = st && st.window_tokens ? Math.round(100 * st.next_would_send / st.window_tokens) + '%' : '—';
    },
  };
})();
```

- [ ] **Step 5: Verify each panel alone in replay** — start the app as in Task 4 Step 9, then for each of `chunks`, `answer`, `almost`, `tiles` take a headless screenshot and look at it:

```bash
for p in chunks answer almost tiles; do
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless=new --window-size=900,420 --virtual-time-budget=9000 \
    --screenshot=/tmp/peek-$p.png "http://127.0.0.1:8200/static/peek/panel.html?show=$p&replay=1" >/dev/null 2>&1 &
  sleep 12; pkill -f "headless=new" ; done
```
(Chrome hangs on exit with virtual time — that is why it is backgrounded and killed; the png is written first.)
Expected, by eye (Read each png): `chunks` shows tinted blocks + "2 words → 2 pieces"; `answer` shows "Hi there!" with "Hi" amber-underlined and ringed; `almost` shows two bars `Hi 72%` / `Hello 28%` after ~1.8 s; `tiles` shows `67%`, `“Hi” vs “Hello”`, `1%`.
Also run `node --test static/peek/` → still 5 pass.

- [ ] **Step 6: Commit**

```bash
git add static/peek
git commit -m "peek panels: chunks, answer (paced reveal + ringed hesitations), what-it-almost-said, tiles"
```

---

### Task 6: The driver panel

**Files:**
- Create: `static/peek/driver.js`

**Interfaces:**
- Consumes: `POST ../../api/session {mode:'compact', board:true, peek:true}` → `{session_id, state}`; `POST ../../api/turn {session_id, text}` → `{turn, state}`; bus `hello`.
- Produces: `peekPanels.driver`; sends `turn`, `clear`; answers `hello` by re-sending the last `turn` and `select`. With `?replay=1` it plays `replay.json` onto the bus every 16 s instead of calling the server.

- [ ] **Step 1: `static/peek/driver.js`**

```js
// The driver: the only panel that talks to the server. Everything else listens on the bus.
peekPanels.driver = (function () {
  let el, sid = null, busy = false;
  const API = '../../api/';                                  // relative: the app lives under /demo/ behind Caddy
  const ASKS = ['Pick a number between 1 and 10', "What's the capital of Australia?", 'Finish this: roses are red, violets are…', 'Write one line about fog'];
  async function post(path, body) {
    const r = await fetch(API + path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
    return r.json();
  }
  async function ask(text) {
    text = (text || '').trim(); if (!text || busy) return;
    busy = true; status('thinking…'); el.querySelectorAll('button,input').forEach(b => b.disabled = true);
    try {
      if (!sid) sid = (await post('session', { mode: 'compact', board: true, peek: true })).session_id;
      const r = await post('turn', { session_id: sid, text });
      peekBus.send('turn', r);
      status(r.turn.event === 'compacted' ? 'the backpack was full — it compacted first' : '');
    } catch (e) { status('error: ' + e.message); if (/no such session/.test(e.message)) sid = null; }   // show the real error; a restart forgets sessions
    busy = false; el.querySelectorAll('button,input').forEach(b => b.disabled = false); el.querySelector('#q').value = ''; el.querySelector('#q').focus();
  }
  function status(s) { el.querySelector('#st').textContent = s; }
  return {
    mount(root) {
      el = root;
      el.innerHTML = '<div class="cap">ask the model</div><form id="f" style="display:flex;gap:.5em"><input type="text" id="q" placeholder="type a question" autocomplete="off"><button>Ask</button></form>' +
        '<div id="asks" style="display:flex;flex-wrap:wrap;gap:.4em"></div><div style="display:flex;gap:.6em;align-items:center"><button id="new" type="button">Start over</button><span id="st" class="dim"></span></div>';
      ASKS.forEach(a => { const b = document.createElement('button'); b.type = 'button'; b.textContent = a; b.onclick = () => ask(a); el.querySelector('#asks').appendChild(b); });
      el.querySelector('#f').onsubmit = e => { e.preventDefault(); ask(el.querySelector('#q').value); };
      el.querySelector('#new').onclick = () => { sid = null; peekBus.send('clear', {}); status(''); };
      peekBus.on('hello', () => {                              // a panel opened late: repeat the last turn for it
        const t = peekBus.last('turn'), s = peekBus.last('select');
        if (t) peekBus.send('turn', t); if (t && s) peekBus.send('select', s);
      });
      if (new URLSearchParams(location.search).get('replay') === '1') {
        fetch('replay.json').then(r => r.json()).then(rp => {
          let i = 0; const play = () => peekBus.send('turn', rp.turns[i++ % rp.turns.length]);
          status('replay — no model'); play(); setInterval(play, 16000);
        });
      }
    },
    onTurn() {},
  };
})();
```

Known and accepted: when the driver answers a `hello` it re-sends `turn` to every panel, so panels already showing that turn replay their reveal once. Fine for a wall being arranged.

- [ ] **Step 2: Verify the bus across windows (replay, no model)** — app running as before. Open two normal Chrome windows by hand:
`http://127.0.0.1:8200/static/peek/panel.html?show=driver&replay=1` and `http://127.0.0.1:8200/static/peek/panel.html?show=answer`
Expected: the answer window shows "Hi there!" within a second of opening (late-join), then the next canned turn every 16 s; clicking a piece in `answer` with an `almost` window open changes its bars.

- [ ] **Step 3: Verify live against Typhoon's Ollama** — tunnel + run locally:

```bash
ssh -f -N -L 11436:127.0.0.1:11434 simonhg@192.168.10.137
VLLM_URL=http://127.0.0.1:11436 VLLM_MODEL=qwen2.5:14b CTXDEMO_EXTRACT=0 CTXDEMO_TOKENIZER=Qwen/Qwen2.5-14B-Instruct .venv/bin/uvicorn app.main:app --port 8200 &
SID=$(curl -s -X POST localhost:8200/api/session -H 'Content-Type: application/json' -d '{"mode":"compact","board":true,"peek":true}' | python3 -c 'import json,sys;print(json.load(sys.stdin)["session_id"])')
curl -s -X POST localhost:8200/api/turn -H 'Content-Type: application/json' -d "{\"session_id\":\"$SID\",\"text\":\"Pick a number between 1 and 10\"}" | python3 -c 'import json,sys;t=json.load(sys.stdin)["turn"];print(t["user_chunks"]);print([(x["t"],x["p"]) for x in t["tokens"]][:8])'
```
Expected: a non-empty chunk list and a list of `(piece, probability)` pairs with at least one `p < 0.9`. Then open the driver (no `replay`) + `answer` + `almost` windows and press a "try asking" button.

- [ ] **Step 4: Commit**

```bash
git add static/peek/driver.js
git commit -m "peek panels: driver (owns the session, feeds the bus, answers late joiners, replay mode)"
```

---

### Task 7: Tab 6, the wall page, docs

**Files:**
- Create: `static/peek/wall.html`
- Modify: `static/index.html` (nav at ~line 172, new section after `#tab-map` closes ~line 260, one block of script next to the `#map` hash handling ~line 661), `README.md`
- Test: `tests/test_api.py`

**Interfaces:**
- Consumes: `static/peek/panel.html?show=&room=&replay=`.
- Produces: `#guess` hash; `static/peek/wall.html?layout=<json>&room=&replay=1`.

- [ ] **Step 1: Write the failing test** — append to `tests/test_api.py`:

```python
def test_act6_pages_are_served(client):
    html = client.get("/").text
    assert 'data-tab="guess"' in html and 'id="tab-guess"' in html
    for f in ("panel.html", "wall.html", "bus.js", "lib.js", "peek.css", "replay.json",
              "driver.js", "chunks.js", "answer.js", "almost.js", "tiles.js"):
        assert client.get(f"/static/peek/{f}").status_code == 200, f
    assert 'src="/' not in client.get("/static/peek/wall.html").text      # relative URLs only: we live under /demo/
```

Run: `.venv/bin/python -m pytest tests/test_api.py::test_act6_pages_are_served -q` → Expected: FAIL (no `data-tab="guess"`).

- [ ] **Step 2: `static/peek/wall.html`**

```html
<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>ctxdemo · the guesses</title>
<style>html,body{height:100%;margin:0;background:#0f1216;overflow:hidden} iframe{position:absolute;border:0;border-radius:6px;outline:1px solid #262d36}</style></head>
<body><script>
  // The frozen wall: positions in % of the screen.  wall.html?layout={"answer":[2,30,60,45],...}&room=wall&replay=1
  const q = new URLSearchParams(location.search), room = q.get('room') || 'wall';
  const DEFAULT = { driver: [2, 3, 60, 24], chunks: [64, 3, 34, 24], answer: [2, 30, 60, 45], almost: [64, 30, 34, 45], tiles: [2, 78, 96, 19] };
  let layout = DEFAULT;
  try { if (q.get('layout')) layout = JSON.parse(q.get('layout')); } catch (e) { console.error('bad ?layout=, using the default', e); }
  for (const [name, [x, y, w, h]] of Object.entries(layout)) {
    const f = document.createElement('iframe');
    f.src = `panel.html?show=${encodeURIComponent(name)}&room=${encodeURIComponent(room)}` + (name === 'driver' && q.get('replay') === '1' ? '&replay=1' : '');
    Object.assign(f.style, { left: x + '%', top: y + '%', width: w + '%', height: h + '%' });
    document.body.appendChild(f);
  }
</script></body></html>
```

- [ ] **Step 3: `static/index.html`** — three small edits.

(a) After the `data-tab="map"` nav button add:

```html
  <button role="tab" aria-selected="false" data-tab="guess">6 · The guesses</button>
```

(b) Immediately after the closing `</section>` of `#tab-map` add:

```html
<section class="tab" id="tab-guess">
  <p class="intro">The model never "knows" its answer. It reads your sentence in <b>pieces</b> and, for every piece it writes, it ranks its <b>guesses</b> and picks one. Green means it was sure; red means it was close to a coin-flip. Tap any piece to see what it almost said. <span class="dim">(Real terms: pieces are <i>tokens</i>; the ranked guesses come from the model's <i>log-probabilities</i>.)</span></p>
  <div id="guess-frame" style="height: calc(100vh - 260px); min-height: 460px; border: 1px solid var(--line); border-radius: 6px; overflow: hidden;"></div>
</section>
```

(c) Next to the `#map` hash lines (~661) add:

```js
    // act 6 is just the panels arranged in one frame; built on first open so it costs nothing until used
    document.querySelector('nav button[data-tab=guess]').addEventListener('click', () => {
      const box = $('guess-frame'); if (box.firstChild) return;
      const f = document.createElement('iframe');
      f.src = 'static/peek/wall.html?room=tab-' + Math.random().toString(36).slice(2, 8) + (new URLSearchParams(location.search).get('replay') === '1' ? '&replay=1' : '');
      f.style.cssText = 'width:100%;height:100%;border:0'; box.appendChild(f);
    });
    if (location.hash === '#guess') { document.querySelector('nav button[data-tab=guess]').click(); }
```

Before editing, read how the existing nav click handler switches tabs (search for `data-tab` in the script) and confirm it is generic over `data-tab` → `#tab-<name>`; if it is a hard-coded list, add `guess` to it. `$` is the page's existing `getElementById` helper — confirm it exists near line 270; if not, use `document.getElementById`.

- [ ] **Step 4: README** — append:

```markdown
## Act 6 — The guesses (2026-09)
How the model reads and chooses: the sentence in pieces (tokens), the answer coloured by how sure it was, and what it almost said.
- Built from standalone panels: `static/peek/panel.html?show=driver|chunks|answer|almost|tiles&room=wall`. One Chrome, one machine (BroadcastChannel). Launch frameless: `chrome --app=<url>`; size them; then freeze the geometry into `static/peek/wall.html?layout={...}`.
- Any panel + `&replay=1` plays canned turns with no model. `driver&replay=1` replays for every open panel.
- Server: sessions created with `peek: true` ask the chat server for `logprobs` (same request on Ollama and vLLM). Chunks need `CTXDEMO_TOKENIZER` (HF repo of the chat model's tokenizer); unset → strip shows the plain sentence.
- JS helper tests: `node --test static/peek/`. Spec: `docs/specs/2026-09-21-ctxdemo-guesses-design.md`.
```

- [ ] **Step 5: Run everything**

Run: `.venv/bin/python -m pytest -q` → Expected: 64 passed. Run: `node --test static/peek/` → 5 pass.
Then headless-screenshot `http://127.0.0.1:8200/?replay=1#guess` at 1600×900 (same Chrome trick as Task 5) and Read the png: five panels visible, answer coloured, bars filled, acts 1–5 nav unchanged.

- [ ] **Step 6: Commit**

```bash
git add static/index.html static/peek/wall.html README.md tests/test_api.py
git commit -m "act 6: the guesses tab + wall page are arrangements of the peek panels"
```

---

### Task 8: Real replay capture and Typhoon run

**Files:**
- Modify: `static/peek/replay.json`

- [ ] **Step 1: Capture three real turns** — with the tunnel and local app from Task 6 Step 3 running:

```bash
.venv/bin/python - <<'EOF'
import json, httpx
c = httpx.Client(base_url="http://127.0.0.1:8200", timeout=300)
sid = c.post("/api/session", json={"mode": "compact", "board": True, "peek": True}).json()["session_id"]
keep_turn = ("n", "user", "answer", "seconds", "event", "event_text", "user_chunks", "tokens")
turns = []
for q in ["Pick a number between 1 and 10", "What's the capital of Australia?", "Finish this: roses are red, violets are…"]:
    r = c.post("/api/turn", json={"session_id": sid, "text": q}).json()
    turns.append({"turn": {k: r["turn"][k] for k in keep_turn},
                  "state": {k: r["state"][k] for k in ("window_tokens", "next_would_send")}})
json.dump({"captured": "qwen2.5:14b on Typhoon Ollama", "turns": turns}, open("static/peek/replay.json", "w"), ensure_ascii=False, indent=1)
print([len(t["turn"]["tokens"]) for t in turns])
EOF
```
Expected: three non-zero piece counts. If every piece in all three turns has `p >= 0.9` (nothing to ring), swap one question for "Write one line about fog" and re-run.

- [ ] **Step 2: Run on Typhoon itself** — `rsync -a --exclude .venv --exclude .git ./ typhoon:/Users/project/ctxdemo/`, on Typhoon `pip install -r requirements.txt` in its venv, restart `run-typhoon.sh`, open `http://localhost:8200/#guess` through the usual `ssh -L 8200:localhost:8200 typhoon` tunnel. Ask Simon before the rsync (it changes Typhoon's working copy).

- [ ] **Step 3: Full check + commit**

Run: `.venv/bin/python -m pytest -q && node --test static/peek/` → Expected: 64 passed; 5 pass.

```bash
git add static/peek/replay.json
git commit -m "act 6: replay captured from a real qwen2.5:14b run"
```

---

## Out of scope here (next plans)
Roads not taken (a `roads` panel + `branch` message), thinking out loud, inside the head, concepts, live streaming, the box port (spec §6 checklist — one VPN session, Simon's call when).
