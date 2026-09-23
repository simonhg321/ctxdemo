# "Inside the head" (piece 4: layers) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A GPU sidecar reads a Qwen3-4B sibling layer by layer (logit lens + attention) for the prompt the wall just sent, and a new `layers` panel shows where the answer's first token — or any tapped token — was decided.

**Architecture:** `layers/` is a standalone FastAPI + TransformerLens service in its own compose file (like vLLM and the vision model on HACLab), bound to `127.0.0.1:8400` + `172.17.0.1:8400`. ctxdemo gains `LAYERS_URL`, a `POST /api/layers` that sends the session's real messages + answer prefix to the sidecar, and a `layers` panel on the existing BroadcastChannel bus that asks on `turn` (index 0) and on `select` (index i). Nothing runs inside a turn; if the sidecar is down the panel says so and the wall is unaffected.

**Tech Stack:** Python 3.12, FastAPI, httpx, pytest (ctxdemo, `.venv/bin/python -m pytest -q`); sidecar: `pytorch/pytorch:2.8.0-cuda12.8-cudnn9-runtime` base, `transformer_lens==3.9.*`, `transformers`, `fastapi`, `uvicorn`; browser: vanilla JS panels, `node --test static/peek/lib.test.mjs`.

**Spec:** `docs/specs/2026-09-23-ctxdemo-layers-design.md` (decisions §5: Qwen3-4B, auto-analyse first token, separate compose).

## Global Constraints

- Words on the wall come from `peekLib.words()` (pieces/tokens) — never hard-code "pieces" or "tokens" in new panel copy; captions from the spec: *the model, layer by layer* · *a 4B sibling of the model you are talking to* · *decided here* · *where it looked* · *how it chose "X"*.
- Relative URLs only in `static/peek/*` (`'../../api/…'`), the app lives under `/demo/` behind Caddy and under `/presenter/` on the Linode.
- The sidecar never blocks a turn: `/api/layers` is a separate request made by the panel after the answer arrives.
- The sidecar is **not** part of `docker-compose.yaml` at the repo root; it has its own `layers/docker-compose.yaml`.
- Sidecar model: `LAYERS_MODEL` env, default `Qwen/Qwen3-4B`, bf16, HF cache at `/mnt/data/hf` on HACLab.
- Every commit message ends with the two attribution lines used in this repo (`Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>` and `Claude-Session: https://claude.ai/code/session_015zajUa5bvxaQ3mdsWe7Snf`).
- Tests: ctxdemo suite stays green (`.venv/bin/python -m pytest -q`, 110 at the start of this plan; `node --test static/peek/lib.test.mjs`, 20). Sidecar tests run with plain `python -m pytest layers/tests -q` and need **no GPU and no model download**.

## File structure

```
layers/                         NEW — the sidecar, self-contained
  README.md                     what it is, how to run, the API
  Dockerfile
  docker-compose.yaml           service `layers`, gpus all, 127.0.0.1:8400 + 172.17.0.1:8400, /mnt/data/hf cache
  requirements.txt
  lens.py                       pure functions: decided_at, attention heat (sink dropped), prompt cut — no torch
  engine.py                     Engine: loads the model (TransformerBridge) and runs one forward pass; the torch part, injectable for tests
  server.py                     FastAPI: GET /health, POST /layers (asyncio.Lock)
  tests/test_lens.py            pure-function tests
  tests/test_server.py          API tests with a stub engine
app/config.py                   + layers_url (env LAYERS_URL)
app/main.py                     + health.layers, POST /api/layers
tests/test_api.py               + /api/layers tests with a fake sidecar
static/peek/lib.js              + layersModel(resp, wallToken), attentionHeat(weights)
static/peek/lib.test.mjs        + tests for both
static/peek/layers.js           NEW panel
static/peek/peek.css            + .layers styles
static/peek/explain/45-layers.md  NEW chip; static/peek/explain.json + one entry
static/peek/wall.html           + ?with=layers layout
docker-compose.yaml             + LAYERS_URL for the HACLab ctxdemo (the Gonzaga compose at the repo root)
```

---

### Task 1: Sidecar pure functions (`layers/lens.py`)

**Files:**
- Create: `layers/lens.py`, `layers/tests/__init__.py` (empty), `layers/tests/test_lens.py`, `layers/requirements.txt`

**Interfaces:**
- Produces: `decided_at(tops: list[str]) -> int | None` — `tops[i]` is layer i's top-1 token string (i from 0); returns the 1-based layer number from which the top-1 equals the final layer's top-1 for every remaining layer; `None` for an empty list.
- Produces: `heat(weights: list[float], drop_first: bool = True) -> list[float]` — attention weights over prompt positions, first position (the attention sink) zeroed when `drop_first`, then scaled so the max is 1.0 (all zeros stay zeros).
- Produces: `cut_front(ids: list[int], max_tokens: int) -> list[int]` — keeps the LAST `max_tokens` ids.

- [ ] **Step 1: Write the failing tests**

```python
# layers/tests/test_lens.py
from layers.lens import decided_at, heat, cut_front


def test_decided_at_is_the_first_layer_of_the_stable_suffix():
    assert decided_at(["the", "a", "Paris", "Paris", "Paris"]) == 3        # layers are 1-based on the wall
    assert decided_at(["Paris", "Paris"]) == 1
    assert decided_at(["a", "b", "Paris"]) == 3                              # decided at the very last layer
    assert decided_at(["Paris", "b", "Paris"]) == 3                          # an early agreement that flips does not count
    assert decided_at([]) is None


def test_heat_drops_the_sink_and_scales_to_one():
    assert heat([0.9, 0.05, 0.05]) == [0.0, 1.0, 1.0]
    assert heat([0.9, 0.05, 0.05], drop_first=False) == [1.0, 0.05 / 0.9, 0.05 / 0.9]
    assert heat([1.0]) == [0.0]                                              # a one-token prompt: nothing to look at
    assert heat([]) == []


def test_cut_front_keeps_the_end():
    assert cut_front([1, 2, 3, 4, 5], 3) == [3, 4, 5]
    assert cut_front([1, 2], 3) == [1, 2]
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd /Users/project/iiat/ctxdemo && .venv/bin/python -m pytest layers/tests/test_lens.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'layers.lens'`

- [ ] **Step 3: Implement**

```python
# layers/lens.py
"""Pure helpers for the layers sidecar. No torch here, so they test anywhere."""
from __future__ import annotations


def decided_at(tops: list[str]) -> int | None:
    """1-based layer from which the top-1 guess equals the final layer's and never changes again."""
    if not tops:
        return None
    final = tops[-1]
    n = len(tops)
    while n > 1 and tops[n - 2] == final:
        n -= 1
    return n


def heat(weights: list[float], drop_first: bool = True) -> list[float]:
    """Attention over prompt positions as 0..1 shades. The first token is an attention sink: drop it."""
    w = [float(x) for x in weights]
    if drop_first and w:
        w[0] = 0.0
    m = max(w) if w else 0.0
    return [x / m for x in w] if m > 0 else [0.0 for _ in w]


def cut_front(ids: list[int], max_tokens: int) -> list[int]:
    """Keep the end of a long prompt: the question and the answer so far are what matter."""
    return ids[-max_tokens:] if max_tokens > 0 and len(ids) > max_tokens else list(ids)
```

