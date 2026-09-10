"""ctxdemo — 'The Backpack'. FastAPI routes + static page."""
from pathlib import Path
from fastapi import FastAPI, HTTPException, Body
from fastapi.responses import FileResponse
from pydantic import BaseModel
from . import config, script as script_mod
from .session import Session
from .jobs import RaceJob
from .vllm import VLLM
from . import grader

ROOT = Path(__file__).resolve().parent.parent


class NewSession(BaseModel):
    mode: str = "endless"


class TurnReq(BaseModel):
    session_id: str
    text: str | None = None


class SessReq(BaseModel):
    session_id: str


def create_app(vllm=None, cfg=None) -> FastAPI:
    cfg = cfg or config.load()
    vllm = vllm or VLLM(cfg.vllm_url, cfg.model)
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
                "compact_at": cfg.compact_at, "handoff_turn": cfg.handoff_turn, "script_turns": len(scr.turns),
                "prices": cfg.prices}

    @app.get("/api/script")
    def get_script():
        return {"turns": [t.__dict__ for t in scr.turns], "details": {k: v.__dict__ for k, v in scr.details.items()}}

    @app.post("/api/session")
    def new_session(req: NewSession = Body(...)):
        if req.mode not in ("endless", "compact", "handoff"):
            raise HTTPException(400, "mode must be endless|compact|handoff")
        s = Session(req.mode, vllm, cfg)
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
