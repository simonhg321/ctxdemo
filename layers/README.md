# layers — "inside the head" sidecar (ctxdemo piece 4)

Loads a small sibling (default `Qwen/Qwen3-4B`) with TransformerLens and, per request, runs ONE forward pass over
the prompt the wall sent, reading the next-token guess at every layer (logit lens) and where the last position
looked (attention, heads averaged, sink dropped). Spec: `../docs/specs/2026-09-23-ctxdemo-layers-design.md`.

- Run on HACLab: `./run-haclab.sh` from the Mac → `/srv/projects/ctxdemo-layers`, port 8400 on localhost + docker bridge.
- ctxdemo side: `LAYERS_URL=http://host.docker.internal:8400` on the ctxdemo container; `/api/health` shows `layers`.
- API: `GET /health` → `{model, n_layers, device, busy}`; `POST /layers {messages|prompt, prefix, top_k, max_tokens}` →
  `{tokens, final:{t,p}, layers:[{n, top:[{t,p}]}], decided_at, attention:[{layer, weights}], cut, model, n_layers, seconds}`.
- Tests (no GPU): `python -m pytest layers/tests -q` from the repo root.
- VRAM: ~8 GB for the 4B in bf16 + activations. Stop it (`docker compose down`) to hand the memory back.
- Resolved set on the spike box: transformer-lens 3.9.0, transformers 5.17.0, torch 2.8.0+cu128.