```
# layers/requirements.txt
fastapi>=0.115
uvicorn[standard]>=0.30
transformer_lens>=3.9,<4
transformers>=4.51
accelerate>=1.0
```

Also create the empty `layers/__init__.py` and `layers/tests/__init__.py` so `from layers.lens import …` resolves from the repo root.

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest layers/tests/test_lens.py -q`
Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add layers/__init__.py layers/lens.py layers/requirements.txt layers/tests/
git commit -m "layers: pure helpers — decided_at, attention heat (sink dropped), cut_front

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_015zajUa5bvxaQ3mdsWe7Snf"
```

---

### Task 2: Sidecar engine with an injectable runner (`layers/engine.py`)

**Files:**
- Create: `layers/engine.py`, `layers/tests/test_engine.py`

**Interfaces:**
- Produces: `class Engine(model_name: str, device: str = "cuda", loader=None)` where `loader(model_name, device) -> Runner`.
- `Runner` protocol (what the real loader returns and what tests stub): attributes `n_layers: int`, `tokenizer` (has `apply_chat_template(messages, tokenize=False, add_generation_prompt=True, enable_thinking=False)`, `encode(text, add_special_tokens=False) -> list[int]`, `decode(ids) -> str`, `convert_ids_to_tokens(ids) -> list[str]`), and method `forward(ids: list[int]) -> tuple[list[list[tuple[str, float]]], list[list[float]]]` returning, per layer, the top-k `(token, prob)` at the last position, and per layer the last position's attention row over the prompt (heads averaged).
- Produces: `Engine.analyze(messages: list[dict] | None, prompt: str | None, prefix: str = "", top_k: int = 5, max_tokens: int = 1536) -> dict` with keys `tokens, final, layers, decided_at, attention, model, n_layers, cut`.

- [ ] **Step 1: Write the failing test**

```python
# layers/tests/test_engine.py
from layers.engine import Engine


class StubTok:
    def apply_chat_template(self, messages, tokenize=False, add_generation_prompt=True, enable_thinking=False):
        return "".join(f"<{m['role']}>{m['content']}" for m in messages) + "<assistant>"
    def encode(self, text, add_special_tokens=False): return [ord(c) for c in text]
    def decode(self, ids): return "".join(chr(i) for i in ids)
    def convert_ids_to_tokens(self, ids): return [chr(i) for i in ids]


class StubRunner:
    n_layers = 3
    tokenizer = StubTok()
    seen = None
    def forward(self, ids):
        StubRunner.seen = list(ids)
        tops = [[("a", 0.3), ("b", 0.2)], [("Yes", 0.5), ("a", 0.1)], [("Yes", 0.9), ("No", 0.05)]]
        attn = [[0.8, 0.1, 0.1] + [0.0] * (len(ids) - 3)] * 3
        return tops, attn


def make(): return Engine("stub/model", device="cpu", loader=lambda name, device: StubRunner())


def test_analyze_from_messages_applies_the_chat_template_and_the_prefix():
    r = make().analyze(messages=[{"role": "user", "content": "hi"}], prefix="Ye")
    assert r["model"] == "stub/model" and r["n_layers"] == 3
    assert "".join(r["tokens"]) == "<user>hi<assistant>Ye"                  # template + the answer so far
    assert r["final"] == {"t": "Yes", "p": 0.9}
    assert [l["n"] for l in r["layers"]] == [1, 2, 3] and r["layers"][1]["top"][0] == {"t": "Yes", "p": 0.5}
    assert r["decided_at"] == 2
    assert [a["layer"] for a in r["attention"]] == [1, 2, 3]                # early / decided / last (3 layers: all of them)
    assert r["attention"][0]["weights"][0] == 0.0 and max(r["attention"][0]["weights"]) == 1.0   # sink dropped, scaled
    assert r["cut"] is False


def test_analyze_from_a_raw_prompt_cuts_the_front():
    r = make().analyze(prompt="x" * 50, max_tokens=10)
    assert len(r["tokens"]) == 10 and r["cut"] is True and len(StubRunner.seen) == 10


def test_analyze_needs_messages_or_prompt():
    import pytest
    with pytest.raises(ValueError):
        make().analyze()
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest layers/tests/test_engine.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'layers.engine'`

- [ ] **Step 3: Implement**

```python
# layers/engine.py
"""The torch part of the sidecar: load a small model once, run one forward pass with hooks, read the guess at
every layer (logit lens) and where the last position looked (attention). The real loader is TransformerLens'
TransformerBridge; tests inject a stub so nothing here needs a GPU."""
from __future__ import annotations
import logging, time
from .lens import decided_at, heat, cut_front

log = logging.getLogger("layers")


def tl_loader(model_name: str, device: str):
    """The real thing: TransformerLens 3.x over a HF model (verified with Qwen3-1.7B on the Mac, 2026-09-21)."""
    import torch
    from transformer_lens.model_bridge import TransformerBridge

    class TLRunner:
        def __init__(self):
            t0 = time.time()
            self.m = TransformerBridge.boot_transformers(model_name, device=device, dtype=torch.bfloat16)
            self.tokenizer = self.m.tokenizer
            self.n_layers = self.m.cfg.n_layers
            log.info("loaded %s on %s in %.1fs (%d layers)", model_name, device, time.time() - t0, self.n_layers)

        @torch.no_grad()
        def forward(self, ids):
            toks = torch.tensor([ids], device=device)
            _, cache = self.m.run_with_cache(toks)
            tops, attn = [], []
            for i in range(self.n_layers):
                h = cache[f"blocks.{i}.hook_resid_post"][0, -1:].unsqueeze(0)
                p = self.m.unembed(self.m.ln_final(h))[0, -1].float().softmax(-1)
                top = p.topk(5)
                tops.append([(self.tokenizer.decode([int(j)]), round(float(v), 4)) for v, j in zip(top.values, top.indices)])
                pat = cache[f"blocks.{i}.attn.hook_pattern"][0].float().mean(0)[-1]     # heads averaged, last query position
                attn.append([round(float(x), 5) for x in pat.tolist()])
            return tops, attn
    return TLRunner()


class Engine:
    def __init__(self, model_name: str, device: str = "cuda", loader=None):
        self.model_name, self.device = model_name, device
        self.runner = (loader or tl_loader)(model_name, device)

    @property
    def n_layers(self) -> int:
        return self.runner.n_layers

    def analyze(self, messages=None, prompt=None, prefix: str = "", top_k: int = 5, max_tokens: int = 1536) -> dict:
        tok = self.runner.tokenizer
        if messages:
            text = tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True, enable_thinking=False) + prefix
        elif prompt is not None:
            text = prompt + prefix
        else:
            raise ValueError("messages or prompt required")
        ids_all = tok.encode(text, add_special_tokens=False)
        ids = cut_front(ids_all, max_tokens)
        tops, attn = self.runner.forward(ids)
        top_strs = [t[0][0] for t in tops]
        dec = decided_at(top_strs)
        L = len(tops)
        picks = sorted({1, dec or L, L})                                    # early / decided / last, 1-based
        return {"model": self.model_name, "n_layers": L, "tokens": tok.convert_ids_to_tokens(ids), "cut": len(ids) < len(ids_all),
                "final": {"t": tops[-1][0][0], "p": tops[-1][0][1]},
                "layers": [{"n": i + 1, "top": [{"t": t, "p": p} for t, p in tops[i][:top_k]]} for i in range(L)],
                "decided_at": dec,
                "attention": [{"layer": n, "weights": heat(attn[n - 1])} for n in picks]}
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest layers/tests -q`
Expected: `6 passed`

