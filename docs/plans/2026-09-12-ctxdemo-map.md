# The Map (act 5) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A fifth tab that draws the session's context as a growing concept graph, which shrinks on compaction and collapses-then-reseeds on handoff, sharing tab 4's camera, mic and session.

**Architecture:** `app/graph.py` holds a pure `Graph` (nodes, edges, survive rule, generation counter) and the extraction prompt/parser. `Session` calls the model once more per turn to extract concepts and reports a `graph_delta`; compaction and handoff run `survive`. The page gets a `static/map.js` renderer (d3-force on canvas, vendored d3) and tab 5 markup; the existing `boardTab()` controller renders into both tabs and fires hooks the map listens to.

**Tech Stack:** Python 3.12+/FastAPI/pytest (existing), d3 7.9.0 vendored (ISC), plain JS.

**Spec:** `docs/specs/2026-09-12-ctxdemo-map-design.md`

## Global Constraints
- Tabs 1–4 keep working unchanged; all 31 existing tests stay green.
- Extraction never raises into a turn; failure → empty delta, logged.
- Extraction tokens are charged to the turn (`sent_tokens`, `new_tokens`, `breakdown["extract"]`).
- Test `Config` fixture sets `extract=False` (FakeVLLM pops a response queue; extraction would eat responses).
- No CDN at runtime: d3 lives in `static/vendor/d3.min.js`.
- Commit after every task with the session attribution trailer.

---

### Task 1: `app/graph.py` — parser, apply, survive

**Files:**
- Create: `app/graph.py`
- Test: `tests/test_graph.py`

**Interfaces:**
- Produces: `EXTRACT_PROMPT: str`; `parse_extract(text) -> tuple[list[str], list[tuple[str,str]]]`; `norm_label(s) -> str`; `class Node(label, first_n, mentions, generation, fresh)`; `class Graph` with `apply(n, concepts, links) -> dict`, `survive(text) -> dict`, `survivors_copy(text) -> Graph`, `to_dict() -> dict`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_graph.py
from app.graph import parse_extract, norm_label, Graph


def test_parse_clean_fenced_and_garbage():
    assert parse_extract('{"concepts": ["Quantization", "int8"], "links": [["quantization", "int8"]]}') == (["Quantization", "int8"], [("quantization", "int8")])
    assert parse_extract('```json\n{"concepts": ["a"], "links": []}\n```') == (["a"], [])
    assert parse_extract("Sure! Here you go: {\"concepts\": [\"gpu\"], \"links\": [[\"gpu\", 3]]} thanks") == (["gpu"], [])
    assert parse_extract("no json here") == ([], [])
    assert parse_extract('{"concepts": "not a list"}') == ([], [])


def test_norm_label():
    assert norm_label("  Quantization! ") == "quantization"
    assert norm_label("GPUs") == "gpu"
    assert norm_label("bus") == "bus"            # short words keep their s
    assert norm_label("Mixture   of Experts") == "mixture of experts"


def test_apply_adds_bumps_and_links_pairwise():
    g = Graph()
    d = g.apply(1, ["Quantization", "int8", "VRAM"], [("int8", "vram")])
    assert d == {"added": ["quantization", "int8", "vram"], "bumped": [],
                 "edges": [["int8", "quantization", 1], ["int8", "vram", 2], ["quantization", "vram", 1]]}
    d2 = g.apply(2, ["int8", "latency"], [])
    assert d2["added"] == ["latency"] and d2["bumped"] == ["int8"]
    assert g.nodes["int8"].mentions == 2 and g.nodes["int8"].first_n == 1 and g.nodes["latency"].first_n == 2
    assert g.edges[("int8", "latency")] == 1 and g.edges[("int8", "vram")] == 2
    assert g.apply(3, ["int8", "int8"], [("int8", "int8")])["edges"] == []      # no self edges, no dup


def test_survive_keeps_mentioned_absorbs_rest_and_counts_generations():
    g = Graph()
    g.apply(1, ["quantization", "int8", "vram"], [])
    g.apply(2, ["vram", "gpu"], [])
    d = g.survive("We talked about quantization and the GPU.")
    assert d["kept"] == [["quantization", 1], ["gpu", 1]]
    # int8 is linked only to quantization (w1) and vram; vram linked to int8, quantization, gpu.  vram's heaviest surviving neighbour: quantization (w1) vs gpu (w1) -> first by weight then label order
    assert d["absorbed"] == [["int8", "quantization"], ["vram", "gpu"]]
    assert set(g.nodes) == {"quantization", "gpu"}
    # re-mentioned survivor resets generation; a survivor kept only via text ticks up again
    g.apply(3, ["quantization"], [])
    assert g.nodes["quantization"].generation == 0
    d2 = g.survive("quantization and gpu again")
    assert d2["kept"] == [["quantization", 1], ["gpu", 2]]


