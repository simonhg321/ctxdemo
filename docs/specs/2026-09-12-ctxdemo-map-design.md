# ctxdemo — "The Map" (act 5) design

_2026-09-12. Approved in conversation by Simon: graph is the main stage, chat off to the side; nodes are concepts; new tab, tab 4 untouched._

## Goal
A wall-sized view of what the model is holding in its context, drawn as an Obsidian-style concept graph that grows as a human talks to the model, and that visibly shrinks on compaction and collapses-then-reseeds on handoff. Same session plumbing as tab 4 (camera, mic, wake phrase, board commands). The graph is the picture; the chat column is the evidence.

## Non-goals (this round)
Turn dots, embeddings/vector clustering, persistence across reloads, any change to tabs 1–4.

## 1. Extraction (server)
- New module `app/graph.py`:
  - `Graph` dataclass: `nodes: dict[str, Node]` (key = normalized label), `edges: dict[tuple[str,str], int]` (weight = co-mentions). `Node`: `label`, `first_n`, `mentions`, `absorbed_into: str | None`.
  - `EXTRACT_PROMPT`: given USER + ASSISTANT text, return JSON `{"concepts": ["..."], "links": [["a","b"], ...]}` with 3–6 concepts, short nouns, lower-case, no sentence. Temperature 0, `max_tokens` 200.
  - `parse_extract(text) -> (concepts, links)`: tolerant JSON parse (strip fences, take the first `{...}` block); on failure return `([], [])`. Never raises.
  - `Graph.apply(n, concepts, links) -> delta`: adds/bumps nodes (normalize: lower, strip punctuation, collapse spaces, singular-ish trim of trailing "s" only when length > 4), adds/bumps edges (sorted key, no self-edges), and links all concepts of one turn pairwise with weight 1 in addition to explicit links. Returns `{"added": [labels], "bumped": [labels], "edges": [[a,b,w]]}`.
  - `Graph.survive(text) -> delta`: for compaction/handoff. A node survives if its label (or a 5+ char prefix of it) appears in `text.lower()`. Non-survivors get `absorbed_into` = their heaviest-edged surviving neighbour, else the heaviest surviving node overall, else dropped. Returns `{"kept": [...], "absorbed": [[label, into], ...]}`.
  - `Graph.to_dict()` for state.
- `Session` gains `self.graph = Graph()`. In `turn()`, after the answer: `self._extract(user_text, r.text)` runs one `vllm.chat` call (counted into the turn's `new_tokens`/`sent_tokens` so the meters stay honest, and flagged in the breakdown as `"extract"`), then `self.graph.apply(...)`. Extraction is skipped when `answer is None` (over-limit) and never raises (any error → empty delta, logged).
- Compaction: after `_compact()` sets the summary, `self.graph.survive(summary)`. Handoff: `new.graph` = a fresh `Graph` seeded with the old graph's survivors against the note (`survive(note)` on a copy, keep only survivors, reset `absorbed_into`).
- `TurnResult` gains `graph_delta: dict` (from `apply`, plus `"survive"` sub-delta when the turn compacted). `state()` gains `"graph": self.graph.to_dict()`. `/api/handoff` response adds `"graph_seed": new.graph.to_dict()` and `"graph_survive": delta`.
- `Config` gains `extract_max_tokens: int = 200` and `extract: bool = True` (env `CTXDEMO_EXTRACT=0` turns it off for tests/CI).

## 2. The Map tab (browser)
- New `<section class="tab" id="tab-map">` and nav button `5 · The map`; `#map` hash opens it and starts camera + mic exactly like `#board`.
- Layout: CSS grid, `1fr 320px` (wall) collapsing to a single column under 900px. Left: `<canvas id="map">` full height. Right column, top to bottom: mic/camera status strip (reuse the tab-4 elements by moving the mic/cam controller into shared functions `micStart/camStart(targetIds)` — tab 4 keeps working), chat log, backpack meter, cost tiles.
- Rendering: `d3-force` 3.x from cdnjs (UMD) on a 2D canvas, `requestAnimationFrame` loop. Node radius `6 + 3*sqrt(mentions)`, edge width `0.5 + 0.6*weight`, label drawn under the node once radius > 8 or hovered. Colours from the existing tokens (`--moss` accent, `--ink`). New nodes: 2 s glow ring. Absorbed nodes: tween to their target over 1.2 s then fade; the target pulses once. Handoff: all nodes tween to centre and fade over 1.5 s into a single "note" node; then survivors unfold from centre with the glow.
- Data flow: page keeps its own `nodes/links` arrays for d3; `applyDelta(turn.graph_delta)` after each turn; `applySurvive(delta)` on compaction/handoff. On page load or session restore: `state.graph` seeds the arrays.
- Replay mode: `?replay=1` (or a `Replay` button in the column) plays `static/replay.json` (a canned 12-turn transcript with pre-baked deltas) at 1 turn per 2.5 s, no model needed. Used to tune the animation.

## 3. Testing
- `tests/test_graph.py`: `parse_extract` (clean JSON, fenced JSON, garbage → empty); `apply` (adds, bumps, pairwise edges, normalization); `survive` (kept vs absorbed, neighbour choice, drop when nothing survives).
- `tests/test_session.py`: FakeVLLM gains a response queue that answers the extraction call; assert `graph_delta` on turns, graph shrinks on compaction, handoff seeds from the note; assert extraction tokens land in the turn totals; `extract=False` → no extra call.
- `tests/test_api.py`: `/api/turn` returns `graph_delta`; `/api/handoff` returns `graph_seed`; `/api/session/{sid}` state carries `graph`.
- Browser: manual via replay mode on Typhoon; not automated.

## 4. Rollout
- Typhoon dev first (qwen2.5:14b handles the extraction prompt in ~1 s). Box unchanged until Simon says.
