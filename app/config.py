"""Demo configuration: config/demo.json + config/prices.json + env."""
from __future__ import annotations
import json, os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Config:
    window_tokens: int = 8192
    compact_at: float = 0.8
    summary_max_tokens: int = 200
    handoff_max_tokens: int = 150
    handoff_turn: int = 10
    model: str = "qwen3-8b"
    answer_max_tokens: int = 400
    race_long_window: int = 30000   # the 'one long session' side: a big-context assistant that never compacts
    board_window: int = 4096        # the whiteboard tab: search results are ~700 tokens each, give it room
    vllm_url: str = "http://127.0.0.1:8100"
    vision_url: str = ""                 # server that reads the whiteboard; defaults to vllm_url
    vision_model: str = ""               # defaults to model (fine when the chat model can see, e.g. qwen3-vl)
    ears_url: str = ""                   # whisper.cpp server; empty = no microphone
    listen_seconds: int = 25             # after the wake phrase, how long the mic stays open for questions
    followup_seconds: int = 12           # after an answer the mic stays open this long for a follow-up, then sleeps (25 s chained forever on room chatter)
    extract: bool = True                 # the map: one extra model call per turn to pull concepts
    extract_max_tokens: int = 200
    tokenizer_repo: str = ""             # act 6 chunks: HF repo whose tokenizer matches the chat model; empty = strip hidden
    turnlog: str = ""                    # path of a JSONL file that gets every question + answer; empty = log nothing (default)
    vocab: str = "wall"                  # words on the wall: "wall" = pieces/backpack, "plain" = tokens/context window (CTXDEMO_VOCAB)
    audience: bool = False               # NFCU Linode: clamp sessions without an X-Presenter header (4k window, 600-token leash, no tools)
    freetext: str = "on"                # the typed-question box: "on" | "password" (the model-switch password unlocks it) | "off" (prepared questions only) — CTXDEMO_FREETEXT
    host_blurb: str = "a single GPU"    # the "this wall" card: where the model runs (CTXDEMO_HOST_BLURB), per venue
    room: bool = False                   # NFCU: show the optional first-name box (feeds the presenter's room panel)
    netdata_url: str = ""                # NFCU: Netdata agent for /api/gpu (GPU busy % in the tiles); empty = no tile
    layers_url: str = ""                 # piece 4: the "inside the head" sidecar (LAYERS_URL); empty = the layers panel says it is off
    admin_password: str = ""             # NFCU: password for the model switch; empty = switching disabled
    compose_dir: str = ""                # NFCU: where docker-compose.yaml + .env live (mounted into the container); empty = disabled
    hf_hub_dir: str = ""                 # NFCU: the vLLM model cache (…/hub) to flag which models are already downloaded
    prices: dict[str, dict[str, float]] = field(default_factory=dict)


def load(root: Path = ROOT) -> Config:
    demo = json.loads((root / "config" / "demo.json").read_text())
    prices = {k: v for k, v in json.loads((root / "config" / "prices.json").read_text()).items() if not k.startswith("_")}
    if os.environ.get("VLLM_MODEL"):
        demo["model"] = os.environ["VLLM_MODEL"]
    if os.environ.get("CTXDEMO_EXTRACT") == "0":
        demo["extract"] = False
    if os.environ.get("CTXDEMO_TOKENIZER"):
        demo["tokenizer_repo"] = os.environ["CTXDEMO_TOKENIZER"]
    if os.environ.get("CTXDEMO_TURNLOG"):
        demo["turnlog"] = os.environ["CTXDEMO_TURNLOG"]
    demo["audience"] = os.environ.get("CTXDEMO_AUDIENCE") == "1"
    demo["vocab"] = "plain" if os.environ.get("CTXDEMO_VOCAB") == "plain" else "wall"
    demo["room"] = os.environ.get("CTXDEMO_ROOM") == "1"
    demo["freetext"] = os.environ.get("CTXDEMO_FREETEXT") if os.environ.get("CTXDEMO_FREETEXT") in ("on", "password", "off") else "on"
    demo["host_blurb"] = os.environ.get("CTXDEMO_HOST_BLURB") or "a single GPU"
    demo["netdata_url"] = os.environ.get("NETDATA_URL", "")
    demo["layers_url"] = os.environ.get("LAYERS_URL", "")
    demo["admin_password"] = os.environ.get("CTXDEMO_ADMIN_PASSWORD", "")
    demo["compose_dir"] = os.environ.get("CTXDEMO_COMPOSE_DIR", "")
    demo["hf_hub_dir"] = os.environ.get("CTXDEMO_HF_HUB", "")
    url = os.environ.get("VLLM_URL", "http://127.0.0.1:8100")
    return Config(vllm_url=url, vision_url=os.environ.get("VISION_URL", url),
                  vision_model=os.environ.get("VISION_MODEL", demo["model"]), ears_url=os.environ.get("EARS_URL", ""),
                  prices=prices, **demo)
