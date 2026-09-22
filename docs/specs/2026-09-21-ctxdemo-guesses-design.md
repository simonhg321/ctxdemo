# ctxdemo — "The guesses" (act 6) design

_2026-09-21. DRAFT for Simon's review. First of five "see it think" pieces; build order agreed in conversation: guesses + chunks → roads not taken → thinking out loud → inside the head → concepts. Acts 1–5 untouched. Agreed so far: no live streaming this round (§5); everything is built as standalone panels (§3) so the wall can be arranged as separate frameless Chrome windows — one Chrome instance, one machine._

## Goal
Show that the model does not "know" its answer — at every step it holds a ranked list of guesses for the next chunk of text and picks one. A student sees:

1. **The chunks.** Their own sentence chopped into the pieces the model actually reads (tokens), as it drops into the backpack. "unbelievable" is three pieces; a space belongs to the word after it.
2. **The guesses.** The answer appears piece by piece, each piece coloured by how sure the model was: green = sure, amber = unsure, red = coin-flip. Tap a piece and a small bar chart shows what it almost said (`Hi` 72% · `Hello` 28%).
3. **The hesitations.** The three least-sure pieces are ringed automatically with their runner-up, so the unattended wall teaches without anyone tapping.

Words used on the wall: "piece" and "guess", not "token" and "logprob". The glossary line under the tab title gives the real terms once.

## Non-goals (this round)
Live word-by-word streaming (see §5), re-rolling from a piece (that is piece 2, "roads not taken"), thinking mode (piece 3), anything inside the model (pieces 4–5), voice/camera on this tab, any change to tabs 1–5 or to what they send to the model.

## Why this ports to the L40 unchanged
ctxdemo makes exactly one kind of model call, `POST /v1/chat/completions`, on both setups (Ollama on Typhoon, vLLM on the box). Verified 2026-09-21 on Typhoon's Ollama 0.30.7: adding `"logprobs": true, "top_logprobs": N` to that same call returns the OpenAI-format guess list per piece (`choices[0].logprobs.content[] = {token, logprob, bytes, top_logprobs[]}`). vLLM returns the same shape (its default cap is 20 alternatives; we ask for 5). So: same request, same parser, only the base URL differs.

The one real difference: vLLM can split text into pieces (`/tokenize`), Ollama cannot (404). To keep a single code path we do the splitting ourselves on both (§2).

## 1. The guesses (server)
- `app/vllm.py`
  - `ChatResult` gains `tokens: list[dict] = []`. Each item: `{"t": str, "p": float, "alts": [{"t": str, "p": float}, ...]}` — `p` is a plain 0–1 probability (`exp(logprob)`), `alts` is the top 5 including the chosen piece, sorted high to low.
  - `chat(..., peek: bool = False)`: when `peek`, add `logprobs: true, top_logprobs: 5` to the body. When not, the body is byte-for-byte what it is today.
  - `parse_logprobs(choice) -> list[dict]`: tolerant. Missing/`null` logprobs → `[]`. Piece text comes from `bytes` when present (decode UTF-8 with `errors="replace"`, so half-a-character pieces show as `�` rather than crashing), else from `token`. Never raises.
- `app/session.py`
  - `Session(peek: bool = False)`. In `turn()`, the **answer calls** are made with `peek=self.peek` (we cannot know in advance which round is the last when tools are on; the pieces kept are those of the final answer). Compaction, handoff and the map's extraction call never peek.
  - `TurnResult` gains `tokens: list[dict] = []` and `user_chunks: list[str] = []`.
- `app/main.py`: `SessReq`-style create request gains `peek: bool = False`; `/api/turn` already returns `tr.to_dict()`, so the new fields ride along. `/api/health` gains `"chunks": true|false` (§2).
- Payload size: 400 pieces × 5 alternatives ≈ 40 KB worst case. Fine.

## 2. The chunks (server)
- New module `app/chunks.py`, one class:
  - `Chunker(repo: str | None)`. Lazy-loads `tokenizers.Tokenizer.from_pretrained(repo)` on first use. `split(text) -> list[str]` encodes and slices the **original text** by the returned character offsets, so the wall shows the student's real characters (no `Ġ` markers). Any failure (library missing, no network, bad repo) → logs once, `available = False`, `split()` returns `[]`. Never raises.
- `Config` gains `tokenizer_repo: str | None` (env `CTXDEMO_TOKENIZER`). Typhoon: `Qwen/Qwen2.5-14B-Instruct`. Box: `Qwen/Qwen3-8B`. Unset → chunks strip hidden, exactly like the existing "counts are estimates" fallback.
- New dependency: `tokenizers` (small, no torch). On the box the tokenizer file is fetched **at image build** so the running container needs no internet.
- The answer's pieces need no tokenizer — they come back with the guesses.
- Honest-numbers note: the chunk count shown is for the bare sentence; the backpack bar still uses the existing counting (which includes chat-template overhead). The tab says "your sentence: 9 pieces" and does not pretend it equals the bar.

## 3. Panels (browser)
Everything is a **panel**: a tiny page that draws one thing and knows nothing about the others. Panels are arranged three ways from the same code: as separate frameless Chrome windows on the wall (`chrome --app=<url>`, drag and size until happy), frozen into one page of iframes once the arrangement is right (like `split.html`), and as tab 6 of the demo.

