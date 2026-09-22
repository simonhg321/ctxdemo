#!/bin/bash
# 02-gpu-docker.sh — NVIDIA driver (open modules, NVIDIA's CUDA repo), Docker + compose, NVIDIA container toolkit.
# Run as root on Ubuntu 24.04:   bash 02-gpu-docker.sh [--reboot]
# Ends with a reboot (needed to load the driver) only when --reboot is given. Idempotent.
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "run as root" >&2; exit 1; }
export DEBIAN_FRONTEND=noninteractive
. /etc/os-release; [ "$VERSION_ID" = "24.04" ] || { echo "expected Ubuntu 24.04, got $VERSION_ID" >&2; exit 1; }

echo "== GPU on the bus:"; lspci | grep -i nvidia || { echo "no NVIDIA device" >&2; exit 1; }

apt-get update -qq
apt-get install -y -qq ca-certificates curl gnupg linux-headers-$(uname -r) >/dev/null

# 1. NVIDIA CUDA repo (Ubuntu 24.04) -> nvidia-open (open kernel modules; the right choice for Ada).
if [ ! -f /usr/share/keyrings/cuda-archive-keyring.gpg ]; then
  curl -fsSL -o /tmp/cuda-keyring.deb https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2404/x86_64/cuda-keyring_1.1-1_all.deb
  dpkg -i /tmp/cuda-keyring.deb >/dev/null && rm -f /tmp/cuda-keyring.deb
  apt-get update -qq
fi
if ! dpkg -l nvidia-open 2>/dev/null | grep -q '^ii'; then
  echo "== installing nvidia-open (takes a few minutes: builds the kernel module)"
  apt-get install -y -qq nvidia-open >/dev/null
fi
apt-mark hold nvidia-open 'nvidia-*' 'libnvidia-*' >/dev/null 2>&1 || true
echo "== driver package: $(dpkg -l nvidia-open | awk '/^ii/{print $3}')  (held)"

# 2. Docker from Docker's repo.
if ! command -v docker >/dev/null; then
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $VERSION_CODENAME stable" > /etc/apt/sources.list.d/docker.list
  apt-get update -qq
  apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin >/dev/null
fi
echo "== docker $(docker --version | awk '{print $3}') compose $(docker compose version --short)"

# 3. NVIDIA container toolkit -> docker runtime.
if ! command -v nvidia-ctk >/dev/null; then
  curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
  curl -fsSL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
    | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
    > /etc/apt/sources.list.d/nvidia-container-toolkit.list
  apt-get update -qq
  apt-get install -y -qq nvidia-container-toolkit >/dev/null
fi
nvidia-ctk runtime configure --runtime=docker >/dev/null
systemctl enable --now docker >/dev/null
systemctl restart docker
echo "== nvidia runtime in docker: $(docker info 2>/dev/null | grep -c nvidia) mention(s)"

# 4. Docker log cap so a chatty vLLM cannot fill the disk; shg can run docker.
if [ ! -f /etc/docker/daemon.json ] || ! grep -q max-size /etc/docker/daemon.json; then
  python3 - <<'PY'
import json, pathlib
p = pathlib.Path("/etc/docker/daemon.json"); d = json.loads(p.read_text()) if p.exists() else {}
d["log-driver"] = "json-file"; d["log-opts"] = {"max-size": "50m", "max-file": "3"}
p.write_text(json.dumps(d, indent=2) + "\n")
PY
  systemctl restart docker
fi
id shg >/dev/null 2>&1 && usermod -aG docker shg && echo "== shg in docker group"

mkdir -p /srv/projects /srv/data/hf /srv/data/logs
echo "== dirs: /srv/projects (code)  /srv/data/hf (model cache)  /srv/data/logs (turn log)"

if lsmod | grep -q '^nvidia' && nvidia-smi >/dev/null 2>&1; then
  echo "== driver already loaded:"; nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader
else
  echo "== REBOOT NEEDED to load the driver."
  if [ "${1:-}" = "--reboot" ]; then echo "rebooting now"; sleep 2; reboot; else echo "   run:  reboot    then check:  nvidia-smi  &&  docker run --rm --gpus all nvidia/cuda:12.6.3-base-ubuntu24.04 nvidia-smi"; fi
fi
