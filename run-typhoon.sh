#!/bin/bash
# Dev loop on Typhoon: Ollama (qwen3-vl:8b) instead of vLLM, no docker.
# Reach it from the Mac with:  ssh -L 8200:localhost:8200 typhoon   then open http://localhost:8200
cd "$(dirname "$0")"
export VLLM_URL=http://127.0.0.1:11434
export VLLM_MODEL=qwen3-vl:8b
export VISION_MODEL=qwen2.5vl:7b     # reader: no thinking mode, answers in one go
export CTXDEMO_SAVE_FRAME=/tmp/ctxdemo-last.jpg
export EARS_URL=http://127.0.0.1:8300     # whisper-server -m models/ggml-small.en.bin --port 8300 --convert --tmp-dir /tmp
exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8200 "$@"