- [ ] **Step 5: Commit**

```bash
git add layers/engine.py layers/tests/test_engine.py
git commit -m "layers: Engine — chat template + prefix, logit lens per layer, decided_at, attention heat; TL loader injectable

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_015zajUa5bvxaQ3mdsWe7Snf"
```

---

### Task 3: Sidecar HTTP server (`layers/server.py`)

**Files:**
- Create: `layers/server.py`, `layers/tests/test_server.py`

**Interfaces:**
- Produces: `create_app(engine) -> FastAPI` with `GET /health -> {"model", "n_layers", "device", "busy": bool}` and `POST /layers {messages?, prompt?, prefix?, top_k?, max_tokens?} -> Engine.analyze(...)` plus `"seconds"`; 400 when neither messages nor prompt; requests serialised by one `asyncio.Lock`.
- Produces: module-level `app` built from env `LAYERS_MODEL` (default `Qwen/Qwen3-4B`) and `LAYERS_DEVICE` (default `cuda`) — only when imported by uvicorn, guarded so tests importing `create_app` do not load a model.

- [ ] **Step 1: Write the failing test**

```python
# layers/tests/test_server.py
from fastapi.testclient import TestClient
from layers.server import create_app
from layers.engine import Engine
from layers.tests.test_engine import StubRunner


def client():
    return TestClient(create_app(Engine("stub/model", device="cpu", loader=lambda n, d: StubRunner())))


def test_health_and_layers_roundtrip():
    c = client()
    h = c.get("/health").json()
    assert h["model"] == "stub/model" and h["n_layers"] == 3 and h["device"] == "cpu" and h["busy"] is False
    r = c.post("/layers", json={"messages": [{"role": "user", "content": "hi"}], "prefix": "Ye", "top_k": 2})
    assert r.status_code == 200
    j = r.json()
    assert j["final"] == {"t": "Yes", "p": 0.9} and j["decided_at"] == 2 and len(j["layers"][0]["top"]) == 2 and "seconds" in j


def test_layers_needs_input():
    assert client().post("/layers", json={}).status_code == 400
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest layers/tests/test_server.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'layers.server'`

- [ ] **Step 3: Implement**

```python
# layers/server.py
"""HTTP face of the sidecar. One model, one lock: this serves a wall, not a room."""
from __future__ import annotations
import asyncio, os, time
from fastapi import FastAPI, HTTPException, Body
from pydantic import BaseModel
from .engine import Engine


class LayersReq(BaseModel):
    messages: list[dict] | None = None
    prompt: str | None = None
    prefix: str = ""
    top_k: int = 5
    max_tokens: int = 1536


def create_app(engine: Engine) -> FastAPI:
    app = FastAPI(title="ctxdemo layers")
    lock = asyncio.Lock()

    @app.get("/health")
    def health():
        return {"model": engine.model_name, "n_layers": engine.n_layers, "device": engine.device, "busy": lock.locked()}

    @app.post("/layers")
    async def layers(req: LayersReq = Body(...)):
        if not req.messages and req.prompt is None:
            raise HTTPException(400, "messages or prompt required")
        async with lock:
            t0 = time.time()
            try:
                out = await asyncio.to_thread(engine.analyze, req.messages, req.prompt, req.prefix,
                                              max(1, min(10, req.top_k)), max(64, min(4096, req.max_tokens)))
            except ValueError as e:
                raise HTTPException(400, str(e))
            out["seconds"] = round(time.time() - t0, 3)
            return out
    return app


if os.environ.get("LAYERS_SERVE") == "1":       # `LAYERS_SERVE=1 uvicorn layers.server:app`; tests import create_app only
    app = create_app(Engine(os.environ.get("LAYERS_MODEL", "Qwen/Qwen3-4B"), os.environ.get("LAYERS_DEVICE", "cuda")))
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest layers/tests -q`
Expected: `8 passed`

- [ ] **Step 5: Commit**

```bash
git add layers/server.py layers/tests/test_server.py
git commit -m "layers: FastAPI server — /health, /layers under one lock

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_015zajUa5bvxaQ3mdsWe7Snf"
```

---

### Task 4: Sidecar image, compose, README — and the first live pass on HACLab

**Files:**
- Create: `layers/Dockerfile`, `layers/docker-compose.yaml`, `layers/README.md`, `layers/run-haclab.sh`

**Interfaces:**
- Produces on HACLab: `http://127.0.0.1:8400/health` and `http://172.17.0.1:8400/layers` (reachable from the ctxdemo container as `http://host.docker.internal:8400`).

- [ ] **Step 1: Write the files**

```dockerfile
# layers/Dockerfile
FROM pytorch/pytorch:2.8.0-cuda12.8-cudnn9-runtime
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY __init__.py lens.py engine.py server.py ./layers/
ENV LAYERS_SERVE=1 LAYERS_MODEL=Qwen/Qwen3-4B LAYERS_DEVICE=cuda HF_HOME=/root/.cache/huggingface
EXPOSE 8400
CMD ["uvicorn", "layers.server:app", "--host", "0.0.0.0", "--port", "8400"]
```

```yaml
# layers/docker-compose.yaml — the "inside the head" sidecar. Its own compose, like vLLM: stop it to free VRAM.
#   cd /srv/projects/ctxdemo-layers && docker compose up -d --build        (first start pulls Qwen3-4B, ~8 GB, into the shared HF cache)
services:
  layers:
    build: .
    container_name: layers
    restart: unless-stopped
    ports:
      - "127.0.0.1:8400:8400"
      - "172.17.0.1:8400:8400"        # docker bridge: ctxdemo reaches it as host.docker.internal:8400 (the VISION_URL pattern)
    volumes:
      - /mnt/data/hf:/root/.cache/huggingface
    environment:
      - LAYERS_MODEL=${LAYERS_MODEL:-Qwen/Qwen3-4B}
      - HF_HUB_DISABLE_TELEMETRY=1
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8400/health',timeout=3)"]
      interval: 15s
      timeout: 5s
      retries: 40
      start_period: 180s
    logging: { driver: json-file, options: { max-size: "10m", max-file: "3" } }
```

