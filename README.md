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