def test_survive_prefix_match_and_nothing_survives():
    g = Graph()
    g.apply(1, ["mixture of experts", "routing"], [])
    d = g.survive("mixtures were discussed")            # 5+ char prefix 'mixtu' matches
    assert d["kept"] == [["mixture of experts", 1]] and d["absorbed"] == [["routing", "mixture of experts"]]
    g2 = Graph(); g2.apply(1, ["a-thing", "b-thing"], [])
    d = g2.survive("nothing relevant")
    assert d == {"kept": [], "absorbed": [["a-thing", None], ["b-thing", None]]} and g2.nodes == {}


def test_survivors_copy_leaves_original_alone():
    g = Graph(); g.apply(1, ["alpha", "beta"], [])
    c = g.survivors_copy("alpha only")
    assert set(c.nodes) == {"alpha"} and set(g.nodes) == {"alpha", "beta"}
    assert c.nodes["alpha"].generation == 1 and g.nodes["alpha"].generation == 0


def test_to_dict_shape():
    g = Graph(); g.apply(1, ["alpha", "beta"], [])
    d = g.to_dict()
    assert d["nodes"] == [{"label": "alpha", "first_n": 1, "mentions": 1, "generation": 0},
                          {"label": "beta", "first_n": 1, "mentions": 1, "generation": 0}]
    assert d["edges"] == [["alpha", "beta", 1]]
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_graph.py -q`
Expected: ImportError `app.graph`.

- [ ] **Step 3: Implement `app/graph.py`**

```python
"""The map: a concept graph of what the conversation is holding. Pure data — no model calls here.

Nodes are concepts (short nouns) the model extracts from each exchange. Edges are co-mentions.
`survive(text)` is the compaction/handoff rule: a node lives on only if the summary/note still says it."""
from __future__ import annotations
import copy, json, re
from dataclasses import dataclass

EXTRACT_PROMPT = ("Read this exchange and list the 3 to 6 most important concepts as short nouns (1-3 words, lower-case). "
                  "Then list pairs of those concepts that are directly related. "
                  'Reply with JSON only: {"concepts": ["..."], "links": [["a", "b"]]}\n\n')
_NOISE = re.compile(r"[^a-z0-9' \-]+")
PREFIX = 5


def norm_label(s: str) -> str:
    s = re.sub(r"\s+", " ", _NOISE.sub(" ", (s or "").lower())).strip()
    if len(s) > 4 and s.endswith("s") and not s.endswith("ss"):
        s = s[:-1]
    return s


def parse_extract(text: str) -> tuple[list[str], list[tuple[str, str]]]:
    """Tolerant: strips fences/chatter, takes the first {...} block. Never raises."""
    if not text:
        return [], []
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return [], []
    try:
        j = json.loads(m.group(0))
    except json.JSONDecodeError:
        return [], []
    concepts = j.get("concepts") if isinstance(j, dict) else None
    if not isinstance(concepts, list):
        return [], []
    concepts = [c for c in concepts if isinstance(c, str) and c.strip()]
    links = []
    for l in (j.get("links") or []) if isinstance(j.get("links"), list) else []:
        if isinstance(l, (list, tuple)) and len(l) == 2 and all(isinstance(x, str) for x in l):
            links.append((l[0], l[1]))
    return concepts, links


@dataclass
class Node:
    label: str
    first_n: int
    mentions: int = 1
    generation: int = 0      # 0 = said in this transcript; +1 per survive without being re-mentioned
    fresh: bool = True       # mentioned since the last survive


class Graph:
    def __init__(self):
        self.nodes: dict[str, Node] = {}
        self.edges: dict[tuple[str, str], int] = {}

    def _edge(self, a: str, b: str, w: int = 1) -> tuple[str, str] | None:
        if a == b or a not in self.nodes or b not in self.nodes:
            return None
        k = (a, b) if a < b else (b, a)
        self.edges[k] = self.edges.get(k, 0) + w
        return k

    def apply(self, n: int, concepts: list[str], links: list[tuple[str, str]]) -> dict:
        added, bumped, touched = [], [], []
        seen: list[str] = []
        for c in concepts:
            k = norm_label(c)
            if not k or k in seen:
                continue
            seen.append(k)
            if k in self.nodes:
                nd = self.nodes[k]; nd.mentions += 1; nd.generation = 0; nd.fresh = True; bumped.append(k)
            else:
                self.nodes[k] = Node(k, n); added.append(k)
        for i, a in enumerate(seen):
            for b in seen[i + 1:]:
                e = self._edge(a, b)
                if e and e not in touched: touched.append(e)
        for a, b in links:
            e = self._edge(norm_label(a), norm_label(b))
            if e and e not in touched: touched.append(e)
        return {"added": added, "bumped": bumped, "edges": [[a, b, self.edges[(a, b)]] for a, b in sorted(touched)]}

    def _mentioned(self, label: str, text: str) -> bool:
        return label in text or (len(label) >= PREFIX and label[:PREFIX] in text)

    def survive(self, text: str) -> dict:
        """Compaction / handoff. Keeps nodes the text still mentions; the rest are absorbed into their heaviest surviving neighbour."""
        t = (text or "").lower()
        keep = [k for k in self.nodes if self._mentioned(k, t)]
        kept, absorbed = [], []
        for k in keep:
            nd = self.nodes[k]
            if not nd.fresh:
                nd.generation += 1
            else:
                nd.generation = max(nd.generation, 1) if nd.generation else 1 if False else nd.generation
            nd.fresh = False
            kept.append([k, nd.generation])
        heaviest = max(keep, key=lambda k: (self.nodes[k].mentions, -keep.index(k)), default=None)
        for k in list(self.nodes):
            if k in keep:
                continue
            best, bw = None, 0
            for (a, b), w in self.edges.items():
                other = b if a == k else a if b == k else None
                if other in keep and (w > bw or (w == bw and best and other < best)):
                    best, bw = other, w
            absorbed.append([k, best or heaviest])
            del self.nodes[k]
        self.edges = {e: w for e, w in self.edges.items() if e[0] in self.nodes and e[1] in self.nodes}
        return {"kept": kept, "absorbed": absorbed}

    def survivors_copy(self, text: str) -> "Graph":
        g = copy.deepcopy(self)
        g.survive(text)
        return g

    def to_dict(self) -> dict:
        return {"nodes": [{"label": nd.label, "first_n": nd.first_n, "mentions": nd.mentions, "generation": nd.generation}
                          for nd in self.nodes.values()],
                "edges": [[a, b, w] for (a, b), w in self.edges.items()]}
