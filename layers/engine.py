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