### 3.1 The bus
- `static/peek/bus.js`, one namespace `window.peekBus = {join(room), send(type, data), on(type, fn), last(type)}`. Built on the browser's `BroadcastChannel` (same origin, same Chrome — that is the agreed constraint; a second machine would need a server relay, not built).
- `room` comes from `?room=` (default `wall`), so two independent sets of panels can coexist.
- Messages: `turn` (the `/api/turn` result: `tokens`, `user_chunks`, `seconds`, `state`), `select` (`{index}` — which piece is in focus), `clear`. Each message carries `v: 1`.
- Late joiners: a panel opened after a turn sends `hello`; the driver re-sends the last `turn` and `select`. No server involved.

### 3.2 One page, many panels
- `static/peek/panel.html?show=<name>&room=<room>` loads `bus.js` + `static/peek/<name>.js`. Each panel module exports the same three functions: `mount(el)`, `onTurn(turn)`, `onSelect(i)`. Adding a panel = adding one file. Body has no chrome at all (no header, no tabs), fills its window, and scales type with the window (`clamp()` on viewport units) so resizing a frame on the wall just works.
- `?bg=` / `?scale=` for wall tuning; `?replay=1` makes any panel play `static/peek/replay.json` by itself, no model and no driver needed — for arranging the wall.

### 3.3 Panels in this round
| `show=` | Draws |
|---|---|
| `driver` | Input box + four "try asking" buttons chosen to make the model hesitate ("Pick a number between 1 and 10", "Write one line about fog", "Name a colour, then a fruit, then a city", "Finish this: roses are red, violets are…"). Owns the session (`{peek: true, board: true}`, typed input only), calls `/api/turn`, sends `turn`. The only panel that talks to the server. (List revised 2026-09-21 after capture: "What's the capital of Australia?" produced no hesitation at all.) |
| `chunks` | The student's sentence as alternating-tint blocks + "9 pieces". |
| `answer` | The answer revealed piece by piece, paced from the turn's real seconds ÷ piece count (capped at 8 s). Colour by `p`: ≥0.9 green, 0.5–0.9 amber, <0.5 red (existing colour tokens). Tap a piece → sends `select`. After the reveal, rings the 3 lowest-`p` pieces (ignoring whitespace-only ones) and cycles `select` through them every 4 s until someone taps. |
| `almost` | "What it almost said": bar chart of the top 5 guesses for the piece in focus. |
| `tiles` | "Sure about NN% of pieces" · "Biggest hesitation: `X` vs `Y`" · backpack fullness from `state`. |

- Alternatives sometimes appear in other languages (`巴黎` next to `Paris`). Keep them — it is a true and interesting fact about the model — with a one-line caption in `almost` the first time one shows.
- Later pieces are just more panels on the same bus: `roads` (piece 2) listens to `select` and adds a `branch` message; `scratchpad`, `layers`, `concepts` follow. Nothing above changes.

### 3.4 Tab 6 and the frozen wall
- Nav button `6 · The guesses`, `<section class="tab" id="tab-guess">`, hash `#guess`: a CSS grid of five iframes pointing at the panels, room = a per-tab random id. That is the whole tab.
- `static/peek/wall.html`: the same idea with positions read from `?layout=` (a short JSON of `{panel: [x, y, w, h]}` in % of the screen). Once the separate windows look right, their geometry is copied here and the wall opens with one URL.

## 4. Testing
- `tests/test_vllm.py`: `peek=False` body unchanged (regression guard for acts 1–5); `peek=True` adds the two fields; `parse_logprobs` on a real captured Ollama response, on `null`, on a half-character `bytes` piece.
- `tests/test_chunks.py`: `split` with a stub tokenizer (offset slicing, empty text); load failure → `available False`, `[]`, no raise.
- `tests/test_session.py`: `FakeVLLM` returns canned `tokens`; `peek` session → `TurnResult.tokens` filled and only the final call peeks; non-peek session → `tokens == []`.
- `tests/test_api.py`: create with `peek` → `/api/turn` carries `tokens` + `user_chunks`; `/api/health` reports `chunks`.
- Browser: manual — each panel alone with `?replay=1`, then driver + panels in separate `chrome --app` windows against Typhoon, then tab 6.

## 5. Decision for Simon: no live streaming in this round
In chat I floated live word-by-word streaming for this act. Having read the code, I recommend **not yet**: the app has no streaming anywhere, and a turn also does compaction, tool rounds and the map extraction — streaming means a second copy of that path. Instead the server answers as it does today and the page *replays* the pieces at the speed they were really generated. On the wall it looks the same; the cost is the same few seconds of "thinking…" that acts 1–5 already have. If that wait feels dead on the big screen, streaming becomes its own small follow-up (Ollama streaming of guesses verified working 2026-09-21).

## 6. Port checklist (box, when ready — one VPN session)
1. `curl` the box's vLLM with `logprobs: true, top_logprobs: 5` → confirm the same shape (image tag is unpinned; this is the only thing not yet seen with our own eyes).
2. Set `CTXDEMO_TOKENIZER=Qwen/Qwen3-8B` in `docker-compose.yaml`; tokenizer fetched in the Dockerfile.
3. `./deploy.sh`; open `/demo/?replay=1#guess`, then a live turn.