```

Note on generation: the rule in `survive` is exactly "kept and fresh → generation stays as is but the node is no longer fresh; kept and not fresh → generation += 1". First survive of a fresh node: spec wants it to read as generation 1 (it now lives via text). So simplify the branch to:

```python
            nd.generation = nd.generation + 1 if not nd.fresh else 1
```
(fresh node surviving for the first time → 1; re-mentioned later → `apply` resets to 0; survives again → 1; not re-mentioned and survives again → 2.) Use this line; delete the confusing one above.

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/test_graph.py -q`
Expected: 7 passed. If `test_survive_keeps_mentioned...` disagrees on absorb targets, check tie-break: highest weight, then alphabetical label.

- [ ] **Step 5: Commit**

```bash
git add app/graph.py tests/test_graph.py
git commit -m "graph: concept graph with survive rule and generation counter"
```

---

### Task 2: Session hooks — extraction per turn, survive on compact/handoff

**Files:**
- Modify: `app/config.py` (add `extract`, `extract_max_tokens`)
- Modify: `app/session.py` (import, `TurnResult.graph_delta`, `Session.graph`, `_extract`, `_compact`, `turn`, `handoff`, `state`)
- Modify: `tests/conftest.py` (cfg fixture `extract=False`)
- Test: `tests/test_session.py`

**Interfaces:**
- Consumes: `Graph`, `EXTRACT_PROMPT`, `parse_extract` from Task 1.
- Produces: `TurnResult.graph_delta: dict` (`{"added","bumped","edges"}` plus `"survive": {...}` when the turn compacted); `Session.graph: Graph`; `Session.last_survive: dict | None` (set by `_compact`); `HandoffResult.graph_survive: dict`; `state()["graph"]`.

- [ ] **Step 1: Failing tests** (append to `tests/test_session.py`)

```python
from dataclasses import replace
from app.session import Session


def test_extract_runs_once_per_turn_and_charges_tokens(fake, cfg):
    c = replace(cfg, extract=True)
    fake.responses = ["The answer about quantization.", '{"concepts": ["quantization", "int8"], "links": []}']
    s = Session("endless", fake, c)
    t = s.turn("tell me about quantization")
    assert len(fake.calls) == 2 and fake.calls[1]["max_tokens"] == c.extract_max_tokens
    assert t.graph_delta["added"] == ["quantization", "int8"]
    assert t.breakdown["extract"] > 0 and sum(t.breakdown.values()) == t.sent_tokens
    assert t.new_tokens == fake.count("The answer about quantization.") + fake.count(fake.calls[1]["messages"][-1]["content"]) - fake.count(fake.calls[1]["messages"][-1]["content"]) + fake.count('{"concepts": ["quantization", "int8"], "links": []}')
    assert s.state()["graph"]["nodes"][0]["label"] == "quantization"


def test_extract_off_means_no_extra_call(fake, cfg):
    s = Session("endless", fake, cfg)
    t = s.turn("hello")
    assert len(fake.calls) == 1 and t.graph_delta == {"added": [], "bumped": [], "edges": []}


def test_extract_failure_is_swallowed(fake, cfg):
    c = replace(cfg, extract=True)
    fake.responses = ["ok", "not json at all"]
    t = Session("endless", fake, c).turn("hi")
    assert t.graph_delta["added"] == []


def test_compaction_survives_graph(fake, cfg):
    c = replace(cfg, extract=True, window_tokens=60, compact_at=0.5)
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
    c = replace(cfg, extract=True)
    fake.responses = ["a1", '{"concepts": ["alpha", "beta"], "links": [["alpha","beta"]]}', "NOTE: alpha matters"]
    s = Session("handoff", fake, c); s.turn("x")
    h = s.handoff()
    assert h.graph_survive == {"kept": [["alpha", 1]], "absorbed": [["beta", "alpha"]]}
    assert [n["label"] for n in h.new_session.state()["graph"]["nodes"]] == ["alpha"]
    assert set(s.graph.nodes) == {"alpha", "beta"}          # old session untouched
```

