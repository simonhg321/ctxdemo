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