```bash
#!/usr/bin/env bash
# layers/run-haclab.sh — rsync the sidecar to the box and (re)build it. Run from the Mac (VPN + ~/gonzaga/iiat-net home).
set -euo pipefail
HOST=simong@IIAT-HACLAB-01; DEST=/srv/projects/ctxdemo-layers
rsync -az --delete --exclude __pycache__ --exclude tests "$(dirname "$0")/" "$HOST:$DEST/"
ssh -o BatchMode=yes $HOST "cd $DEST && docker compose up -d --build 2>&1 | tail -3"
echo "then:  ssh $HOST 'docker logs -f layers'   until 'loaded Qwen/Qwen3-4B'"
```

```markdown
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
```

- [ ] **Step 2: Build and start it on HACLab, wait for the model**

Run (from the Mac, VPN up): `cd /Users/project/iiat/ctxdemo && chmod +x layers/run-haclab.sh && ./layers/run-haclab.sh`
Then: `ssh simong@IIAT-HACLAB-01 'for i in $(seq 1 60); do s=$(docker inspect -f "{{.State.Health.Status}}" layers 2>/dev/null); [ "$s" = healthy ] && break; sleep 5; done; echo $s; docker logs layers 2>&1 | grep -E "loaded|Error" | tail -3; nvidia-smi --query-compute-apps=process_name,used_memory --format=csv,noheader'`
Expected: `healthy`, a `loaded Qwen/Qwen3-4B on cuda in NN.Ns (36 layers)` line, and a second GPU process of roughly 8–9 GB next to vLLM's 18.8 GB. If the image build fails on `transformer_lens` pinning, loosen `requirements.txt` to `transformer_lens>=3.9` and rebuild; record the resolved version in the README.

- [ ] **Step 3: First live pass — the changed Monty Hall**

Run: `ssh simong@IIAT-HACLAB-01 'curl -s http://127.0.0.1:8400/layers -H "Content-Type: application/json" -d "{\"messages\":[{\"role\":\"system\",\"content\":\"You are a friendly assistant in a university lab. Keep answers short.\"},{\"role\":\"user\",\"content\":\"Monty Hall, but the host opens a door at random and it happens to be a goat. Should I switch?\"}]}"' | python3 -c 'import json,sys;j=json.load(sys.stdin);print("final",j["final"],"decided_at",j["decided_at"],"of",j["n_layers"],"in",j["seconds"],"s");[print(l["n"],[ (t["t"],t["p"]) for t in l["top"][:3]]) for l in j["layers"][::6]+j["layers"][-1:]]'`
Expected: a JSON answer in well under a second, `final` a plausible first token (`Yes`/`No`/`In`/`The`), `decided_at` somewhere in the second half of the 36 layers, early layers showing junk or punctuation. Paste the layer-by-layer lines into the commit message body as the first specimen.

- [ ] **Step 4: Commit**

```bash
git add layers/Dockerfile layers/docker-compose.yaml layers/README.md layers/run-haclab.sh
git commit -m "layers: image, own compose (127.0.0.1 + docker bridge :8400), README, run-haclab.sh — first live pass on the L40

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_015zajUa5bvxaQ3mdsWe7Snf"
```

---

### Task 5: ctxdemo — `LAYERS_URL`, health, `POST /api/layers`

**Files:**
- Modify: `app/config.py` (Config fields + `load`), `app/main.py` (health, new endpoint, `create_app` signature)
- Test: `tests/test_api.py`

**Interfaces:**
- Consumes: the sidecar API from Task 3.
- Produces: `Config.layers_url: str = ""` (env `LAYERS_URL`); `create_app(..., layers_transport=None)`; `/api/health["layers"] ∈ {"ok","down","none"}`; `POST /api/layers {session_id, index: int | None}` → the sidecar JSON plus `{"index": int, "wall_token": str | None}`; 404 unknown session, 400 index out of range / no answer yet, 503 when `layers_url` is empty, 502 when the sidecar fails.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_api.py

def test_api_layers_sends_the_sessions_real_messages_and_the_answer_prefix(fake, cfg):
    """Piece 4: the panel asks how token i of the last answer formed; we send the messages as sent + tokens[:i] to the sidecar."""
    from dataclasses import replace
    import httpx
    seen = {}
    def sidecar(req: httpx.Request):
        if req.url.path == "/health":
            return httpx.Response(200, json={"model": "Qwen/Qwen3-4B", "n_layers": 36, "device": "cuda", "busy": False})
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json={"tokens": ["a"], "final": {"t": "Yes", "p": 0.9}, "layers": [], "decided_at": 20,
                                         "attention": [], "cut": False, "model": "Qwen/Qwen3-4B", "n_layers": 36, "seconds": 0.2})
    c = TestClient(create_app(vllm=fake, cfg=replace(cfg, layers_url="http://layers"), layers_transport=httpx.MockTransport(sidecar)))
    assert c.get("/api/health").json()["layers"] == "ok"
    sid = c.post("/api/session", json={"mode": "compact", "board": True, "peek": True, "persona": "wall"}).json()["session_id"]
    assert c.post("/api/layers", json={"session_id": sid, "index": 0}).status_code == 400          # no answer yet
    c.post("/api/turn", json={"session_id": sid, "text": "hi there"})                                # fake answers "Echo: hi there" → tokens Echo: / hi / there
    r = c.post("/api/layers", json={"session_id": sid, "index": 2}).json()
    assert r["decided_at"] == 20 and r["index"] == 2 and r["wall_token"] == "there"
    msgs = seen["body"]["messages"]
    assert msgs[0]["role"] == "system" and msgs[-1] == {"role": "user", "content": "hi there"}          # the messages as sent, ending with the user turn
    assert seen["body"]["prefix"] == "Echo:hi"                                                       # tokens[:2] joined as text
    r0 = c.post("/api/layers", json={"session_id": sid}).json()                                      # index omitted = the first token
    assert r0["index"] == 0 and r0["wall_token"] == "Echo:"
    assert c.post("/api/layers", json={"session_id": sid, "index": 99}).status_code == 400
    assert c.post("/api/layers", json={"session_id": "nope", "index": 0}).status_code == 404


def test_api_layers_off_and_down(fake, cfg):
    from dataclasses import replace
    import httpx
    off = TestClient(create_app(vllm=fake, cfg=cfg))
    assert off.get("/api/health").json()["layers"] == "none"
    assert off.post("/api/layers", json={"session_id": "x", "index": 0}).status_code == 503
    down = TestClient(create_app(vllm=fake, cfg=replace(cfg, layers_url="http://layers"),
                                 layers_transport=httpx.MockTransport(lambda r: httpx.Response(500, text="boom"))))
    assert down.get("/api/health").json()["layers"] == "down"
    sid = down.post("/api/session", json={"mode": "compact", "board": True, "peek": True}).json()["session_id"]
    down.post("/api/turn", json={"session_id": sid, "text": "hi"})
    assert down.post("/api/layers", json={"session_id": sid, "index": 0}).status_code == 502