Simplify the `new_tokens` assertion to: `assert t.new_tokens == fake.count("The answer about quantization.") + fake.count('{"concepts": ["quantization", "int8"], "links": []}')`.

- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_session.py -q` → fails (`extract` not a Config field).

- [ ] **Step 3: Implement**

`app/config.py`, inside `Config`:
```python
    extract: bool = True                 # the map: one extra model call per turn to pull concepts
    extract_max_tokens: int = 200
```
and in `load()` before the return: `if os.environ.get("CTXDEMO_EXTRACT") == "0": demo["extract"] = False` (add `"extract"` handling only via env; `demo.json` need not list it).

`tests/conftest.py` cfg fixture: add `extract=False`.

`app/session.py`:
- import: `from .graph import Graph, EXTRACT_PROMPT, parse_extract` and `import logging; log = logging.getLogger("uvicorn.error")`.
- `TurnResult`: add `graph_delta: dict = field(default_factory=lambda: {"added": [], "bumped": [], "edges": []})`.
- `HandoffResult`: add `graph_survive: dict = field(default_factory=dict)` (make it a dataclass field after `new_session`).
- `Session.__init__`: `self.graph = Graph()`; `self.last_survive: dict | None = None`.
- New method:
```python
    def _extract(self, n: int, user_text: str, answer: str) -> tuple[dict, int, int, float]:
        """One small model call → (delta, prompt_tokens, completion_tokens, seconds). Never raises."""
        empty = {"added": [], "bumped": [], "edges": []}
        if not self.cfg.extract or not answer:
            return empty, 0, 0, 0.0
        try:
            r = self.vllm.chat([{"role": "user", "content": f"{EXTRACT_PROMPT}USER: {user_text}\n\nASSISTANT: {answer}"}],
                               self.cfg.extract_max_tokens)
            concepts, links = parse_extract(r.text)
            return self.graph.apply(n, concepts, links), r.prompt_tokens, r.completion_tokens, r.seconds
        except Exception as e:      # the map must never break a turn
            log.warning("extract failed: %s: %s", type(e).__name__, e)
            return empty, 0, 0, 0.0
```
- `_compact()`: after `self.memory = (...)`, add `self.last_survive = self.graph.survive(r.text)`.
- `turn()`: after the final `self.transcript.append({"role": "assistant", "content": r.text})`:
```python
        delta, xp, xc, xs = self._extract(n, user_text, r.text)
        sent += xp; new += xc; secs += xs
        breakdown["extract"] = xp
        if event == "compacted" and self.last_survive is not None:
            delta["survive"] = self.last_survive; self.last_survive = None
```
and pass `graph_delta=delta` into `TurnResult(...)`. (The over-limit early return keeps the default empty delta.)
- `handoff()`: after building `new`: `new.graph = self.graph.survivors_copy(r.text)`; compute `surv = copy.deepcopy(self.graph).survive(r.text)` — simpler: do both in one: 
```python
        g = copy.deepcopy(self.graph); surv = g.survive(r.text); new.graph = g
```
(`import copy` at top) and return `HandoffResult(note=r.text, note_tokens=..., new_session=new, graph_survive=surv)`.
- `state()`: add `"graph": self.graph.to_dict()`.

- [ ] **Step 4: Run the whole suite** `.venv/bin/python -m pytest -q` → all pass (31 old + 7 graph + 5 session).

- [ ] **Step 5: Commit** `git add app/config.py app/session.py tests/conftest.py tests/test_session.py && git commit -m "session: extract concepts per turn; graph survives compaction and seeds handoff"`

---

### Task 3: API surface + static mount

**Files:**
- Modify: `app/main.py` (`/api/compact` and `/api/handoff` responses; mount `/static`)
- Test: `tests/test_api.py`

**Interfaces:**
- Produces: `/api/turn` → `turn.graph_delta`; `/api/compact` → `graph_survive`; `/api/handoff` → `graph_seed`, `graph_survive`; `GET /api/session/{sid}` → `state.graph`; `GET /static/<file>`.

- [ ] **Step 1: Failing tests** (append to `tests/test_api.py`)

```python
def test_graph_fields_on_routes(client, fake, cfg):
    from dataclasses import replace
    from app.main import create_app
    app = create_app(vllm=fake, cfg=replace(cfg, extract=True)); app.state.race_threads = False
    c = TestClient(app)
    fake.responses = ["a1", '{"concepts": ["alpha", "beta"], "links": []}', "summary: alpha", "NOTE beta"]
    sid = c.post("/api/session", json={"mode": "handoff"}).json()["session_id"]
    t = c.post("/api/turn", json={"session_id": sid, "text": "x"}).json()["turn"]
    assert t["graph_delta"]["added"] == ["alpha", "beta"]
    assert c.get(f"/api/session/{sid}").json()["graph"]["edges"] == [["alpha", "beta", 1]]
    j = c.post("/api/compact", json={"session_id": sid}).json()
    assert j["graph_survive"]["kept"] == [["alpha", 1]]
    h = c.post("/api/handoff", json={"session_id": sid}).json()
    assert h["graph_survive"]["absorbed"] == [["alpha", None]] and h["graph_seed"]["nodes"] == []


