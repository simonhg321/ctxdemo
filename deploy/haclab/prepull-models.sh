#!/usr/bin/env bash
# Download every model in config/models.json into the HACLab vLLM cache (/mnt/data/hf) so a switch never waits on
# Hugging Face. Runs as any docker-group user; the cache dir is root-owned and docker runs as root.
set -uo pipefail
cd /srv/projects/ctxdemo
for m in $(python3 -c 'import json;[print(x["id"]) for x in json.load(open("config/models.json"))["models"]]'); do
  echo "== $m"
  docker run --rm --entrypoint python3 -v /mnt/data/hf:/root/.cache/huggingface vllm/vllm-openai:latest \
    -c "from huggingface_hub import snapshot_download; p=snapshot_download('$m', allow_patterns=['*.json','*.safetensors','*.txt','*.model','*.tiktoken','*.py']); print('   ok', p)" 2>&1 | grep -E "ok|Error|error" | tail -2
done
echo "== cache:"; du -sh /mnt/data/hf/hub; ls /mnt/data/hf/hub | grep models--
