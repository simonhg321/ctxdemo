# ctxdemo — "The Backpack"

A one-page demo of what a chat assistant actually receives when you press send: the context window fills,
compaction summarizes and forgets, a deliberate handoff is cheaper. Spec: `/Users/project/iiat/docs/specs/2026-09-10-ctxdemo-design.md`.

- Runs on IIAT-HACLAB-01 at `/srv/projects/ctxdemo/` (container `ctxdemo`, 127.0.0.1:8200), talks to vLLM on :8100.
- Web: https://iiat.gonzaga.edu:8443/demo/  (Caddy `handle_path /demo/*` → `host.docker.internal:8200`)
- Deploy from the Mac: `./deploy.sh`.  Tests: `.venv/bin/python -m pytest -q`.
- Knobs: `config/demo.json` (window size, compaction threshold, handoff turn), `config/prices.json`, `corpus/script.json`.

## Caddy (once)
In `/srv/data/caddy/Caddyfile`, inside the `iiat.gonzaga.edu` block:
```
	handle_path /demo/* {
		reverse_proxy host.docker.internal:8200
	}
	redir /demo /demo/ 301
```
and add `/demo /demo/*` to the `not path` line in `(common)`. Then `docker exec caddy caddy reload --config /etc/caddy/Caddyfile`.

## Act 4: the whiteboard + voice (added 2026-09-12)
- Camera reads a whiteboard (reader model `VISION_MODEL` via `VISION_URL`, default = chat model); wakes on a strip of
  green tape (browser-side, free), sleeps when the board leaves. Board commands COMPACT / HANDOFF / RESET.
- Microphone: browser voice detection → one clip per utterance → local whisper.cpp (`EARS_URL`). Wake phrase
  "hi compact demo" opens a 25 s question window (`listen_seconds`). Audio never leaves the box.
- Web search tool (DuckDuckGo HTML, no key) — results go into the backpack. Board tab window = `board_window` (4096).
- Dev loop on Typhoon: `run-typhoon.sh` (Ollama qwen2.5:14b chat — qwen3-vl always thinks under Ollama and eats the
  answer cap — + qwen2.5vl:7b reader, whisper-server :8300),
  reach via `ssh -L 8200:localhost:8200 typhoon` → http://localhost:8200/#board (camera/mic need localhost or https).
- Box: `port-to-box.sh` once on the box, then `./deploy.sh` from the Mac. Compose runs a `whisper` sidecar.

## Act 5: the map (added 2026-09-12)
- Tab 5 draws the same session as tab 4 as an Obsidian-style concept graph: one extra model call per turn extracts 3–6
  concepts (`extract`, `extract_max_tokens`; env `CTXDEMO_EXTRACT=0` turns it off). Extraction tokens are charged to the
  turn (`breakdown.extract`) so the meters stay honest.
- Compaction keeps only nodes the summary still mentions (the rest are absorbed into a surviving neighbour); handoff seeds
  the new session's graph from the note alone. Nodes that survive only on paper wash out a shade per `generation` — a
  copy of a copy — and re-mentioning resets them.
- Rendering: `static/map.js` (d3-force on canvas, d3 7.9.0 vendored in `static/vendor/`, no CDN at showtime). Chat,
  camera mirror, mic level and the meter sit in a side column; tab 4 is unchanged and drives both.
- Replay without talking: http://localhost:8200/?replay=1#map plays `static/replay.json` (12 turns, compaction at 8,
  handoff at 12). Spec: `docs/specs/2026-09-12-ctxdemo-map-design.md`; plan: `docs/plans/2026-09-12-ctxdemo-map.md`.

## Act 6 — The guesses (2026-09)
How the model reads and chooses: the sentence in pieces (tokens), the answer coloured by how sure it was, and what it almost said.
- Built from standalone panels: `static/peek/panel.html?show=driver|chunks|answer|almost|tiles&room=wall`. One Chrome, one machine (BroadcastChannel). Launch frameless: `chrome --app=<url>`; size them; then freeze the geometry into `static/peek/wall.html?layout={...}`.
- Any panel + `&replay=1` plays canned turns with no model. `driver&replay=1` replays for every open panel.
- Turn log: set `CTXDEMO_TURNLOG=/path/turns.jsonl` and every question + answer (tab, seconds, act 6 hesitation numbers, typed/voice/board) is appended as one JSON line to that file — nothing goes to the container log. Unset (the default) nothing is written anywhere, and the `hear:` transcript lines are silenced too. On the box: `/srv/projects/ctxdemo/data/logs/turns.jsonl` (`tail -f`, or `jq -r '"\(.ts)  \(.user)  →  \(.answer)"'`).
- Server: sessions created with `peek: true` ask the chat server for `logprobs` (same request on Ollama and vLLM). Chunks need `CTXDEMO_TOKENIZER` (HF repo of the chat model's tokenizer); unset → strip shows the plain sentence.
- JS helper tests: `node --test static/peek/*.test.mjs`. Spec: `docs/specs/2026-09-21-ctxdemo-guesses-design.md`.
- Personas: `config/personas/<id>.md` (title / one-line blurb / system prompt, prompt may be empty) pick who the model
  answers as; served at `GET /api/personas`, picked from the wall with `static/peek/panel.html?show=persona&room=wall`
  (not in `wall.html`'s DEFAULT layout — add it to a custom `?layout=` to place it).
- Explain bar: a chip strip fixed across the top of `wall.html`, one chip per `static/peek/explain/NN-<id>.md` (label =
  line 1, body = a tiny markdown subset) listed in order by `static/peek/explain.json` — add a chip by adding a file
  and one line there. The `who it speaks as` card's `<!-- personas -->` line renders the live persona list.
- `wall.html?bar=0` drops the explain bar entirely (script not even loaded) so the DEFAULT iframe geometry is untouched.

