"""The model switch (NFCU wall): an allow-list (config/models.json), a password, and a background restart of the
vLLM service with a new model. Nothing here talks to the GPU; it writes the compose env file and runs
`docker compose up -d vllm`, then waits for vLLM's health and tells the app which model is live."""
from __future__ import annotations
import json, logging, subprocess, threading, time
from pathlib import Path
from typing import Callable

log = logging.getLogger("ctxdemo")
ROOT = Path(__file__).resolve().parent.parent


def load_models(path: Path = ROOT / "config" / "models.json") -> list[dict]:
    return json.loads(path.read_text())["models"]


def _run(cmd: list[str], cwd: Path) -> int:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=600).returncode


def host_restarts(cmd: list[str], cwd: Path) -> int:
    """The container has no docker access. Writing .env is the whole request: on the host, a systemd path unit
    (deploy/linode/06-model-switch-unit.sh) watches that file and runs `docker compose up -d vllm` itself."""
    return 0


class Switcher:
    def __init__(self, models: list[dict], env_file: Path, compose_dir: Path, hub_dir: Path, password: str,
                 runner: Callable[[list[str], Path], int] | None = None, wait_for: Callable[[str], bool] | None = None,
                 on_switched: Callable[[dict], None] | None = None):
        self.models = models
        self.env_file, self.compose_dir, self.hub_dir = Path(env_file), Path(compose_dir), Path(hub_dir)
        self.password = password
        self._run = runner or _run
        self._wait = wait_for or (lambda model_id: True)     # blocks until the server serves model_id (the old one stays healthy until the restart begins)
        self._on_switched = on_switched or (lambda m: None)
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self.switching: dict | None = None            # {"target", "since"} while a restart is in flight
        self.last_error: str | None = None

    @property
    def enabled(self) -> bool:
        return bool(self.password) and bool(self.models)

    def info(self, model_id: str) -> dict | None:
        return next((m for m in self.models if m["id"] == model_id), None)

    def _cached(self, model_id: str) -> bool:
        return (self.hub_dir / ("models--" + model_id.replace("/", "--"))).exists()

    def status(self, current: str | None) -> dict:
        return {"current": current, "switching": self.switching, "enabled": self.enabled, "error": self.last_error,
                "models": [{**m, "cached": self._cached(m["id"]), "current": m["id"] == current} for m in self.models]}

    def switch(self, model_id: str, password: str, current: str | None = None) -> dict:
        if not self.enabled or password != self.password:
            raise PermissionError("wrong password")
        m = self.info(model_id)
        if not m:
            raise ValueError("not in the list")
        if current is not None and model_id == current:
            raise RuntimeError("already on that model")   # a same-model restart is two minutes of downtime for nothing
        with self._lock:
            if self.switching:
                raise RuntimeError("a switch is already running")
            self.switching = {"target": model_id, "since": time.time()}
            self.last_error = None
        # compose reads .env from its directory: MODEL and MODEL_ARGS are interpolated into the vllm command; keep the other lines
        keep = [l for l in (self.env_file.read_text().splitlines() if self.env_file.exists() else []) if not l.startswith(("MODEL=", "MODEL_ARGS="))]
        self.env_file.write_text("\n".join([f"MODEL={model_id}", f"MODEL_ARGS={m['args']}", *keep]).rstrip("\n") + "\n")
        st = self.status(current=None)                # snapshot before the thread runs: a fast restart would already show idle
        self._thread = threading.Thread(target=self._restart, args=(m,), daemon=True)
        self._thread.start()
        return st

    def _restart(self, m: dict) -> None:
        try:
            rc = self._run(["docker", "compose", "up", "-d", "--force-recreate", "vllm"], self.compose_dir)
            if rc != 0:
                raise RuntimeError(f"docker compose exited {rc}")
            if not self._wait(m["id"]):
                raise RuntimeError("vLLM did not come up serving the new model")
            self._on_switched(m)
        except Exception as e:                        # the wall shows the error; the old model may or may not be back
            log.error("model switch to %s failed: %s", m["id"], e)
            self.last_error = f"{type(e).__name__}: {e}"
        finally:
            self.switching = None

    def join(self, timeout: float | None = None) -> None:
        if self._thread:
            self._thread.join(timeout)
