#!/bin/bash
# Dev loop on Typhoon: Ollama (qwen3-vl:8b) instead of vLLM, no docker.
# Reach it from the Mac with:  ssh -L 8200:localhost:8200 typhoon   then open http://localhost:8200
cd "$(dirname "$0")"
export VLLM_URL=http://127.0.0.1:11434
export VLLM_MODEL=qwen3-vl:8b
exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8200 "$@"