```

Note: `tests/test_api.py` already imports `json`? Check the top of the file; add `import json` if missing.

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_api.py -q -k layers`
Expected: FAIL, `TypeError: create_app() got an unexpected keyword argument 'layers_transport'` (or `KeyError: 'layers'`)

- [ ] **Step 3: Implement**

In `app/config.py`, after `netdata_url`:
```python
    layers_url: str = ""                 # piece 4: the "inside the head" sidecar (LAYERS_URL); empty = the layers panel says it is off
```
and in `load()` after the `netdata_url` line:
```python
    demo["layers_url"] = os.environ.get("LAYERS_URL", "")
```

In `app/main.py`:
- signature: `def create_app(vllm=None, cfg=None, vision=None, tools=None, ears=None, chunker=None, personas=None, netdata_transport=None, switcher=None, layers_transport=None) -> FastAPI:`
- after the `netdata = …` line:
```python
    layers = httpx.Client(base_url=cfg.layers_url.rstrip("/"), timeout=60, transport=layers_transport) if cfg.layers_url else None

    def layers_health() -> str:
        if layers is None:
            return "none"
        try:
            return "ok" if layers.get("/health", timeout=3).status_code == 200 else "down"
        except httpx.HTTPError:
            return "down"
```
- in `health()`'s dict add `"layers": layers_health(),`
- new request model next to `ModelReq`:
```python
    class LayersReq(BaseModel):
        session_id: str
        index: int | None = None     # which token of the last answer; None/0 = the first
```
- new endpoint after `/api/room`:
```python
    @app.post("/api/layers")
    def api_layers(req: LayersReq = Body(...)):
        """Piece 4: how token `index` of the last answer formed, layer by layer, in the sidecar's sibling model.
        Sends the messages exactly as the session sent them (system + transcript up to the user turn) plus the answer so far."""
        if layers is None:
            raise HTTPException(503, "layers are off on this wall")
        s = get(req.session_id)
        last = next((t for t in reversed(s.turns) if t.answer is not None and t.tokens), None)
        if last is None:
            raise HTTPException(400, "no answer with tokens yet")
        i = req.index or 0
        if i < 0 or i >= len(last.tokens):
            raise HTTPException(400, f"index must be 0..{len(last.tokens) - 1}")
        msgs = s.messages
        cut = max((k for k, m in enumerate(msgs) if m["role"] == "user"), default=len(msgs) - 1)   # through the last user turn
        body = {"messages": msgs[:cut + 1], "prefix": "".join(t["t"] for t in last.tokens[:i]), "top_k": 5}
        try:
            r = layers.post("/layers", json=body)
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise HTTPException(502, f"layers sidecar: {type(e).__name__}: {e}")
        out = r.json()
        out.update({"index": i, "wall_token": last.tokens[i]["t"]})
        return out
```
`get()` already raises 404 for an unknown session.

- [ ] **Step 4: Run to verify they pass, whole suite green**

Run: `.venv/bin/python -m pytest -q`
Expected: `112 passed` (110 + 2)

- [ ] **Step 5: Commit**

```bash
git add app/config.py app/main.py tests/test_api.py
git commit -m "piece 4: LAYERS_URL, health.layers, POST /api/layers (session messages + answer prefix → sidecar)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_015zajUa5bvxaQ3mdsWe7Snf"
```

---

### Task 6: lib.js helpers for the panel

**Files:**
- Modify: `static/peek/lib.js` (add two functions, export them), `static/peek/lib.test.mjs`

**Interfaces:**
- Produces: `peekLib.layersModel(resp, wallToken) -> {chips: [{n, t, p, tone, isFinal, decided}], decided_at, agree: bool, sibling: string}` — `tone` = `peekLib.tone(p)` when the chip's top equals the sibling's final token, else `'other'`; `agree` = sibling final token equals `wallToken` (trimmed compare).
- Produces: `peekLib.attentionHeat(resp, which) -> {layer, cells: [{t, w}]}` pairing `resp.tokens` with the weights of the attention row whose `layer === resp.decided_at` when `which === 'decided'`, the first row for `'early'`, the last for `'late'`; falls back to the last row.

- [ ] **Step 1: Write the failing tests**

```javascript
// append to static/peek/lib.test.mjs
const RESP = { tokens: ['<s>', 'Monty', ' Hall', '?'], final: { t: 'Yes', p: 0.9 }, decided_at: 3, n_layers: 4,
  layers: [{ n: 1, top: [{ t: 'the', p: 0.2 }] }, { n: 2, top: [{ t: 'No', p: 0.4 }] }, { n: 3, top: [{ t: 'Yes', p: 0.6 }] }, { n: 4, top: [{ t: 'Yes', p: 0.9 }] }],
  attention: [{ layer: 1, weights: [0, 0.2, 1, 0.1] }, { layer: 3, weights: [0, 1, 0.5, 0] }, { layer: 4, weights: [0, 0.1, 0.1, 1] }] };
test('layersModel: chips with tones, the decided marker, and whether the sibling agrees with the wall', () => {
  const m = L.layersModel(RESP, 'Yes');
  assert.equal(m.chips.length, 4); assert.equal(m.decided_at, 3); assert.equal(m.agree, true); assert.equal(m.sibling, 'Yes');
  assert.deepEqual(m.chips[0], { n: 1, t: 'the', p: 0.2, tone: 'other', isFinal: false, decided: false });
  assert.deepEqual(m.chips[2], { n: 3, t: 'Yes', p: 0.6, tone: 'unsure', isFinal: true, decided: true });
  assert.equal(m.chips[3].tone, 'sure');
  assert.equal(L.layersModel(RESP, ' No').agree, false);
  assert.deepEqual(L.layersModel(null, 'x'), { chips: [], decided_at: null, agree: null, sibling: null });
});
test('attentionHeat: pairs tokens with the chosen attention row', () => {
  assert.deepEqual(L.attentionHeat(RESP, 'decided'), { layer: 3, cells: [{ t: '<s>', w: 0 }, { t: 'Monty', w: 1 }, { t: ' Hall', w: 0.5 }, { t: '?', w: 0 }] });
  assert.equal(L.attentionHeat(RESP, 'early').layer, 1); assert.equal(L.attentionHeat(RESP, 'late').layer, 4);
  assert.equal(L.attentionHeat({ ...RESP, decided_at: 99 }, 'decided').layer, 4);     // no matching row: the last one
  assert.deepEqual(L.attentionHeat(null, 'decided'), { layer: null, cells: [] });
});
```

- [ ] **Step 2: Run to verify they fail**

Run: `node --test static/peek/lib.test.mjs 2>&1 | grep -E "^ℹ (pass|fail)|TypeError"`
Expected: `fail 2`, `TypeError: L.layersModel is not a function`

