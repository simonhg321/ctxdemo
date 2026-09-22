"""Act 6: persona files under config/personas/ — pick who the model answers as.

Each file is `# Title` / `> one-line blurb` / the system prompt (remaining lines, may be empty)."""
from __future__ import annotations
import logging
import re
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("uvicorn.error")

ID_RE = re.compile(r"^[a-z0-9_-]+$")
ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Persona:
    id: str
    title: str
    blurb: str
    prompt: str


def load(dir: Path = ROOT / "config" / "personas") -> dict[str, Persona]:
    """Parse every <dir>/<id>.md. Never raises: a malformed file is skipped with a log.warning
    so one bad file can't take the whole wall down. Sorted with 'wall' first, then alphabetical."""
    personas: dict[str, Persona] = {}
    if not dir.is_dir():
        return personas
    for path in sorted(dir.glob("*.md")):
        pid = path.stem
        if not ID_RE.match(pid):
            log.warning("personas: skipping %s: id must match [a-z0-9_-]+", path.name)
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError as e:
            log.warning("personas: skipping %s: %s", path.name, e)
            continue
        if len(lines) < 2 or not lines[0].startswith("# ") or not lines[1].startswith("> "):
            log.warning("personas: skipping %s: expected '# Title' then '> blurb'", path.name)
            continue
        personas[pid] = Persona(id=pid, title=lines[0][2:].strip(), blurb=lines[1][2:].strip(),
                                 prompt="\n".join(lines[2:]).strip())
    return dict(sorted(personas.items(), key=lambda kv: (kv[0] != "wall", kv[0])))