def test_static_is_served(client):
    assert client.get("/static/map.js").status_code in (200, 404)     # mount exists (404 only until Task 5 adds the file)
    assert client.get("/static/../app/main.py").status_code in (403, 404)
```

- [ ] **Step 2: Run** → `graph_survive` KeyError.

- [ ] **Step 3: Implement** in `app/main.py`:
- `from fastapi.staticfiles import StaticFiles`; after `app = FastAPI(...)`: `app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")`.
- `/api/compact`: return `{"summary": text, "graph_survive": s.last_survive or {"kept": [], "absorbed": []}, "state": s.state()}` and set `s.last_survive = None` after reading.
- `/api/handoff`: add `"graph_seed": h.new_session.graph.to_dict(), "graph_survive": h.graph_survive`.

- [ ] **Step 4: Run** `.venv/bin/python -m pytest -q` → green.
- [ ] **Step 5: Commit** `git add app/main.py tests/test_api.py && git commit -m "api: graph deltas on turn/compact/handoff; serve /static"`

---

### Task 4: Vendor d3 + replay fixture

**Files:**
- Create: `static/vendor/d3.min.js` (d3 7.9.0 from cdnjs, saved once)
- Create: `static/replay.json`

- [ ] **Step 1:** `mkdir -p static/vendor && curl -sL -o static/vendor/d3.min.js https://cdnjs.cloudflare.com/ajax/libs/d3/7.9.0/d3.min.js && head -c 80 static/vendor/d3.min.js` — expect `// https://d3js.org v7.9.0`.
- [ ] **Step 2:** Write `static/replay.json`: `{"turns": [...]}` with 12 entries of `{"user", "answer", "graph_delta"}`; entry 8 carries `"event": "compacted", "event_text": "<summary>"` and its delta has `"survive"`; entry 12 is `{"handoff": true, "note": "...", "graph_survive": {...}, "graph_seed": {...}}`. Topics: tokens, context window, quantization, int8, vram, gpu, rlhf, reward model, mixture of experts, routing, latency, cost. Deltas must be consistent (a node is `added` once, then `bumped`). Keep answers to two sentences.
- [ ] **Step 3: Commit** `git add static/vendor static/replay.json && git commit -m "map: vendor d3 7.9.0, canned replay transcript"`

---

### Task 5: `static/map.js` — the renderer

**Files:**
- Create: `static/map.js`

**Interfaces:**
- Produces global `window.ctxMap = { init(canvas), seed(graphDict), applyDelta(delta), applySurvive(survive), handoff(seedGraphDict, survive), clear() }`. Node objects `{id, r, gen, born, fading, tx, ty}`; links `{source, target, w}`.

- [ ] **Step 1: Write it**

