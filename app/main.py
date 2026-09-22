"""ctxdemo — 'The Backpack'. FastAPI routes + static page."""
from pathlib import Path
from fastapi import FastAPI, HTTPException, Body
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from . import config, script as script_mod
from .session import Session, SYSTEM, SYSTEM_BOARD, SYSTEM_MAP
from .personas import load as load_personas
from .jobs import RaceJob
from .vllm import VLLM
from .tools import Tools
from .chunks import Chunker
from .turnlog import TurnLog
from .ears import Ears, split_wake, spoken_command
from . import grader
import difflib, re, os, base64, logging, time
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


class SessReq(BaseModel):
    session_id: str


class ListenReq(BaseModel):
    session_id: str
    off: bool = False            # the off button: close the window now


def create_app(vllm=None, cfg=None, vision=None, tools=None, ears=None, chunker=None, personas=None) -> FastAPI:
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

    @app.get("/api/health")
    def health():
        return {"vllm": "ok" if vllm.health() else "down", "model": cfg.model, "window_tokens": cfg.window_tokens,
                "vision": "ok" if vision.health() else "down", "vision_model": getattr(vision, "model", cfg.model),
                "exact_counts": getattr(vllm, "exact", True), "board_window": cfg.board_window,
                "ears": ("ok" if ears.health() else "down") if ears else "none", "listen_seconds": cfg.listen_seconds,
                "compact_at": cfg.compact_at, "handoff_turn": cfg.handoff_turn, "script_turns": len(scr.turns),
                "prices": cfg.prices, "chunks": bool(getattr(chunker, "available", False))}

    @app.get("/api/personas")
    def list_personas():
        return {"personas": [{"id": p.id, "title": p.title, "blurb": p.blurb, "prompt": p.prompt}
                              for p in personas.values()]}

    @app.get("/api/script")
    def get_script():
        return {"turns": [t.__dict__ for t in scr.turns], "details": {k: v.__dict__ for k, v in scr.details.items()}}

    @app.post("/api/session")
    def new_session(req: NewSession = Body(...)):
        if req.mode not in ("endless", "compact", "handoff"):
            raise HTTPException(400, "mode must be endless|compact|handoff")
        board_window = max(1024, min(32768, req.window)) if req.window else cfg.board_window   # 32k = the box's whole context: lets the wall overflow on purpose
        scfg = replace(cfg, window_tokens=board_window) if req.board else cfg
        if req.max_tokens:
            scfg = replace(scfg, answer_max_tokens=max(100, min(10000, req.max_tokens)))
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
            tr = s.turn(text)
        except Exception as e:
            raise HTTPException(502, f"model server error: {type(e).__name__}: {e}")
        d = tr.to_dict()
        d["asks"] = asks
        d["remembered"] = {a: grader.remembered(tr.answer, scr.details[a]) for a in asks}
        turnlog.write(s.id, tab_of(s), text, tr.answer, tr.seconds, tr.tokens, source=req.source or "typed", persona=s.persona,
                      full={"n": tr.n, "system": s.system, "user_chunks": tr.user_chunks, "pieces": tr.tokens, "cut": tr.cut,
                            "sent_tokens": tr.sent_tokens, "new_tokens": tr.new_tokens, "breakdown": tr.breakdown,
                            "event": tr.event, "event_text": tr.event_text, "tool_uses": tr.tool_uses,
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