- [ ] **Step 3: Implement** — add before `const api = {` in `static/peek/lib.js`, and add `layersModel, attentionHeat` to the `api` object:

```javascript
  // piece 4, layers panel: one chip per layer from the sidecar's response; the final token's tone once a layer agrees with it.
  function layersModel(resp, wallToken) {
    if (!resp || !resp.layers) return { chips: [], decided_at: null, agree: null, sibling: null };
    const fin = resp.final ? resp.final.t : null;
    const chips = resp.layers.map(l => {
      const top = (l.top && l.top[0]) || { t: '', p: 0 };
      const isFinal = top.t === fin;
      return { n: l.n, t: top.t, p: top.p, tone: isFinal ? tone(top.p) : 'other', isFinal, decided: l.n === resp.decided_at };
    });
    const norm = s => String(s == null ? '' : s).trim();
    return { chips, decided_at: resp.decided_at ?? null, agree: fin == null || wallToken == null ? null : norm(fin) === norm(wallToken), sibling: fin };
  }
  // the "where it looked" strip: prompt tokens paired with one attention row (early / decided / late).
  function attentionHeat(resp, which) {
    if (!resp || !resp.attention || !resp.attention.length) return { layer: null, cells: [] };
    const rows = resp.attention;
    const row = which === 'early' ? rows[0] : which === 'late' ? rows[rows.length - 1]
      : (rows.find(r => r.layer === resp.decided_at) || rows[rows.length - 1]);
    return { layer: row.layer, cells: (resp.tokens || []).map((t, i) => ({ t, w: row.weights[i] ?? 0 })) };
  }
```

- [ ] **Step 4: Run to verify they pass**

Run: `node --test static/peek/lib.test.mjs 2>&1 | grep -E "^ℹ (pass|fail)"`
Expected: `pass 22`, `fail 0`

- [ ] **Step 5: Commit**

```bash
git add static/peek/lib.js static/peek/lib.test.mjs
git commit -m "peek lib: layersModel + attentionHeat for the layers panel

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_015zajUa5bvxaQ3mdsWe7Snf"
```

---

### Task 7: The `layers` panel, its chip, and the wall slot

**Files:**
- Create: `static/peek/layers.js`, `static/peek/explain/45-layers.md`
- Modify: `static/peek/explain.json`, `static/peek/peek.css`, `static/peek/wall.html`
- Test: `tests/test_api.py` (served-files assertions)

**Interfaces:**
- Consumes: bus messages `turn` (`msg.turn` has `tokens`; the driver's session id is not on the bus — see Step 3 for how the panel gets it), `select` (`{index}`), `clear`; `POST /api/layers` from Task 5; `peekLib.layersModel/attentionHeat` from Task 6; `peekLib.words()`.
- Produces: `peekPanels.layers` with `mount/onTurn/onSelect`; bus message `layers` `{index, decided_at, agree}` after each response (for the explain chip pulse).

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_api.py

def test_layers_panel_chip_and_wall_slot_are_served(client):
    assert client.get("/static/peek/layers.js").status_code == 200
    assert "45-layers.md" in client.get("/static/peek/explain.json").json()
    assert client.get("/static/peek/explain/45-layers.md").status_code == 200
    assert "'layers'" in client.get("/static/peek/wall.html").text            # ?with=layers slot
    d = client.get("/static/peek/driver.js").text
    assert "session_id" in d and "'turn', slim" in d and "sid" in d           # the driver puts the session id on the turn message (Step 3)
    js = client.get("/static/peek/layers.js").text
    assert "api/layers" in js and "peekLib.layersModel(" in js and "peekLib.words(" in js and "'/" not in js
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_api.py -q -k layers_panel`
Expected: FAIL on the first assertion (404 for `layers.js`)

- [ ] **Step 3: Implement**

3a. The panel needs the session id to call `/api/layers`. The driver's `sendTurn` builds `slim = { turn, state }`; add the id: in `static/peek/driver.js` change

```javascript
    const slim = { turn: msg.turn, state: msg.state ? { window_tokens: msg.state.window_tokens, next_would_send: msg.state.next_would_send } : null };
```
to
```javascript
    const slim = { turn: msg.turn, session_id: sid, state: msg.state ? { window_tokens: msg.state.window_tokens, next_would_send: msg.state.next_would_send } : null };
```

3b. `static/peek/layers.js`:

```javascript
// "Inside the head": how one token of the answer formed, layer by layer, in a 4B sibling of the wall's model.
// Asks /api/layers for the first token after every turn, and for any token tapped in the answer (bus `select`).
peekPanels.layers = (function () {
  let el, sid = null, toks = [], busy = false, which = 'decided', last = null;
  const esc = s => String(s == null ? '' : s).replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));
  const vis = t => String(t).replace(/^Ġ| /g, '␣').replace(/\n/g, '⏎').replace(/^<\|.*\|>$/, '·');
  function draw(resp, index) {
    const W = peekLib.words();
    const m = peekLib.layersModel(resp, toks[index] ? toks[index].t : null);
    el.querySelector('#how').textContent = index ? `how it chose “${toks[index].t.trim()}”` : 'how it chose the first ' + W.piece;
    const col = el.querySelector('#col');
    col.innerHTML = m.chips.slice().reverse().map(c =>
      `<div class="lchip ${c.tone}${c.decided ? ' decided' : ''}" title="layer ${c.n}: ${esc(c.t)} ${peekLib.pct(c.p)}">` +
      `<span class="ln">${c.n}</span><span class="lt">${esc(vis(c.t))}</span><span class="lp">${peekLib.pct(c.p)}</span>` +
      (c.decided ? '<span class="ldec">decided here</span>' : '') + '</div>').join('');
    const verdict = el.querySelector('#verdict');
    if (m.agree === false) verdict.innerHTML = `the wall said <b>${esc(toks[index].t.trim())}</b> · the sibling would have said <b>${esc(String(m.sibling).trim())}</b>`;
    else if (m.agree === true) verdict.innerHTML = `both say <b>${esc(String(m.sibling).trim())}</b>`;
    else verdict.textContent = '';
    const h = peekLib.attentionHeat(resp, which);
    el.querySelector('#heat').innerHTML = h.cells.map(c => `<span class="hcell" style="background:rgba(127,200,232,${(0.08 + 0.72 * c.w).toFixed(2)})">${esc(vis(c.t))}</span>`).join('');
    el.querySelector('#heatcap').textContent = h.layer ? `where it looked · layer ${h.layer}` : '';
    el.querySelector('#meta').textContent = resp ? `${resp.model.split('/').pop()} · ${resp.n_layers} layers · ${resp.seconds}s${resp.cut ? ' · prompt cut to the last ' + resp.tokens.length + ' ' + W.pieces : ''}` : '';
    peekBus.send('layers', { index, decided_at: m.decided_at, agree: m.agree });
  }
  async function ask(index) {
    if (!sid || !toks.length || busy) return;
    busy = true; el.querySelector('#state').textContent = 'reading the layers…';
    try {
      const r = await fetch('../../api/layers', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ session_id: sid, index }) });   // relative: /demo/ prefix
      if (r.status === 503) { el.querySelector('#state').textContent = 'layers are off on this wall'; return; }
      if (!r.ok) { el.querySelector('#state').textContent = 'layers: ' + ((await r.json().catch(() => ({}))).detail || r.statusText); return; }
      last = await r.json(); el.querySelector('#state').textContent = ''; draw(last, index);
    } catch (e) { el.querySelector('#state').textContent = 'layers: ' + e.message; }
    finally { busy = false; }
  }
  return {
    mount(root) {
      el = root; el.classList.add('layers');
      el.innerHTML = '<div class="wire-head"><div class="cap">the model, layer by layer <span class="dim" id="how"></span></div><span id="meta" class="dim" style="margin-left:auto;font-size:.7em"></span></div>' +
        '<div class="dim" style="font-size:.75em">a 4B sibling of the model you are talking to, read layer by layer · <span id="verdict"></span></div>' +
        '<div id="state" class="dim">ask something…</div>' +
        '<div class="lbody"><div id="col" class="lcol"></div><div class="lheat"><div class="cap"><span id="heatcap">where it looked</span> ' +
        '<button type="button" id="hw" class="linkish">early / decided / late</button></div><div id="heat"></div></div></div>';
      el.querySelector('#hw').onclick = () => { which = { decided: 'early', early: 'late', late: 'decided' }[which]; if (last) draw(last, last.index); };
    },
    onTurn(msg) {
      sid = (msg && msg.session_id) || sid; toks = (msg && msg.turn && msg.turn.tokens) || []; last = null;
      el.querySelector('#col').innerHTML = ''; el.querySelector('#heat').innerHTML = ''; el.querySelector('#verdict').textContent = '';
      if (!toks.length) { el.querySelector('#state').textContent = 'ask something…'; return; }
      ask(0);                                                  // the anchor: how the first token of the answer formed
    },
    onSelect(i) { if (toks[i]) ask(i); },
  };
})();
```

3c. `static/peek/explain/45-layers.md`:

```markdown
# inside the head
The model is a stack of **layers** — 36 of them in the sibling this wall reads. Each layer takes the running guess about the next piece and rewrites it a little. Read the guess out after every layer and you can watch an answer form: nothing, then a vague word, then the right word getting surer, then locked in.

