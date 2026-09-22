# ctxdemo — "Roads not taken" (piece 2) design

_2026-09-22. DRAFT for Simon's review. Second of five "see it think" pieces. Act 6 as shipped is the base; nothing in acts 1–5 changes. Same rules as piece 1: standalone panel on the bus, plain words on the wall, one Chrome._

## Goal
Act 6 shows that at every piece the model held a ranked list and picked one. Piece 2 answers the question a student asks next: **"what if it had picked the other one?"** Tap a runner-up in *what it almost said* and the wall shows the answer the model would have written from that point on — the road it did not take.

What a student sees: the answer so far in its normal colours up to the tapped piece; the tapped piece swapped for the runner-up, marked; then the continuation in a second voice (ice blue), coloured by certainty like everything else. Heading: *"If it had said `X` instead of `Y`…"*. Often the road converges back to the same answer (the model recovers). Sometimes it goes somewhere completely different (Monty Hall: "Yes" vs "No" at piece 1). Both are the lesson: the answer is a path, not a fact.

## Non-goals
Branching from anything but the most recent answer; branching more than one level deep; streaming; changing what the session sends afterward (a road is a side trip — it never enters the backpack); anything for acts 1–5.

## 1. How a road is generated (server)
One extra model call, outside the session's history. The conversation as it stood before the answer, plus the answer's pieces up to the tapped one, plus the runner-up, handed to the model as an **unfinished assistant message** to continue.

- vLLM: `POST /v1/chat/completions` with the transcript, a final `{"role":"assistant","content": prefix}` and `"continue_final_message": true, "add_generation_prompt": false` (documented vLLM extras). Same `logprobs`/`top_logprobs` flags, so the road is coloured too.
- Ollama (dev on Typhoon): its OpenAI endpoint ignores those two extras. Step 1 of the build is a **spike**: send a trailing assistant message and check whether Ollama continues it or starts over. If it starts over, dev uses vLLM on the box directly (attended) and the laptop copy shows roads only in replay.
- `app/vllm.py`: `chat()` gains `prefix: str | None = None`; when set, appends the assistant message and the two extras. Body without `prefix` stays byte-for-byte what it is today (regression guard).
- `app/session.py`: `Session.road(index: int, alt: str) -> RoadResult` — looks at the last `TurnResult` with tokens; `prefix = "".join(t["t"] for t in tokens[:index]) + alt`; messages = `self.messages` as they were sent for that turn (the session keeps `last_sent_messages`); `max_tokens` = min(300, cfg.answer_max_tokens); `peek=True`. Returns `{index, alt, was, prefix, text, tokens, cut, seconds}`. Not appended to the transcript, not counted in `total_sent`/`total_new` (a small "side trips: N · M pieces" counter on the tiles keeps the meters honest). Raises `ValueError` if `index` is out of range or `alt` is not one of that piece's alts (no free-text injection).
- `app/main.py`: `POST /api/road {session_id, index, alt}` → the RoadResult. 400 on ValueError, 502 on model error (existing pattern). Logged to the turn log as `{"road": {...}}` when the log is on.

## 2. Panels (browser)
- **`almost`** (existing): every bar becomes tappable. Tapping the chosen piece does nothing; tapping a runner-up sends `road` `{index, alt}` on the bus and shows "…" in the road panel. Bars get a small `→` affordance and the caption gains one line: *tap a runner-up to see where that road goes*.
- **`driver`** (existing, owns the session): listens for `road`, calls `/api/road`, sends `roadresult` (the RoadResult) — the only panel that talks to the server stays the only one. Caches by `(turn n, index, alt)` so re-taps are free; cache cleared on `turn`/`clear`.
- **`roads`** (new, `panel.html?show=roads`): renders `roadresult`: the original pieces `[0, index)` in their normal tones, then the swapped piece with a ring and strike-through of the original (`~~Yes~~ No`), then the road's pieces in ice blue, coloured by `p` as usual, revealed at the real pace. Heading *If it had said `X` instead of `Y`…*; footer: *converged back* (if the road's text ends with the same last sentence as the original) or *went somewhere else*. Empty state: *tap a runner-up in "what it almost said"*.
- **`answer`** (existing): when a `roadresult` arrives, dims pieces after `index` so the eye jumps to the roads panel; a new `turn`/`select` restores. No other change.
- **`wall.html`**: the roads panel joins DEFAULT below *what it almost said* (right column: persona 3–46%, almost 51–20%, roads 73–24%; tiles unchanged). Frozen layouts via `?layout=` still work.
- **Explain chip** `35-roads.md`: what a road is, why the model can recover (each piece is predicted from everything before it, so a wrong word often gets absorbed), and why sometimes it cannot (the first word of a yes/no answer decides the rest).

## 3. Testing
- `tests/test_vllm.py`: `chat(prefix=…)` body has the trailing assistant message and the two extras; without `prefix` the body is unchanged.
- `tests/test_session.py`: `road()` builds the right prefix from the fake's tokens; rejects a bad index / an alt not in the list; does not change `transcript`, `total_sent`, `total_new`; side-trip counters increment.
- `tests/test_api.py`: `/api/road` round trip on a peek session; 400 on bad alt; 404 on no such session; `roads.js` + `35-roads.md` served.
- `lib.test.mjs`: `roadModel(tokens, road)` → the three segments (before / swapped / after) and the converged flag.
- Browser: headless render of `roads` with a canned `roadresult` in `replay.json`; then live on the box.

## 4. Open questions for Simon
1. **Road length.** 300 pieces keeps a road under ~10 s on the L40. Long enough for Monty Hall; too short for a country list, which is fine — the lesson is at the fork.
2. **Auto-road on the wall.** When nobody taps, should the unattended wall walk the biggest hesitation's runner-up on its own after the reveal (like the rings cycle)? Recommended yes, one auto-road per turn, so the panel is never empty.
3. **Name on the wall.** *Roads not taken* vs *What if it had said…*. The chip can carry both.

## 5. Order of work
Spike (Ollama prefill, 15 min) → server (`prefix`, `road()`, endpoint) → `roads` panel + `almost` taps + driver plumbing → wall layout + chip → deploy → live on the box with Monty Hall.
