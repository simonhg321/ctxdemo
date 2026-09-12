#!/usr/bin/env bash
# port-to-box.sh — run ON IIAT-HACLAB-01 as simong, once, before deploy.sh. Prepares the whiteboard + voice pieces.
# What it does (nothing needs sudo except step 3, which it only PRINTS):
#   1. pulls qwen2.5vl:7b into the host Ollama (the whiteboard reader; ~6 GB)
#   2. downloads whisper.cpp's ggml-small.en.bin into /srv/projects/ctxdemo/models (~490 MB) for the whisper container
#   3. checks that Ollama listens on the docker bridge (172.17.0.1:11434) — the ctxdemo container reaches it as
#      host.docker.internal. Default Ollama binds 127.0.0.1 only. If not reachable, prints the systemd override to apply.
#   4. checks the whisper image's server binary path matches docker-compose.yaml
set -uo pipefail
DEST=/srv/projects/ctxdemo
echo "== 1. Ollama reader model"; ollama pull qwen2.5vl:7b && ollama list | grep qwen2.5vl
echo "== 2. whisper model"; mkdir -p $DEST/models
[ -f $DEST/models/ggml-small.en.bin ] || curl -L -o $DEST/models/ggml-small.en.bin https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.en.bin
ls -la $DEST/models/ggml-small.en.bin
echo "== 3. Ollama on the docker bridge"
if curl -s -m 3 http://172.17.0.1:11434/api/tags >/dev/null; then echo "ok: Ollama answers on 172.17.0.1:11434"; else
cat <<'MSG'
NOT reachable on 172.17.0.1:11434. Ollama is bound to 127.0.0.1. Fix (sudo, one-time):
  sudo mkdir -p /etc/systemd/system/ollama.service.d
  printf '[Service]\nEnvironment="OLLAMA_HOST=0.0.0.0:11434"\n' | sudo tee /etc/systemd/system/ollama.service.d/bind.conf
  sudo systemctl daemon-reload && sudo systemctl restart ollama
  curl -s http://172.17.0.1:11434/api/tags | head -c 100
(0.0.0.0 is fine: the box's firewall only exposes 443; verify with: sudo firewall-cmd --list-ports)
MSG
fi
echo "== 4. whisper image"; docker pull -q ghcr.io/ggml-org/whisper.cpp:main >/dev/null && docker run --rm --entrypoint ls ghcr.io/ggml-org/whisper.cpp:main /app/build/bin | grep -x whisper-server && echo "ok: /app/build/bin/whisper-server" || echo "!! whisper-server not at /app/build/bin — run: docker run --rm --entrypoint find ghcr.io/ggml-org/whisper.cpp:main / -name whisper-server"
echo "== then, from the Mac (VPN or campus): ./deploy.sh   and open https://iiat.gonzaga.edu:8443/demo/#board"
