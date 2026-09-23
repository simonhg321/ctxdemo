# ctxdemo — "Inside the head" (piece 4: layers) design

_2026-09-23. DRAFT for Simon's review. Fourth of five "see it think" pieces, built out of order (before roads / thinking out loud) because Simon asked for it and the spike passed. Runs on HACLab first. Same rules as pieces 1–3: a standalone panel on the bus, plain words on the wall, one Chrome, nothing in acts 1–5 changes._

## Goal
Act 6 shows what the model chose and what it almost chose. Piece 4 shows **where in the network the choice happened**. A model is a stack of layers (36 in Qwen3-4B); each one rewrites a running guess about the next token. If you read that guess out at every layer you can watch an answer form: nothing, then a vague word, then the right word getting surer, then locked in. Students see a **column of layers** lighting up bottom to top with the guess at each one, a marker at *"decided here"*, and, beside it, **which words of the question the model was looking at** when it decided.

Two moments to show:
1. **The first token of the answer** — automatically, every turn. "Yes" vs "No" on the changed Monty Hall is decided somewhere around layer 20; the room watches it happen.
2. **Any token you tap** in *the answer* — the guesses panel already has `select`; the layers panel listens and shows how *that* token formed. Tap a red token: the layers disagree until late. Tap a green one: it locks in early.

## The honest caveat, on the wall
The hooks look inside a **smaller sibling** (Qwen3-4B) of the model answering the wall (Qwen3-8B). Same family, same architecture, different size, so its layers may not agree with the 8B's final answer. The panel caption says so in one line: *"a 4B sibling of the model you are talking to, read layer by layer."* When the sibling's final guess differs from the wall's actual token, the panel shows both (*it said "Yes" · the sibling would have said "No"*) — that disagreement is itself a lesson.

## Why HACLab
The L40 has 46 GB; vLLM reserves 40 % (18.8 GB) and the whiteboard reader takes 6 GB when it runs, leaving ~20 GB. Qwen3-4B in bf16 needs ~8 GB plus a few GB of activations at 1–2k tokens. Fits with no change to vLLM. (The Linode's 20 GB card would need vLLM cut to ~65 %; not now.) Verified on the Mac 9/21: TransformerLens 3.9 `TransformerBridge.boot_transformers` loads Qwen3-1.7B, `run_with_cache` gives `hook_resid_post` per layer and attention patterns, logit lens shows "Paris" forming; the first token is an attention sink and must be filtered out of the "where it looked" view.

## 1. The sidecar (`layers/`, new)
A small GPU container beside vLLM in the HACLab compose. Nothing else in ctxdemo imports torch.
- **Image:** `pytorch/pytorch:2.x-cuda12.x-runtime` + `transformer_lens==3.9.*` + `fastapi`. Model from the shared HF cache (`/mnt/data/hf`), `LAYERS_MODEL=Qwen/Qwen3-4B` (env; `Qwen/Qwen3-1.7B` as the light option). Loads once at start (~20 s), `gpus: all`, internal port 8400, healthcheck `/health` → `{model, layers, device}`.
- **`POST /layers`** `{prompt: str, top_k: 5, max_tokens: 1536}` → one forward pass with cache (~100–300 ms on the L40) →
  ```
  {tokens: [str],                      # the prompt as the sibling tokenizes it
   final: {t, p},                      # the sibling's own next-token guess
   layers: [{n, top: [{t, p}]}, …],    # logit lens at every layer, last position
   decided_at: int | null,             # first layer from which the final top-1 never changes again
   attention: [{layer, weights: [float]}]   # last position's attention over the prompt tokens, heads averaged, sink token zeroed; 3 layers: early / decided_at / last
  }
  ```
  Prompts longer than `max_tokens` are cut from the front (keep the end: the question and the answer so far). Two requests at once are serialised; a third waits (`asyncio.Lock`) — this is one wall, not the room.
- **`GET /health`**. Errors are JSON with a message; the panel prints them.

## 2. ctxdemo (server)
- `Config.layers_url` (env `LAYERS_URL`, empty = piece off). `/api/health` gains `"layers": "ok" | "down" | "none"`.
- `POST /api/layers {session_id, index: int | null}`: builds the prompt from the session's **actual messages as sent** (system + transcript through the last user turn, via the chat template the sibling's tokenizer provides) plus, when `index` is given, the answer's tokens `[0, index)`; forwards to the sidecar; returns its JSON plus `{index, wall_token: tokens[index].t}` so the panel can compare. 404 no session, 400 bad index, 502 sidecar error (existing pattern). Never called inside a turn: the turn is done before anyone asks, so nothing here can slow or break an answer.
- Logged to the turn log only as `{"layers": {"decided_at", "final", "index"}}` when the log is on.

## 3. Panels (browser)
- **`layers`** (new, `panel.html?show=layers`). Listens to `turn` (asks for `index: 0`, the first answer token) and to `select` (asks for that index). Draws:
  - a **column of layer chips**, layer 1 at the bottom, each showing its top guess, shaded by its probability (dim → bone), coloured by the act-6 tones once the guess equals the final token; a bracket *"decided here"* at `decided_at`; the wall's real token at the top with the sibling's guess beside it when they differ.
  - a **"where it looked" strip**: the question's tokens with a heat shade from the attention row at `decided_at`, sink token excluded, plus a small early/late toggle.
  - captions: *the model, layer by layer* · *a 4B sibling of the model you are talking to* · when `index > 0`: *how it chose "X"*.
  - empty / off / error states: *ask something…* · *layers are off on this wall* · the sidecar's message.
- **`answer`** (existing): no change; `select` already exists. **`explain`**: chip `45-layers.md` — what a layer is (a rewrite of the running guess), why early layers are vague, what "decided here" means, why the sibling can disagree. **`wall.html`**: `?with=layers` puts the panel in the right column (persona shrinks, layers 46–33 %); the Gonzaga wall can also open it as its own frameless window as before.

## 4. Testing
- `layers/tests`: the sidecar against a **tiny stand-in** (TransformerLens' `attn-only-1l` / a 2-layer toy) so tests need no GPU: shape of the response, `decided_at` logic (first stable layer; `null` when it never settles), sink zeroing, prompt cut from the front, lock serialises.
- `tests/test_api.py`: `/api/layers` with a fake sidecar (httpx MockTransport): prompt built from the real session messages + answer prefix, `wall_token` attached, 400/404/502, health `layers`.
- `lib.test.mjs`: `layersModel(resp, wallToken)` → chip list with tones + decided index; `attentionHeat(weights)` normalisation with the sink dropped.
- Browser: headless render of `layers` with a canned response in `replay.json`; then live on HACLab: Monty Hall first token, then tap a red token in the C division answer.

## 5. Open questions for Simon
1. **Sibling size:** Qwen3-4B (closer to the 8B, ~8 GB) or Qwen3-1.7B (faster, ~4 GB, more disagreement)? Recommend 4B; the env var makes it a one-line change.
2. **Auto-analyse the first token every turn** (recommended, it's the anchor demo) — costs one sidecar call per turn, off the turn's critical path.
3. **Deploy the sidecar into the existing HACLab compose** (same `docker compose up -d --build`, model pulled at first start from the box's cache/internet) — yes unless you want it separate.

## 6. Order of work
Sidecar with toy-model tests → HACLab compose + first live `/layers` (Monty Hall) → ctxdemo endpoint → panel + explain chip → `?with=layers` → deploy → Simon taps things. Estimate: one session. Roads (piece 2) and thinking-out-loud (piece 3) follow, specs already drafted for 2.
