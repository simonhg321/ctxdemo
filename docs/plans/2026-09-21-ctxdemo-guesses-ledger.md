# SDD ledger — plan: docs/plans/2026-09-21-ctxdemo-guesses.md
Spec: docs/specs/2026-09-21-ctxdemo-guesses-design.md · branch `guesses` (from `map` @12d6a06; docs commit 2db88e1) · started 2026-09-21 10:08 PDT
Ruling: work in place on a new branch `guesses`, no worktree — the plan's commands use the repo's `.venv`, and acts 1–5 stay behaviour-identical so an accidental deploy from this tree is harmless — cost if wrong: Simon deploys a half-built tab 6 (hidden behind a nav button).
Note: `.superpowers/` added to .git/info/exclude (local only). deploy.sh rsync does not exclude it — workspace is deleted at finish; do not deploy mid-build.
Ruling: commits carry the `Co-Authored-By: Claude Fable 5.1` trailer (session attribution rule) — cost if wrong: cosmetic.

## Pre-flight scan
| Tasks | Produces → consumes | Finding |
|---|---|---|
| 1→3 | `chat(..., peek=)`, `ChatResult.tokens` → Session passes `**_peek_kw()`, reads `r.tokens` | agree |
| 2→3 | `Chunker.split/.available`, `Config.tokenizer_repo` → `create_app(chunker=)`, health `chunks` | agree |
| 3→6 | `/api/session {peek}`, `/api/turn {turn.tokens,user_chunks}, state{window_tokens,next_would_send}` → driver.js | agree (state keys exist in Session.state()) |
| 4→5,6 | `peekLib`, `peekBus`, `peekPanels`, `peekStopCycle`, msg `{turn,state}` → panels | agree; answer.js click: self-replay paints locally, else bus (plan fixed before start) |
| 4,5,6→7 | panel.html query params → wall.html/index.html iframes | agree |
| 4→8 | replay.json shape → real capture keeps same keys | agree |
| 3 (self) | FakeVLLM.calls gains key `peek` | RISK: an existing test may compare whole call dicts. Ruling: if so, implementer updates that assertion to include `"peek": False` — behaviour unchanged — cost if wrong: none |
| 1 (self) | tests vs code: exp(-0.3289)=0.7197, exp(-1.2719)=0.2803, exp(-0.1)=0.9048; "garbage" string → AttributeError caught → [] | agree |
| 2 (self) | `tokenizers==0.22.*` pin may not exist | plan already tells implementer to take newest 0.2x and record it |
| 5,7 (self) | headless-Chrome screenshot steps need a GUI Chrome | implementer may skip if Chrome absent and must say so; controller verifies visually at the end |
| 8 | needs ssh tunnel to Typhoon + rsync to Typhoon | Step 2 (rsync to Typhoon) is a side effect outside the repo → controller asks Simon; not dispatched |