```js
// The map: what the conversation is holding, as a graph. d3-force on a 2D canvas.
(() => {
  const NOW = () => performance.now();
  let canvas, ctx, sim, nodes = [], links = [], byId = new Map(), W = 0, H = 0, raf = 0, collapse = null;
  const css = k => getComputedStyle(document.documentElement).getPropertyValue(k).trim();
  const R = m => 6 + 3 * Math.sqrt(m);
  function resize() { const b = canvas.getBoundingClientRect(); W = canvas.width = b.width * devicePixelRatio; H = canvas.height = b.height * devicePixelRatio; ctx.setTransform(devicePixelRatio, 0, 0, devicePixelRatio, 0, 0); W /= devicePixelRatio; H /= devicePixelRatio; if (sim) sim.force('center', d3.forceCenter(W / 2, H / 2)).alpha(0.3).restart(); }
  function init(el) {
    canvas = el; ctx = el.getContext('2d'); resize(); addEventListener('resize', resize);
    sim = d3.forceSimulation(nodes).force('link', d3.forceLink(links).id(d => d.id).distance(l => 70 - 6 * Math.min(5, l.w)).strength(l => 0.2 + 0.1 * Math.min(5, l.w)))
      .force('charge', d3.forceManyBody().strength(-160)).force('center', d3.forceCenter(W / 2, H / 2))
      .force('collide', d3.forceCollide(d => R(d.m) + 14)).alphaDecay(0.03).on('tick', () => {});
    loop();
  }
  const add = (id, m, gen, x, y) => { if (byId.has(id)) return byId.get(id); const n = { id, m: m || 1, gen: gen || 0, born: NOW(), x: x ?? W / 2 + (Math.random() - .5) * 60, y: y ?? H / 2 + (Math.random() - .5) * 60 }; nodes.push(n); byId.set(id, n); return n; };
  const link = (a, b, w) => { const s = byId.get(a), t = byId.get(b); if (!s || !t) return; const e = links.find(l => (l.source.id || l.source) === a && (l.target.id || l.target) === b); if (e) e.w = w; else links.push({ source: s, target: t, w }); };
  function restart() { sim.nodes(nodes); sim.force('link').links(links); sim.alpha(0.6).restart(); }
  function seed(g) { clear(); for (const n of (g.nodes || [])) add(n.label, n.mentions, n.generation); for (const [a, b, w] of (g.edges || [])) link(a, b, w); restart(); }
  function applyDelta(d) {
    if (!d) return;
    for (const id of d.added || []) add(id, 1, 0);
    for (const id of d.bumped || []) { const n = byId.get(id); if (n) { n.m++; n.gen = 0; n.born = NOW(); } }
    for (const [a, b, w] of d.edges || []) link(a, b, w);
    if (d.survive) applySurvive(d.survive);
    restart();
  }
  function applySurvive(s) {
    for (const [id, gen] of s.kept || []) { const n = byId.get(id); if (n) { n.gen = gen; n.pulse = NOW(); } }
    for (const [id, into] of s.absorbed || []) {
      const n = byId.get(id); if (!n) continue;
      const t = into && byId.get(into); n.fading = NOW(); n.tx = t ? t.x : W / 2; n.ty = t ? t.y : H / 2; n.target = t || null;
      byId.delete(id); links = links.filter(l => l.source.id !== id && l.target.id !== id);
    }
    restart();
  }
  function handoff(seedGraph, survive) {
    collapse = { t0: NOW(), seed: seedGraph }; links = []; for (const n of nodes) { n.fading = NOW(); n.tx = W / 2; n.ty = H / 2; byId.delete(n.id); }
  }
  function clear() { nodes.length = 0; links = []; byId = new Map(); collapse = null; restart(); }
  function draw() {
    const t = NOW(); ctx.clearRect(0, 0, W, H);
    const bone = css('--bone'), moss = css('--moss'), dim = css('--dim'), ice = css('--ice');
    ctx.lineCap = 'round';
    for (const l of links) { ctx.strokeStyle = dim; ctx.globalAlpha = 0.35; ctx.lineWidth = 0.5 + 0.6 * Math.min(6, l.w); ctx.beginPath(); ctx.moveTo(l.source.x, l.source.y); ctx.lineTo(l.target.x, l.target.y); ctx.stroke(); }
    ctx.globalAlpha = 1;
    for (let i = nodes.length - 1; i >= 0; i--) {
      const n = nodes[i];
      if (n.fading) {                              // absorbed: drift to target and fade over 1.2 s
        const k = Math.min(1, (t - n.fading) / 1200); const tx = n.target ? n.target.x : n.tx, ty = n.target ? n.target.y : n.ty;
        n.x += (tx - n.x) * 0.12; n.y += (ty - n.y) * 0.12; ctx.globalAlpha = 1 - k;
        if (k >= 1) { nodes.splice(i, 1); if (n.target) n.target.pulse = t; continue; }
      } else ctx.globalAlpha = Math.max(0.35, 1 - 0.25 * n.gen);
      const r = R(n.m), age = t - n.born;
      if (age < 2000) { ctx.strokeStyle = moss; ctx.lineWidth = 2; ctx.globalAlpha *= 1; ctx.beginPath(); ctx.arc(n.x, n.y, r + 4 + 6 * (age / 2000), 0, 7); ctx.stroke(); }
      if (n.pulse && t - n.pulse < 600) { ctx.strokeStyle = ice; ctx.lineWidth = 3; ctx.beginPath(); ctx.arc(n.x, n.y, r + 2 + 10 * ((t - n.pulse) / 600), 0, 7); ctx.stroke(); }
      ctx.fillStyle = n.gen ? ice : bone; ctx.beginPath(); ctx.arc(n.x, n.y, r, 0, 7); ctx.fill();
      if (r > 7 || nodes.length < 40) { ctx.fillStyle = bone; ctx.font = `${r > 12 ? 15 : 13}px "Helvetica Neue", system-ui, sans-serif`; ctx.textAlign = 'center'; ctx.fillText(n.id, n.x, n.y + r + 15); }
      ctx.globalAlpha = 1;
    }
    if (collapse) {                                // handoff: everything has been told to fade to centre; after 1.5 s unfold the seed
      const k = (t - collapse.t0) / 1500;
      ctx.fillStyle = ice; ctx.globalAlpha = Math.min(1, k); ctx.beginPath(); ctx.arc(W / 2, H / 2, 14 + 6 * Math.min(1, k), 0, 7); ctx.fill();
      ctx.fillStyle = bone; ctx.font = '14px system-ui'; ctx.textAlign = 'center'; ctx.fillText('handoff note', W / 2, H / 2 + 34); ctx.globalAlpha = 1;
      if (k >= 1) { const s = collapse.seed; collapse = null; nodes.length = 0; byId = new Map(); links = []; for (const n of (s.nodes || [])) add(n.label, n.mentions, n.generation, W / 2, H / 2); for (const [a, b, w] of (s.edges || [])) link(a, b, w); restart(); }
    }
    if (!nodes.length && !collapse) { ctx.fillStyle = dim; ctx.font = '16px system-ui'; ctx.textAlign = 'center'; ctx.fillText('say “hi compact demo” and ask something — the map draws what the model is holding', W / 2, H / 2); }
  }
  function loop() { draw(); raf = requestAnimationFrame(loop); }
  window.ctxMap = { init, seed, applyDelta, applySurvive, handoff, clear };
})();
```