- **the column** — one chip per layer, bottom to top. The chip shows that layer's best guess and how sure it was. Chips turn the answer's colour once they agree with the final word.
- **decided here** — the first layer after which the guess never changes again. Early = the model "knew"; late = it was still arguing with itself.
- **where it looked** — which pieces of the question the model paid attention to when it decided. The first piece is skipped: models park spare attention there.

Tap any piece of the answer and the column shows how *that* piece formed. Red pieces are decided late.

Honesty note: the layers you see belong to a **4B sibling** of the model that answered — same family, same design, smaller. When the two disagree the panel says so; that disagreement is a lesson too.
```

(The words `piece`/`pieces` here are rewritten to tokens by `peekLib.plainText` on the Linode — do not write "tokens" in the file.)

3d. `static/peek/explain.json` → `["10-pieces.md", "20-guesses.md", "25-wire.md", "30-almost.md", "40-persona.md", "45-layers.md", "50-backpack.md", "60-wall.md"]`. In `static/peek/explain.js` next to the existing `peekBus.on('wire', …)` add `peekBus.on('layers', () => pulse('layers'));`.

3e. `static/peek/peek.css` append:

```css
/* the layers panel */
#panel.layers .lbody { display: grid; grid-template-columns: minmax(10em, 34%) 1fr; gap: .8em; flex: 1; min-height: 0; }
#panel.layers .lcol { display: flex; flex-direction: column; gap: .12em; overflow-y: auto; min-height: 0; font-size: .7em; }
#panel.layers .lchip { display: grid; grid-template-columns: 2em 1fr 3em auto; gap: .4em; align-items: baseline; padding: .1em .4em; border-radius: .2em; border-left: .25em solid var(--line); color: var(--dim); }
#panel.layers .lchip .ln { text-align: right; } #panel.layers .lchip .lt { white-space: pre; overflow: hidden; text-overflow: ellipsis; color: var(--bone); }
#panel.layers .lchip.sure { border-left-color: var(--moss); background: rgba(155,191,106,.14); }
#panel.layers .lchip.unsure { border-left-color: var(--amber); background: rgba(242,169,59,.14); }
#panel.layers .lchip.flip { border-left-color: var(--red); background: rgba(224,85,60,.18); }
#panel.layers .lchip.decided { outline: 1px solid var(--ice); } #panel.layers .ldec { color: var(--ice); font-size: .85em; }
#panel.layers .lheat { display: flex; flex-direction: column; gap: .4em; min-height: 0; overflow: auto; }
#panel.layers #heat { line-height: 1.7; font-size: .9em; } #panel.layers .hcell { padding: .05em .15em; border-radius: .2em; white-space: pre; }
#panel.layers .linkish { font-size: .8em; padding: .1em .4em; }
```

3f. `static/peek/wall.html` — next to the `?with=room` line add:

```javascript
    if (q.get('with') === 'layers') layout = Object.assign({}, DEFAULT, { persona: [64, 3, 34, 30], almost: [64, 34, 34, 14], layers: [64, 49, 34, 29] });   // piece 4: the layers panel on the right
```
and in the `body.stack` CSS block add `body.stack iframe[data-panel=layers]{grid-column:1/-1;height:70vh}`.

- [ ] **Step 4: Run the tests and a headless render**

Run: `.venv/bin/python -m pytest -q && node --test static/peek/lib.test.mjs 2>&1 | grep -E "^ℹ (pass|fail)" && node -e "for (const f of ['layers.js','driver.js','explain.js']) new Function(require('fs').readFileSync('static/peek/'+f,'utf8')); console.log('syntax ok')"`
Expected: `113 passed`, `pass 22`, `syntax ok`.
Render (local :8222 has no sidecar, so the panel must show the off state cleanly): `"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless=new --disable-gpu --hide-scrollbars --window-size=900,700 --virtual-time-budget=5000 --screenshot=$SCRATCH/layers.png "http://127.0.0.1:8222/static/peek/panel.html?show=layers"` then Read the PNG: header, caption line, "ask something…". Then a canned render: temporarily paste the Task 4 live JSON into the browser console is not possible headless — instead verify the drawing code with the Task 6 fixture by adding to `lib.test.mjs` nothing further; the live check is Task 8.

- [ ] **Step 5: Commit**

```bash
git add static/peek/layers.js static/peek/explain/45-layers.md static/peek/explain.json static/peek/explain.js static/peek/peek.css static/peek/wall.html static/peek/driver.js tests/test_api.py
git commit -m "piece 4: the layers panel (column of layer chips, decided-here, where-it-looked), explain chip, ?with=layers; driver puts session_id on the turn message

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_015zajUa5bvxaQ3mdsWe7Snf"
```

