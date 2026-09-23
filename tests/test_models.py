"""The model switch (NFCU): an allow-list, a password, a background restart of vLLM, and the wall told what is happening."""
import json, threading
import pytest
from app.models import Switcher, load_models


def test_load_models_reads_the_allow_list():
    ms = load_models()
    assert ms[0]["id"] == "Qwen/Qwen3-8B-FP8" and all({"id", "label", "note", "args", "tools", "tokenizer"} <= set(m) for m in ms)


def make(tmp_path, runner_calls, health=None):
    env = tmp_path / ".env"
    hub = tmp_path / "hub"; (hub / "models--Qwen--Qwen3-4B-FP8").mkdir(parents=True)
    def runner(cmd, cwd): runner_calls.append((cmd, cwd)); return 0
    sw = Switcher(models=[{"id": "Qwen/Qwen3-8B-FP8", "label": "a", "note": "", "args": "--x", "tools": True, "tokenizer": "Qwen/Qwen3-8B"},
                          {"id": "Qwen/Qwen3-4B-FP8", "label": "b", "note": "", "args": "", "tools": False, "tokenizer": "Qwen/Qwen3-4B"}],
                  env_file=env, compose_dir=tmp_path, hub_dir=hub, password="pw", runner=runner,
                  wait_healthy=health or (lambda: True), on_switched=lambda m: runner_calls.append(("switched", m["id"])))
    return sw, env


def test_status_lists_models_with_cached_flag_and_current(tmp_path):
    sw, _ = make(tmp_path, [])
    st = sw.status(current="Qwen/Qwen3-8B-FP8")
    assert st["current"] == "Qwen/Qwen3-8B-FP8" and st["switching"] is None
    assert [m["cached"] for m in st["models"]] == [False, True]
    assert sw.info("Qwen/Qwen3-4B-FP8")["tools"] is False and sw.info("nope") is None


def test_switch_checks_password_and_allow_list(tmp_path):
    sw, _ = make(tmp_path, [])
    with pytest.raises(PermissionError): sw.switch("Qwen/Qwen3-4B-FP8", "wrong")
    with pytest.raises(ValueError): sw.switch("evil/model", "pw")
    with pytest.raises(PermissionError): Switcher(models=[], env_file=tmp_path / "e", compose_dir=tmp_path, hub_dir=tmp_path, password="", runner=None).switch("x", "")   # no password configured = disabled


def test_switch_writes_env_restarts_vllm_and_reports(tmp_path):
    calls = []
    gate = threading.Event()
    sw, env = make(tmp_path, calls, health=lambda: gate.wait(5))
    st = sw.switch("Qwen/Qwen3-4B-FP8", "pw")
    assert st["switching"]["target"] == "Qwen/Qwen3-4B-FP8" and "since" in st["switching"]
    with pytest.raises(RuntimeError): sw.switch("Qwen/Qwen3-8B-FP8", "pw")          # one at a time
    text = env.read_text()
    assert "MODEL=Qwen/Qwen3-4B-FP8\n" in text and "MODEL_ARGS=\n" in text
    gate.set(); sw.join(5)
    assert calls[0][0][:4] == ["docker", "compose", "up", "-d"] and "vllm" in calls[0][0] and calls[0][1] == tmp_path
    assert ("switched", "Qwen/Qwen3-4B-FP8") in calls
    assert sw.status(current="Qwen/Qwen3-4B-FP8")["switching"] is None