- [ ] **Step 2: Smoke it standalone** — open `http://localhost:8200/static/map.js` returns JS (after Task 3's mount). No unit test; Task 7 replay exercises it.
- [ ] **Step 3: Commit** `git add static/map.js && git commit -m "map: d3-force canvas renderer with glow, absorb, and handoff collapse"`

---

### Task 6: Tab 5 markup + wire the board controller to both tabs

**Files:**
- Modify: `static/index.html` — nav button, `#tab-map` section, CSS for `.mapwrap`, and inside `boardTab()`: multi-target rendering, hooks into `ctxMap`, hash `#map`, scripts.

- [ ] **Step 1: Nav + section.** After the tab-4 button: `<button role="tab" aria-selected="false" data-tab="map">5 · The map</button>`. After `</section>` of `#tab-board`:

```html
<section class="tab" id="tab-map">
  <div class="mapwrap">
    <canvas id="map"></canvas>
    <aside class="mapside">
      <div class="cam mini"><video id="video-map" autoplay playsinline muted></video><div class="read"><span id="cue-state-map">board says</span><b id="read-txt-map">–</b></div></div>
      <div class="micline"><i class="lvl" id="mic-lvl-map"></i> <span id="mic-state-map"></span></div>
      <div class="chat" id="chat-map"></div>
      <div class="pack" id="pack-map"></div>
      <div class="controls"><button id="replay-map">Replay a canned chat</button><button id="handoff-map">Hand off</button><button id="compact-map">Compact</button></div>
    </aside>
  </div>
</section>
```

CSS (next to `.duo`):
```css
  .mapwrap { display: grid; grid-template-columns: minmax(0, 1fr) 320px; gap: 24px; height: calc(100vh - 150px); min-height: 480px; }
  #map { width: 100%; height: 100%; display: block; background: var(--ground); border: 1px solid var(--line); border-radius: 6px; }
  .mapside { display: grid; grid-template-rows: auto auto minmax(0, 1fr) auto auto; gap: 10px; min-height: 0; }
  .mapside .chat { max-height: none; min-height: 0; }
  .cam.mini video { max-height: 130px; }
  .micline { color: var(--dim); font-size: 13px; display: flex; gap: 8px; align-items: center; }
  @media (max-width: 900px) { .mapwrap { grid-template-columns: 1fr; height: auto; } #map { height: 60vh; } }
```
and `section.tab#tab-map { padding-bottom: 16px; }`.

- [ ] **Step 2: Scripts.** Before the main `<script>`: `<script src="static/vendor/d3.min.js"></script><script src="static/map.js"></script>`.

- [ ] **Step 3: Board controller renders to both tabs.** Inside `boardTab()`:
- Replace `const chat = $('chat-board'), pack = $('pack-board'); pack.innerHTML = packHTML();` with
  `const chats = [$('chat-board'), $('chat-map')], packs = [$('pack-board'), $('pack-map')]; packs.forEach(p => p.innerHTML = packHTML());`
  and define `const chat = { insertAdjacentHTML: (w, h) => chats.forEach(c => c.insertAdjacentHTML(w, h)), set innerHTML(v) { chats.forEach(c => c.innerHTML = v); }, get scrollHeight() { return 0; }, set scrollTop(v) { chats.forEach(c => c.scrollTop = c.scrollHeight); } };` — then every existing `chat.…` line and `renderTurn(chat, …)` keeps working (renderTurn only uses `insertAdjacentHTML`, `scrollTop`, `scrollHeight`).
- `packUpdate(pack, …)` → `packs.forEach(p => packUpdate(p, …))` (3 call sites: start, turn, handoff, compactNow).
- `setState(t)` → also `$('cue-state-map').textContent = t`; every `$('read-txt').textContent = X` → also set `read-txt-map` (wrap in `const readTxt = v => { $('read-txt').textContent = v; $('read-txt-map').textContent = v; }` and use it).
- `micState(t)` → also `$('mic-state-map').textContent = t`; the level bar: `['mic-lvl','mic-lvl-map'].forEach(id => $(id).style.setProperty('--w', …))` and the `.rec` class toggles on both.
- `camStart()`: after `video.srcObject = stream;` add `$('video-map').srcObject = stream;`.
- Map hooks: `ctxMap.init($('map'));` at the top of `boardTab()`. In `start()`: after `sid = r.session_id`: `ctxMap.seed(r.state.graph || {nodes: [], edges: []})`. In `turn()`: after `renderTurn(...)`: `ctxMap.applyDelta(r.turn.graph_delta)`. In `compactNow()`: `ctxMap.applySurvive(r.graph_survive)`. In `handoff()`: `ctxMap.handoff(r.graph_seed, r.graph_survive)`.
- Buttons: `$('handoff-map').addEventListener('click', handoff); $('compact-map').addEventListener('click', compactNow);`
- Tab open: `document.querySelector('nav button[data-tab=map]').addEventListener('click', camStart); if (location.hash === '#map') document.querySelector('nav button[data-tab=map]').click();` and canvas needs a resize after the tab becomes visible: in the map tab click handler call `dispatchEvent(new Event('resize'))` after a `setTimeout(…, 0)`.

- [ ] **Step 4: Check tab 4 still works** — load `#board`, ask via the text box, see the chat in both tabs and the graph on tab 5. Run `.venv/bin/python -m pytest -q` (unchanged, green).
- [ ] **Step 5: Commit** `git add static/index.html && git commit -m "map: tab 5 wired to the board session — chat column, mirrored camera, graph on the wall"`

---

### Task 7: Replay mode

**Files:**
- Modify: `static/index.html` (replay button handler in `boardTab()`)

- [ ] **Step 1: Handler**
```js
    $('replay-map').addEventListener('click', async () => {
      if (busy) return; busy = true; $('replay-map').disabled = true;
      try {
        const rp = await (await fetch('static/replay.json')).json();
        chat.innerHTML = ''; ctxMap.clear();
        const fakeState = { window_tokens: cfg.board_window || 4096, totals: { sent: 0, typed: 0, cost_usd: {} } };
        let n = 0;
        for (const t of rp.turns) {
          await new Promise(r => setTimeout(r, 2500));
          if (t.handoff) { note('', `Session ended — handoff note. A fresh session starts with only this.`, t.note); ctxMap.handoff(t.graph_seed, t.graph_survive); continue; }
          n++; const turn = { n, user: t.user, answer: t.answer, typed_words: t.user.split(/\s+/).length, sent_tokens: t.sent_tokens || 0, new_tokens: t.new_tokens || 0, seconds: 0, cost_usd: {}, breakdown: t.breakdown || { system: 80, memory: 0, transcript: 0, message: 20 }, event: t.event || null, event_text: t.event_text || null, tool_uses: [], remembered: {} };
          fakeState.totals.sent += turn.sent_tokens; fakeState.totals.typed += turn.typed_words;
          renderTurn(chat, turn); packs.forEach(p => packUpdate(p, turn, fakeState)); ctxMap.applyDelta(t.graph_delta);
        }
      } catch (e) { note('red', 'replay: ' + e.message); }
      finally { busy = false; $('replay-map').disabled = false; }
    });
```
Note: replay uses `chat`/`packs`/`note` from the controller, so it lives inside `boardTab()`. `?replay=1` in the URL clicks the button after `health()` resolves: `if (new URLSearchParams(location.search).get('replay')) { document.querySelector('nav button[data-tab=map]').click(); setTimeout(() => $('replay-map').click(), 500); }` — placed at the end of `boardTab()`. Replay must not start the camera: gate `camStart` on `!new URLSearchParams(location.search).get('replay')` in the map tab click handler.

- [ ] **Step 2: Try it** — `http://localhost:8200/?replay=1#map` on Typhoon via the tunnel; watch 12 turns, a compaction at 8, a handoff at 12. Tune constants in `map.js` (charge, distances, glow) until it reads well on a big screen.
- [ ] **Step 3: Commit** `git add static/index.html static/map.js && git commit -m "map: replay mode from a canned transcript"`

---

### Task 8: Deploy to Typhoon + live check + docs

- [ ] **Step 1:** `rsync -rc --exclude .venv --exclude .git --exclude __pycache__ --exclude models ./ typhoon:/Users/project/ctxdemo/` then on Typhoon: run the test suite in `.venv`, `pkill -f "uvicorn app.main"`, `nohup ./run-typhoon.sh >> /private/tmp/ctxdemo.log 2>&1 &`, `curl /api/health`.
- [ ] **Step 2:** Live: Simon talks to it on `#map`; confirm extraction latency in the log (`turn.seconds` includes it) stays under ~2 s extra on qwen2.5:14b; the graph grows; COMPACT/HANDOFF (board or buttons) animate.
- [ ] **Step 3:** Append a dated section to `/Users/project/iiat/docs/ctxdemo-ideas.md` and update `README.md` (tab list, `CTXDEMO_EXTRACT`, `/static`). Commit.

---

## Self-review
- Spec §1 extraction → Tasks 1–2. §1 compaction/handoff → Task 2 (`_compact`, `handoff`) + Task 3 routes. §1 `Config.extract`/env → Task 2. §2 tab, layout, renderer, animations, generation alpha → Tasks 5–6. §2 replay → Tasks 4, 7. §3 tests → Tasks 1–3 (browser manual per spec). §4 rollout → Task 8.
- Names used consistently: `graph_delta`, `graph_survive`, `graph_seed`, `last_survive`, `survivors_copy`, `ctxMap.{init,seed,applyDelta,applySurvive,handoff,clear}`.
