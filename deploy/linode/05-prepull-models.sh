#!/bin/bash
# 05-prepull-models.sh — download every model in config/models.json into the vLLM cache so a switch during the
# talk is a ~1 minute restart, not a 5 minute download. Run as root; safe to re-run (skips what is cached).
set -uo pipefail
cd /srv/projects/ctxdemo
for m in $(python3 -c 'import json;[print(x["id"]) for x in json.load(open("config/models.json"))["models"]]'); do
  echo "== $m"
  docker run --rm --entrypoint python3 -v /srv/data/hf:/root/.cache/huggingface vllm/vllm-openai:latest \
    -c "from huggingface_hub import snapshot_download; p=snapshot_download('$m', allow_patterns=['*.json','*.safetensors','*.txt','*.model','*.tiktoken','*.py']); print('   ok', p)" 2>&1 | grep -E "ok|Error|error" | tail -2
done
echo "== cache:"; du -sh /srv/data/hf/hub; ls /srv/data/hf/hub | grep models--