## Tasks
Task 1: note — plan's test handler always returned logprobs, which would have failed `plain.tokens == []`; implementer made the mock return logprobs only when asked (reviewer: correct fix of a plan bug).
Task 1: minor (deferred): app/vllm.py ~71-74 chosen-piece dedup uses dict equality (`me not in alts`); fragile if alt dicts ever gain keys.
Task 1: complete (commits 2db88e1..9c78b92, review clean)
Task 2: ⚠️ resolved by controller — no test for Config.load() reading CTXDEMO_TOKENIZER; sibling env vars have no tests either, brief did not ask; not a gap. minor (deferred): add a config-load env test.
Task 2: complete (commits 9c78b92..f457098, review clean; tokenizers 0.22.2)
Task 3: minor (deferred): tests/test_session.py:3 unused `from app.chunks import Chunker` (plan told the implementer to add it).
Task 3: minor (deferred): tool-loop answer call's peek is verified by inspection only; no test with tools on + peek.
Task 3: complete (commits f457098..3ec3d97, review clean; 63 tests)
Task 4: review → Needs fixes. Important (plan-mandated): panel.html autoSelect's initial setTimeout is untracked; a turn arriving before it fires lets the stale timeout fire with old indices and orphan the running interval (leak on an unattended wall).
Ruling: the finding is right and the plan text is wrong — fix it: track the pending timeout id and clear it in stopCycle() — spec §3.3 wants a 4 s hesitation cycle that survives hours unattended — cost if wrong: none (strictly safer).
Task 4: minor (deferred): `?bg=` is set as an inline style unsanitised (operator-only knob).
Task 4: note — reviewer called `window.peekStopCycle` undocumented; it is in the plan's panel.html code and Task 5 consumes it. No action.
Task 4: fix round 1/5 (1 addressed, 0 open — autoSelect pending timeout tracked + cleared; commits 91dce15..79fe9e9)
Task 4: complete (commits 3ec3d97..79fe9e9, review clean after 1 fix round)
Task 5: implementer DONE_WITH_CONCERNS (commit 7c1a6bf). Controller looked at the screenshots before review; three correctness problems, two of them plan defects:
Ruling: `hesitations()` must only return pieces with p < 0.9 — the plan's "3 lowest" ringed and toured pieces the model was 100% sure of ("Hi there!" ringed all three) — spec goal is "the hesitations", so sure pieces are not hesitations — cost if wrong: an all-sure answer shows no rings (that is the honest picture).
Ruling: ring/focus must not use `outline` + offset on inline spans (they overlap neighbours and cover letters on the wall); use inset box-shadow — cost if wrong: cosmetic.
Task 5: finding — almost.js `foreign()` regex was NOT verbatim: the ` ` escape became a plain space, making the class U+0020–U+206F, so Arabic/most scripts are never flagged and the language note never shows. Restore the escapes.
Task 5: pre-review fix round (3 addressed: hesitations p<0.9, inset rings, regex escapes restored; commits 7c1a6bf..1c7533e)
Task 5: note — tooling decodes `\uXXXX` escapes in tool-call strings into literal chars when writing files; verify bytes with od for any file that needs escapes.
Task 5: minor (deferred): almost.js `#note` (other-languages caption) is never cleared on `clear`.
Task 5: minor (deferred): peek.css — a piece that is both .ring and .focus shows only the focus shadow (ring colour hidden).
Task 5: complete (commits 79fe9e9..1c7533e, review clean)
Task 6: implementer DONE_WITH_CONCERNS (commit 4d3301d). Live turn vs Typhoon qwen2.5:14b OK: 10 chunks, pieces with p=0.5066/0.5237/0.9037, ~4 s.
Ruling: the JS test command is `node --test static/peek/*.test.mjs` — on node 26 the bare-directory form fails with MODULE_NOT_FOUND — Task 7's README line and verification use the glob form — cost if wrong: none.
Task 6: review → Needs fixes. Two Important (plan-mandated), both in the hello/late-join handler: (1) after "Start over" a late joiner is sent the pre-reset turn (bus cache is never cleared); (2) the cached `select` is not tied to the cached `turn`, so a late joiner can get the previous turn's index against the new turn.
Ruling: both findings are right; the plan's code is wrong — the driver keeps its own `lastTurn`/`lastSelect` (select reset to null on every new turn, both reset on Start over) and the hello handler uses those instead of `peekBus.last()` — spec §3.1 says late joiners get "the last turn and select", which only makes sense for the current turn — cost if wrong: none.
Task 6: also taking the reviewer's minor now (1 line): do not wipe the input box when the request failed.
Task 6: minor (deferred): in `?replay=1` the ask form stays live, so a real turn can interleave with canned ones.
Task 6: fix round 1/5 (3 addressed, 0 open — driver owns lastTurn/lastSelect; input kept on failure; commits 4d3301d..3858d0c)
Task 6: complete (commits 1c7533e..3858d0c, review clean after 1 fix round). Tunnel to Typhoon Ollama left up on 127.0.0.1:11436 (pid 14486) for Task 8.
Task 7: implementer DONE (commit 5c565cc; 64 py / 5 js). Controller looked at the screenshots: the bus feeds all five iframes (first cross-panel proof), tabs 1–5 intact, tab 1 still default. Two layout defects, both from the plan:
Ruling: the tiles panel must lay its three tiles out in a ROW that wraps (in the default wall layout the strip is wide and short, the third tile "backpack full" was cut off) — spec §3.3 lists three tiles; a hidden one is a missing requirement — cost if wrong: cosmetic.
Ruling: the answer and the chunks strip are the hero content and must be larger than the captions (answer 1.8em, scrolls inside its panel if long; chunks 1.5em) — at wall distance 15 px body text in a 960 px frame is unreadable — cost if wrong: Simon retunes with ?scale=.
Task 7: pre-review fix round (2 addressed: tiles wrap in a row, answer/chunks hero text; commits 5c565cc..6a96253). Screenshots: /private/tmp/claude-501/peek-shots/4-wall-fixed.png, 6-tiles-500-uncropped.png. Note: headless Chrome here floors viewport width at 500 px, so <500 px wrap is unverified (low risk).
Task 7: NEXT = dispatch the task review over 3858d0c..6a96253 (brief task-7-brief.md + the two layout rulings + the node-glob ruling). NOT yet dispatched — SAVE POINT 2026-09-21 11:37, Simon paused the session.
Task 7: review dispatched 17:15 over 3858d0c..6a96253 (build resumed after HACLab reboot)
Task 7: minor (deferred): tests/test_api.py `src="/` assertion is vacuous (wall.html sets src in JS) — plan-mandated.
Task 7: complete (commits 3858d0c..6a96253, review clean after 1 pre-review fix round)
Task 8: controller runs the capture itself (one script against the already-running :8222 instance on Typhoon's Ollama); rsync to Typhoon needs Simon's OK.
Ruling: replay prompts changed from the plan's (Australia / roses were 100% sure → dull) to "Write one line about fog" + "Name a colour, then a fruit, then a city" — spec wants hesitations to ring — cost if wrong: none.
Note: pytest prints 287 warnings; base branch `map` prints 248 for 52 tests — pre-existing FastAPI/httpx deprecation noise (fastapi/routing.py), not introduced here. Deferred.
Task 8: replay captured + committed (bc12b2a). Remaining: rsync to Typhoon (Simon's OK), final whole-branch review.
FINAL REVIEW (opus, 12d6a06..bc12b2a): Needs fixes — 2 Important + 2 triaged FIX NOW; all hard constraints PASS; container tokenizer prefetch verified to work offline.
Ruling: swap the two all-sure "try asking" prompts for the Task-8-proven ones and amend spec §3.3 — spec's own stated goal ("chosen to make the model hesitate") beats its literal list — cost if wrong: none.
Ruling: Dockerfile takes ARG CTXDEMO_TOKENIZER fed from compose build.args so one value drives prefetch + runtime.
Triage: FIX NOW #3 (unused import), #9 (vacuous src="/ assertion → real one); LEAVE 1,2,4,5,6,7,8,10 per reviewer reasoning. Also taking the wall.html try-widening (1 line) and sendTurn trimming state to the two keys (matches replay.json) as part of the same wave.
Final fix wave: 296505e (5/6 addressed) + 6f67e5a (controller one-liner for residual #4: layout validation also rejects scalars/empty objects; proven on 8 inputs).
Ruling: residual #4 fixed by the controller directly rather than a second dispatch — one condition, operator-only knob, diff-visible — cost if wrong: none.
FINAL: mergeable. Workspace deleted after this line; rulings summarised to Simon.
