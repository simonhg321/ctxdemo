"""The scripted 20-turn conversation and the 12 planted details."""
from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path
from .config import ROOT


@dataclass(frozen=True)
class Detail:
    id: str
    text: str
    aliases: list[str]


@dataclass(frozen=True)
class Turn:
    n: int
    user: str
    plants: list[str]
    asks: list[str]


@dataclass
class Script:
    turns: list[Turn]
    details: dict[str, Detail]


def load(root: Path = ROOT) -> Script:
    turns = [Turn(**t) for t in json.loads((root / "corpus" / "script.json").read_text())]
    details = {d["id"]: Detail(**d) for d in json.loads((root / "corpus" / "details.json").read_text())}
    return Script(turns=turns, details=details)
