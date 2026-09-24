"""ctxdemo — 'The Backpack'. FastAPI routes + static page."""
import random
from pathlib import Path
from fastapi import FastAPI, HTTPException, Body, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from . import config, script as script_mod
from .session import Session, SYSTEM, SYSTEM_BOARD, SYSTEM_MAP
from .personas import load as load_personas
from .jobs import RaceJob
from .vllm import VLLM, clamp_sampling
from .tools import Tools
from .chunks import Chunker
from .turnlog import TurnLog, hesitations
from .models import Switcher, load_models, host_restarts
from collections import deque
from .ears import Ears, split_wake, spoken_command
from . import grader
import difflib, re, os, base64, logging, time
import httpx
log = logging.getLogger("uvicorn.error")
from dataclasses import replace

READ_PROMPT = ("A person is holding a whiteboard up to the camera. Write out what they wrote as one line of plain text. "
               "Fix smudged or unclear letters to the obvious intended word; normal capitalization. "
               "Output only that line. If there is no whiteboard or no writing, output NONE.")
COMMANDS = {"COMPACT", "HANDOFF", "RESET", "NONE"}


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", "", s.lower()).strip()


def same_board(a: str, b: str) -> bool:
    a, b = norm(a), norm(b)
    return bool(a) and (a == b or difflib.SequenceMatcher(None, a, b).ratio() > 0.8)

ROOT = Path(__file__).resolve().parent.parent


class NewSession(BaseModel):
    mode: str = "endless"
    tools: bool = False          # let the assistant search the web
    board: bool = False          # whiteboard persona (short answers for a wall)
    teach: bool = False          # the map: longer lab-guide answers that invite the next question
    window: int | None = None    # board sessions only: a smaller backpack for the wall, so a short chat visibly fills it
    peek: bool = False           # act 6: return the guesses behind each piece of the answer
    persona: str | None = None   # act 6: config/personas/<id>.md — the system prompt speaks as this persona
    system: str | None = None    # act 6: free-text system prompt; wins over persona ("" = no system message at all)
    max_tokens: int | None = None  # act 6: longer leash for personas that ask for long answers (clamped 100-10000; the box serves 32k)


class HearReq(BaseModel):
    session_id: str
    audio: str                   # base64 audio clip from MediaRecorder
    mime: str = "audio/webm"


class LookReq(BaseModel):
    session_id: str
    image: str                   # base64 jpeg, no data: prefix


class TurnReq(BaseModel):
    session_id: str
    text: str | None = None
    source: str | None = None    # "typed" (default) or "voice" — only for the turn log
    name: str | None = None      # NFCU: optional first name for the presenter's room feed (and the turn log)
    sampling: dict | None = None  # the temperature card's dials: temperature / top_p / top_k / repetition_penalty (clamped server-side; None = greedy)


class UnlockReq(BaseModel):
    password: str


class SessReq(BaseModel):
    session_id: str


class ListenReq(BaseModel):
    session_id: str
    off: bool = False            # the off button: close the window now


