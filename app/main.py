"""ctxdemo — 'The Backpack'. FastAPI routes + static page."""
from pathlib import Path
from fastapi import FastAPI, HTTPException, Body
from fastapi.responses import FileResponse
from pydantic import BaseModel
from . import config, script as script_mod
from .session import Session, SYSTEM, SYSTEM_BOARD
from .jobs import RaceJob
from .vllm import VLLM
from .tools import Tools
from . import grader
import difflib, re

READ_PROMPT = ("A person is holding a small whiteboard up to the camera. Transcribe exactly what is written on it, "
               "as one line of plain text. If there is no readable writing, reply with the single word NONE.")
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


class LookReq(BaseModel):
    session_id: str
    image: str                   # base64 jpeg, no data: prefix


class TurnReq(BaseModel):
    session_id: str
    text: str | None = None


class SessReq(BaseModel):
    session_id: str


def create_app(vllm=None, cfg=None, vision=None, tools=None) -> FastAPI:
    cfg = cfg or config.load()
    vllm = vllm or VLLM(cfg.vllm_url, cfg.model)
    if vision is None:
        vision = vllm if (cfg.vision_url in ("", cfg.vllm_url) and cfg.vision_model in ("", cfg.model)) \
            else VLLM(cfg.vision_url or cfg.vllm_url, cfg.vision_model or cfg.model)
    tools = tools or Tools()
    scr = script_mod.load()
    app = FastAPI(title="ctxdemo")
    sessions: dict[str, Session] = {}
    jobs: dict[str, RaceJob] = {}
    app.state.sessions, app.state.jobs = sessions, jobs

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
                "exact_counts": getattr(vllm, "exact", True),
                "compact_at": cfg.compact_at, "handoff_turn": cfg.handoff_turn, "script_turns": len(scr.turns),
                "prices": cfg.prices}

    @app.get("/api/script")
    def get_script():
        return {"turns": [t.__dict__ for t in scr.turns], "details": {k: v.__dict__ for k, v in scr.details.items()}}

    @app.post("/api/session")
    def new_session(req: NewSession = Body(...)):
        if req.mode not in ("endless", "compact", "handoff"):
            raise HTTPException(400, "mode must be endless|compact|handoff")
        s = Session(req.mode, vllm, cfg, system_prompt=SYSTEM_BOARD if req.board else SYSTEM,
                    tools=tools if req.tools else None)
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
        return {"turn": d, "state": s.state()}

    @app.post("/api/handoff")
    def handoff(req: SessReq = Body(...)):
        s = get(req.session_id)
        try:
            h = s.handoff()
        except Exception as e:
            raise HTTPException(502, f"model server error: {type(e).__name__}: {e}")
        sessions[h.new_session.id] = h.new_session
        return {"session_id": h.new_session.id, "note": h.note, "note_tokens": h.note_tokens, "state": h.new_session.state()}

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
        return {"summary": text, "state": s.state()}

    @app.post("/api/look")
    def look(req: LookReq = Body(...)):
        """Read the whiteboard. Returns the question if it's new, a command, or nothing. Never runs the turn."""
        s = get(req.session_id)
        try:
            r = vision.look(req.image, READ_PROMPT)
        except Exception as e:
            raise HTTPException(502, f"vision server error: {type(e).__name__}: {e}")
        text = r.text.strip().strip('"').splitlines()[0].strip() if r.text.strip() else "NONE"
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
