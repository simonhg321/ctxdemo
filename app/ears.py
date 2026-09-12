"""Speech to text via a local whisper.cpp server (`whisper-server --convert`). Audio never leaves the box.
Wake phrase handling lives here too: 'hi compact demo, what's the weather' -> wake + question."""
from __future__ import annotations
import base64, difflib, re, time
from dataclasses import dataclass
import httpx

WAKE_PHRASE = "compact demo"
WAKE_LEAD_WORDS = 4      # the phrase may sit this many words into the utterance (whisper hallucinates leads: "check hi compact demo")
_NOISE = re.compile(r"[^a-z0-9' ]+")


@dataclass
class HearResult:
    text: str
    seconds: float


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", _NOISE.sub(" ", s.lower())).strip()


def split_wake(heard: str, phrase: str = WAKE_PHRASE) -> tuple[bool, str]:
    """Returns (woke, remainder). Fuzzy: 'high compaq demo whats up' -> (True, 'whats up')."""
    words = norm(heard).split()
    n = len(phrase.split())
    for start in range(0, min(len(words), WAKE_LEAD_WORDS + 1)):   # phrase may follow a few lead words
        cand = " ".join(words[start:start + n])
        if len(words[start:start + n]) == n and difflib.SequenceMatcher(None, cand, phrase).ratio() >= 0.72:
            rest = " ".join(words[start + n:]).strip()
            return True, rest
    return False, ""


COMMANDS = {"compact": "COMPACT", "compact it": "COMPACT",
            "handoff": "HANDOFF", "hand off": "HANDOFF", "hand it off": "HANDOFF",
            "reset": "RESET", "start over": "RESET", "start again": "RESET"}


def spoken_command(heard: str) -> str | None:
    """A bare command word/phrase (inside the listening window) -> COMPACT / HANDOFF / RESET; anything longer is a question."""
    return COMMANDS.get(norm(heard))


class Ears:
    def __init__(self, url: str, transport: httpx.BaseTransport | None = None):
        self.url = url.rstrip("/")
        self._c = httpx.Client(base_url=self.url, timeout=60, transport=transport)

    def health(self) -> bool:
        try:
            return self._c.get("/", timeout=3).status_code < 500
        except httpx.HTTPError:
            return False

    def transcribe(self, audio_b64: str, mime: str = "audio/webm") -> HearResult:
        raw = base64.b64decode(audio_b64)
        ext = "webm" if "webm" in mime else ("ogg" if "ogg" in mime else "wav")
        t0 = time.time()
        r = self._c.post("/inference", files={"file": (f"clip.{ext}", raw, mime)},
                         data={"response_format": "json", "temperature": "0"})
        r.raise_for_status()
        return HearResult(text=(r.json().get("text") or "").strip(), seconds=time.time() - t0)