def create_app(vllm=None, cfg=None, vision=None, tools=None, ears=None, chunker=None, personas=None, netdata_transport=None, switcher=None, layers_transport=None) -> FastAPI:
    cfg = cfg or config.load()
    personas = personas if personas is not None else load_personas()
    if ears is None and cfg.ears_url:
        ears = Ears(cfg.ears_url)
    vllm = vllm or VLLM(cfg.vllm_url, cfg.model)
    if vision is None:
        vision = vllm if (cfg.vision_url in ("", cfg.vllm_url) and cfg.vision_model in ("", cfg.model)) \
            else VLLM(cfg.vision_url or cfg.vllm_url, cfg.vision_model or cfg.model)
    tools = tools or Tools()
    chunker = chunker or Chunker(cfg.tokenizer_repo)
    turnlog = TurnLog(cfg.turnlog)
    room: deque = deque(maxlen=60)     # the presenter's live feed: the last turns from every session, newest last
    netdata = httpx.Client(base_url=cfg.netdata_url.rstrip("/"), timeout=3, transport=netdata_transport) if cfg.netdata_url else None
    layers = httpx.Client(base_url=cfg.layers_url.rstrip("/"), timeout=60, transport=layers_transport) if cfg.layers_url else None

    def layers_health() -> str:
        if layers is None:
            return "none"
        try:
            return "ok" if layers.get("/health", timeout=3).status_code == 200 else "down"
        except httpx.HTTPError:
            return "down"
    if hasattr(vllm, "refresh_model"):
        vllm.refresh_model()                          # the served name may differ from config (the model switch changes it)
    if switcher is None and cfg.compose_dir and cfg.admin_password:
        def switched(m):                              # vLLM is back on the new model: use its name and its tokenizer
            if hasattr(vllm, "refresh_model"): vllm.refresh_model()
            if hasattr(chunker, "use"): chunker.use(m.get("tokenizer"))
        switcher = Switcher(load_models(), env_file=Path(cfg.compose_dir) / ".env", compose_dir=Path(cfg.compose_dir),
                            hub_dir=Path(cfg.hf_hub_dir or "/nonexistent"), password=cfg.admin_password, runner=host_restarts,
                            wait_for=lambda mid: vllm.wait_for_model(mid) if hasattr(vllm, "wait_for_model") else True, on_switched=switched)
    switcher = switcher or Switcher(models=[], env_file=Path("/nonexistent/.env"), compose_dir=Path("/nonexistent"), hub_dir=Path("/nonexistent"), password="")
    current_model = lambda: getattr(vllm, "model", cfg.model)
    scr = script_mod.load()
    app = FastAPI(title="ctxdemo")
    app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")
    sessions: dict[str, Session] = {}
    jobs: dict[str, RaceJob] = {}
    app.state.sessions, app.state.jobs = sessions, jobs

    def tab_of(s: Session) -> str:
        """Which tab a session belongs to, for the turn log: map / board / compact / endless / race, +peek for act 6."""
        base = "map" if s.system == SYSTEM_MAP else "board" if s.system == SYSTEM_BOARD else s.mode
        return base + ("+peek" if s.peek else "")

    def get(sid: str) -> Session:
        s = sessions.get(sid)
        if not s:
            raise HTTPException(404, "no such session")
        return s

    @app.get("/")
    def index():
        return FileResponse(ROOT / "static" / "index.html")

    AUDIENCE_WINDOW, AUDIENCE_MAX_TOKENS = 4096, 600

    def is_audience(request: Request) -> bool:
        """Linode only (cfg.audience): everyone is the audience unless Caddy's /presenter/ route added X-Presenter."""
        return cfg.audience and request.headers.get("x-presenter") != "1"

    @app.get("/api/health")
    def health(request: Request):
        return {"vllm": "ok" if vllm.health() else "down", "model": current_model(), "window_tokens": cfg.window_tokens,
                "audience": is_audience(request), "room": cfg.room, "host": cfg.host_blurb, "freetext": cfg.freetext, "switching": switcher.switching, "vocab": cfg.vocab,
                "tools_ok": (switcher.info(current_model()) or {"tools": True})["tools"],
                "vision": "ok" if vision.health() else "down", "vision_model": getattr(vision, "model", cfg.model),
                "exact_counts": getattr(vllm, "exact", True), "board_window": cfg.board_window,
                "ears": ("ok" if ears.health() else "down") if ears else "none", "listen_seconds": cfg.listen_seconds,
                "compact_at": cfg.compact_at, "handoff_turn": cfg.handoff_turn, "script_turns": len(scr.turns),
                "prices": cfg.prices, "chunks": bool(getattr(chunker, "available", False)),
                "layers": layers_health()}

    @app.get("/api/queue")
    def queue():
        """How busy the shared GPU is right now, for the ask box's waiting line."""
        return {"queue": vllm.queue() if hasattr(vllm, "queue") else None}

    @app.get("/api/models")
    def models():
        """The switch list: what is running, what can be picked, what is already downloaded, whether a switch is in flight."""
        return switcher.status(current=current_model())

    class ModelReq(BaseModel):
        id: str
        password: str = ""

    class LayersReq(BaseModel):
        session_id: str
        index: int | None = None     # which token of the last answer; None/0 = the first

    @app.post("/api/unlock")
    def unlock(req: UnlockReq = Body(...)):
        """CTXDEMO_FREETEXT=password: does this password open the typed-question box? Read-only on purpose: checking a credential must never
        restart the model (last night's incident was a same-model 'switch' used as a password check)."""
        pw = getattr(switcher, "password", "") or cfg.admin_password
        if not pw or req.password != pw:
            raise HTTPException(403, "wrong password")
        return {"ok": True}

    @app.post("/api/model")
    def set_model(req: ModelReq = Body(...)):
        try:
            return switcher.switch(req.id, req.password, current=current_model())
        except PermissionError:
            raise HTTPException(403, "wrong password")
        except ValueError:
            raise HTTPException(400, "not in the list")
        except RuntimeError as e:
            raise HTTPException(409, str(e))

    @app.get("/api/gpu")
    def gpu():
        """GPU busy % right now, from Netdata's nvidia_smi collector — the room's own effect on the card. None when unconfigured/unreachable."""
        if netdata is None:
            return {"gpu": None}
        try:
            j = netdata.get("/api/v1/data", params={"context": "nvidia_smi.gpu_utilization", "after": -3, "points": 1, "format": "json"}).json()
            row = (j.get("data") or [[]])[0]
            busy = row[j["labels"].index("gpu")] if "gpu" in j.get("labels", []) and row else None
            return {"gpu": {"busy": round(float(busy))} if busy is not None else None}
        except Exception:
            return {"gpu": None}

    @app.get("/api/room")
    def room_feed(request: Request):
        """The room: recent questions from every session, newest first. Presenter-only when the audience clamp is on."""
        if is_audience(request):
            raise HTTPException(403, "presenter only")
        return {"turns": list(reversed(room))}

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
            out = r.json()
            if not isinstance(out, dict):
                raise HTTPException(502, "layers sidecar: bad response")
        except httpx.HTTPError as e:
            raise HTTPException(502, f"layers sidecar: {type(e).__name__}: {e}")
        except ValueError:
            raise HTTPException(502, "layers sidecar: bad response")
        out.update({"index": i, "wall_token": last.tokens[i]["t"]})
        return out

    @app.get("/api/personas")
    def list_personas():
        return {"personas": [{"id": p.id, "title": p.title, "blurb": p.blurb, "prompt": p.prompt}
                              for p in personas.values()]}

    @app.get("/api/script")
    def get_script():
        return {"turns": [t.__dict__ for t in scr.turns], "details": {k: v.__dict__ for k, v in scr.details.items()}}

    @app.post("/api/session")
    def new_session(request: Request, req: NewSession = Body(...)):
        if req.mode not in ("endless", "compact", "handoff"):
            raise HTTPException(400, "mode must be endless|compact|handoff")
        if is_audience(request):                         # the room shares one GPU: small backpack, short leash, no web
            req = req.model_copy(update={"window": min(req.window or AUDIENCE_WINDOW, AUDIENCE_WINDOW),
                                         "max_tokens": min(req.max_tokens or AUDIENCE_MAX_TOKENS, AUDIENCE_MAX_TOKENS),
                                         "tools": False})
        board_window = max(1024, min(32768, req.window)) if req.window else cfg.board_window   # 32k = the box's whole context: lets the wall overflow on purpose
        scfg = replace(cfg, window_tokens=board_window) if req.board else cfg
        if req.max_tokens:
            scfg = replace(scfg, answer_max_tokens=max(100, min(10000, req.max_tokens)))
        leash = (switcher.info(current_model()) or {}).get("max_tokens")   # per-model cap (models.json): a looping model can't burn the whole 10k
        if leash:
            scfg = replace(scfg, answer_max_tokens=min(scfg.answer_max_tokens, leash))
        if req.system is not None:                       # custom free text always wins, even "" (no system message)
            system_prompt, persona_label = req.system, "custom"
        elif req.persona is not None:
            p = personas.get(req.persona)
            if not p:
                raise HTTPException(400, "unknown persona")
            system_prompt, persona_label = p.prompt, req.persona
        else:
            system_prompt = SYSTEM_MAP if req.teach else SYSTEM_BOARD if req.board else SYSTEM
            persona_label = None
        s = Session(req.mode, vllm, scfg,
                    system_prompt=system_prompt, persona=persona_label,
                    tools=tools if req.tools else None, peek=req.peek, chunker=chunker)
        sessions[s.id] = s
        return {"session_id": s.id, "state": s.state()}

    @app.post("/api/turn")
    def turn(req: TurnReq = Body(...)):
        s = get(req.session_id)
        asks: list[str] = []
        text = req.text
        if text is None:
            if s.script_pos >= len(scr.turns):
                raise HTTPException(409, "script finished")
            t = scr.turns[s.script_pos]
            text, asks = t.user, t.asks
            s.script_pos += 1
        try:
            samp = clamp_sampling(req.sampling)
            if samp:
                samp["seed"] = random.randrange(1 << 31)    # vLLM serves with seed=0: without this, "ask twice" at temperature 1 repeats verbatim
            tr = s.turn(text, sampling=samp)
        except Exception as e:
            raise HTTPException(502, f"model server error: {type(e).__name__}: {e}")
        d = tr.to_dict()
        name = (req.name or "").strip()[:24] or getattr(s, "room_name", None)   # a name given once sticks to the session
        s.room_name = name
        if tr.answer is not None:
            room.append({"ts": time.strftime("%H:%M:%S"), "name": name, "user": text, "answer": (tr.answer or "")[:160],
                         "seconds": tr.seconds, "persona": s.persona, "session": s.id[:6],
                         **{k: v for k, v in hesitations(tr.tokens).items() if k in ("pieces", "flips")},
                         "sure_pct": (round(100 * sum(1 for t in tr.tokens if t.get("t", "").strip() and t.get("p", 1) >= 0.9)
                                            / max(1, sum(1 for t in tr.tokens if t.get("t", "").strip()))) if tr.tokens else None),
                         "worst": next(iter(hesitations(tr.tokens)["worst"]), None) if tr.tokens else None})
        d["asks"] = asks
        d["remembered"] = {a: grader.remembered(tr.answer, scr.details[a]) for a in asks}
        turnlog.write(s.id, tab_of(s), text, tr.answer, tr.seconds, tr.tokens, source=req.source or "typed", persona=s.persona, name=name,
                      full={"n": tr.n, "system": s.system, "user_chunks": tr.user_chunks, "pieces": tr.tokens, "cut": tr.cut,
                            "sent_tokens": tr.sent_tokens, "new_tokens": tr.new_tokens, "breakdown": tr.breakdown,
                            "event": tr.event, "event_text": tr.event_text, "tool_uses": tr.tool_uses, "wire": tr.wire,
                            "window_tokens": s.cfg.window_tokens, "max_tokens": s.cfg.answer_max_tokens, "model": vllm.model})
        return {"turn": d, "state": s.state()}

    @app.post("/api/handoff")
    def handoff(req: SessReq = Body(...)):
        s = get(req.session_id)
        try:
            h = s.handoff()
        except Exception as e:
            raise HTTPException(502, f"model server error: {type(e).__name__}: {e}")
        sessions[h.new_session.id] = h.new_session
        return {"session_id": h.new_session.id, "note": h.note, "note_tokens": h.note_tokens, "state": h.new_session.state(),
                "graph_seed": h.new_session.graph.to_dict(), "graph_survive": h.graph_survive}

    @app.post("/api/compact")
    def compact_now(req: SessReq = Body(...)):
        """Compact on request (the whiteboard says COMPACT). Works in any mode."""
        s = get(req.session_id)
        if not s.transcript:
            raise HTTPException(409, "nothing to compact yet")
        try:
            text = s._compact()
        except Exception as e:
            raise HTTPException(502, f"model server error: {type(e).__name__}: {e}")
        s.events.append({"n": s.n, "event": "compacted", "text": text})
        surv, s.last_survive = s.last_survive or {"kept": [], "absorbed": []}, None
        return {"summary": text, "graph_survive": surv, "state": s.state()}

    @app.post("/api/hear")
    def hear(req: HearReq = Body(...)):
        """Transcribe a clip. Wake phrase opens a listening window; inside it, speech is a question. Never runs the turn."""
        if not ears:
            raise HTTPException(503, "no microphone backend (EARS_URL not set)")
        s = get(req.session_id)
        try:
            r = ears.transcribe(req.audio, req.mime)
        except Exception as e:
            raise HTTPException(502, f"speech server error: {type(e).__name__}: {e}")
        heard = re.sub(r"\[[A-Z_ ]+\]|\([a-z ]+\)", " ", r.text).strip()   # whisper markers: [BLANK_AUDIO], (laughs)
        heard = re.sub(r"\s+", " ", heard)
        if turnlog.enabled:                                   # bystander speech stays out of the logs unless we are logging turns
            log.info("hear: %r (%.1fs)", heard[:120], r.seconds)
        now = time.time()
        out = {"heard": heard, "seconds": round(r.seconds, 2), "woke": False, "question": None, "command": None,
               "listening": now < s.listening_until, "listen_left": max(0, round(s.listening_until - now))}
        if out["listening"] and (cmd := spoken_command(heard)):     # "compact" / "hand off" / "start over", said inside the window
            out["command"] = cmd
            s.listening_until = 0 if cmd == "SLEEP" else now + cfg.listen_seconds
            out["listen_left"] = 0 if cmd == "SLEEP" else cfg.listen_seconds
            out["listening"] = cmd != "SLEEP"
            return out
        woke, rest = split_wake(heard)
        if woke:
            s.listening_until = now + cfg.listen_seconds
            out.update(woke=True, listening=True, listen_left=cfg.listen_seconds)
            if len(rest.split()) >= 2:
                out["question"] = rest
            return out
        if out["listening"] and len(heard.split()) >= 2:
            out["question"] = heard
            s.listening_until = now + cfg.listen_seconds       # a question keeps the window open
            out["listen_left"] = cfg.listen_seconds
        return out

    @app.post("/api/listen")
    def keep_listening(req: ListenReq = Body(...)):
        """The answer has finished (been read aloud): restart the follow-up window, if one was open recently.
        Thinking + speaking used to eat the whole window, so a natural follow-up needed the wake phrase again."""
        s = get(req.session_id)
        now = time.time()
        if req.off:
            s.listening_until = 0
        elif s.listening_until > now - 120:
            s.listening_until = now + cfg.followup_seconds
        return {"listening": now < s.listening_until, "listen_left": max(0, round(s.listening_until - now))}

    @app.post("/api/look")
    def look(req: LookReq = Body(...)):
        """Read the whiteboard. Returns the question if it's new, a command, or nothing. Never runs the turn."""
        s = get(req.session_id)
        try:
            r = vision.look(req.image, READ_PROMPT)
        except Exception as e:
            raise HTTPException(502, f"vision server error: {type(e).__name__}: {e}")
        text = r.text.strip().strip('"').splitlines()[0].strip() if r.text.strip() else "NONE"
        log.info("look: %r (%d tokens, %.1fs)", r.text[:120], r.prompt_tokens, r.seconds)
        if os.environ.get("CTXDEMO_SAVE_FRAME"):
            Path(os.environ["CTXDEMO_SAVE_FRAME"]).write_bytes(base64.b64decode(req.image))
        out = {"read": text, "read_tokens": r.prompt_tokens, "seconds": round(r.seconds, 2),
               "question": None, "command": None, "new": False}
        word = norm(text).upper().replace(" ", "")
        if word in COMMANDS:
            if word != "NONE" and not same_board(text, s.last_board):
                out["command"], out["new"] = word, True
                s.last_board = text
            return out
        if same_board(text, s.last_board):
            return out
        s.last_board = text
        out["question"], out["new"] = text, True
        return out

    @app.get("/api/session/{sid}")
    def session_state(sid: str):
        return get(sid).state()

    @app.post("/api/race/run")
    def race_run():
        job = RaceJob(vllm, cfg, scr).run(threads=app.state.race_threads if hasattr(app.state, "race_threads") else True)
        jobs[job.id] = job
        return {"job_id": job.id}

    @app.get("/api/race/{job_id}")
    def race_state(job_id: str):
        j = jobs.get(job_id)
        if not j:
            raise HTTPException(404, "no such job")
        return j.state()

    return app


app = create_app()
