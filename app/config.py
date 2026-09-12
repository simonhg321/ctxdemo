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
    prices: dict[str, dict[str, float]] = field(default_factory=dict)


def load(root: Path = ROOT) -> Config:
    demo = json.loads((root / "config" / "demo.json").read_text())
    prices = {k: v for k, v in json.loads((root / "config" / "prices.json").read_text()).items() if not k.startswith("_")}
    if os.environ.get("VLLM_MODEL"):
        demo["model"] = os.environ["VLLM_MODEL"]
    url = os.environ.get("VLLM_URL", "http://127.0.0.1:8100")
    return Config(vllm_url=url, vision_url=os.environ.get("VISION_URL", url),
                  vision_model=os.environ.get("VISION_MODEL", demo["model"]), prices=prices, **demo)
