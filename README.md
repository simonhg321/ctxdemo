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
- Dev loop on Typhoon: `run-typhoon.sh` (Ollama qwen3-vl:8b chat + qwen2.5vl:7b reader, whisper-server :8300),
  reach via `ssh -L 8200:localhost:8200 typhoon` → http://localhost:8200/#board (camera/mic need localhost or https).
- Box: `port-to-box.sh` once on the box, then `./deploy.sh` from the Mac. Compose runs a `whisper` sidecar.