---

### Task 8: Wire ctxdemo on HACLab to the sidecar and look at it live

**Files:**
- Modify: `docker-compose.yaml` (repo root = the HACLab ctxdemo compose): add `- LAYERS_URL=http://host.docker.internal:8400` under the ctxdemo `environment:` next to `VISION_URL`.
- Modify: `README.md` — a short "Piece 4: layers" section pointing at `layers/README.md` and the `?with=layers` URL.

- [ ] **Step 1: Deploy ctxdemo to HACLab**

Run: `cd /Users/project/iiat/ctxdemo && ./deploy.sh` (needs VPN + `~/gonzaga/iiat-net home`)
Expected: the health line printed by deploy.sh contains `"layers":"ok"`. If it says `down`, check `ssh simong@IIAT-HACLAB-01 'docker ps | grep layers; curl -s http://172.17.0.1:8400/health'` — the sidecar from Task 4 must be up and bound to the bridge.

- [ ] **Step 2: Live check through the wall's API**

```bash
B=https://iiat.gonzaga.edu:8443/demo
SID=$(curl -sk -X POST $B/api/session -H 'Content-Type: application/json' -d '{"mode":"compact","board":true,"peek":true,"persona":"wall"}' | python3 -c 'import json,sys;print(json.load(sys.stdin)["session_id"])')
curl -sk -X POST $B/api/turn -H 'Content-Type: application/json' -d "{\"session_id\":\"$SID\",\"text\":\"Monty Hall, but the host opens a door at random and it happens to be a goat. Should I switch?\"}" | python3 -c 'import json,sys;t=json.load(sys.stdin)["turn"];print("wall:",t["answer"][:60],"| first token:",repr(t["tokens"][0]["t"]))'
curl -sk -X POST $B/api/layers -H 'Content-Type: application/json' -d "{\"session_id\":\"$SID\",\"index\":0}" | python3 -c 'import json,sys;j=json.load(sys.stdin);print("sibling:",j["final"],"decided_at",j["decided_at"],"/",j["n_layers"],"| wall token",repr(j["wall_token"]),"|",j["seconds"],"s");[print(f"  L{l[\"n\"]:2d}",[(t[\"t\"],t[\"p\"]) for t in l[\"top\"][:2]]) for l in j["layers"][::5]+j["layers"][-1:]]'
```
Expected: a first-token analysis in < 1 s; `decided_at` printed; the wall token and the sibling's final shown side by side. Then open `https://iiat.gonzaga.edu:8443/demo/static/peek/wall.html?with=layers` in a real browser, ask the Monty Hall button, watch the column fill, tap a red token in the answer and watch it change. Take a screenshot to the Desktop for the journal.

- [ ] **Step 3: Record and commit**

Append the live numbers (decided_at for Monty Hall first token, seconds, agree/disagree) to `docs/plans/2026-09-23-ctxdemo-layers.md` under a `## Live specimen` heading at the end, then:

```bash
git add docker-compose.yaml README.md docs/plans/2026-09-23-ctxdemo-layers.md
git commit -m "piece 4 live on HACLab: LAYERS_URL wired, first specimen recorded

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_015zajUa5bvxaQ3mdsWe7Snf"
git push
```

Then update `/Users/project/dsc/HANDOFF.md` (piece 4 live, URLs, VRAM now used, what Simon should tap) and `JOURNAL.md`.

---

## Self-review

- **Spec coverage.** §Goal two moments → Task 7 (`onTurn` → index 0, `onSelect` → index i). §Caveat sibling + disagreement line → Task 6 `agree` + Task 7 `#verdict`. §Why HACLab / VRAM → Task 4 Step 2 checks the second GPU process. §1 sidecar: image/compose/bind addresses/health/lock/prompt cut/serialisation → Tasks 1–4 (the spec's `prompt` field kept; `messages` added so the sidecar's own tokenizer applies the chat template — recorded in the README). §2 ctxdemo: `layers_url`, health, `/api/layers` with real messages + prefix, 404/400/502, never inside a turn → Task 5 (turn-log line dropped: the panel's call is out of band and the log would only see it if the endpoint wrote it — deferred, not needed for the demo; noted here as the one spec item not implemented). §3 panel/explain/wall slot → Task 7. §4 tests → Tasks 1–3 (toy runner instead of `attn-only-1l`, so no download), 5, 6, 7 headless, 8 live. §5 decisions → defaults in Tasks 3–4.
- **Placeholders.** None: every step has code or an exact command.
- **Type consistency.** `Engine.analyze(messages, prompt, prefix, top_k, max_tokens)` positional order matches `server.py`'s `to_thread` call. Sidecar response keys (`tokens, final, layers, decided_at, attention, cut, model, n_layers, seconds`) match `layersModel`/`attentionHeat` fixtures and the ctxdemo fake in Task 5. `wall_token`/`index` added by ctxdemo are what `layers.js` reads via `last.index`. Bus message names: `turn` (now with `session_id`), `select`, `clear`, new `layers`.

## Live specimen (Task 8, 2026-09-23)

Deployed to HACLab via `./deploy.sh`; health line: `..."chunks":true,"layers":"ok"`.

Controller ruling: network path to `iiat.gonzaga.edu:8443` changed today, so the live check ran on the box itself
against ctxdemo's direct port (`ssh simong@IIAT-HACLAB-01 curl http://127.0.0.1:8200/...`) instead of through Caddy.
Same bodies as below, no `-k` needed since it's plain HTTP on loopback.

Prompt: "Monty Hall, but the host opens a door at random and it happens to be a goat. Should I switch?"

- Wall's answer (qwen3-8b, 61 tokens): "No, switching doesn't help in this case. The original Monty Hall problem
  assumes..." — first token `'No'` (p=0.7271).
- `/api/layers` index 0 (sibling qwen3-4b reading the same prompt): final `Yes` (p=0.9998), `decided_at` 31 / 36
  layers, 0.51 s. **Disagree** — the wall said "No", the sibling's logit-lens settles on "Yes" from layer 26 onward
  (layer trace: L21 first flips to " yes" p=0.14, L26 " yes" p=0.75, L31 "Yes" p=0.63, L36 "Yes" p=0.9998). A clean
  example of the "host opens at random" variant (switching is a coin flip, not a win) tripping up the smaller model
  while the 8B gets it right.
- No token in this answer actually crossed into "coin-flip" red (p<0.5 per `peekLib.tone`) — the whole answer stayed
  confident. Picked the least-sure token instead: index 42, `'s` at p=0.5579 ("unsure", amber). `/api/layers`
  index 42: sibling final `'s` (p=0.7527), `decided_at` 36 / 36, 0.2 s — **agree** with the wall here.
- Real-browser tap-a-token / screenshot step: **skipped** per controller instruction (controller does the visual
  check separately).
