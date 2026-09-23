#!/bin/bash
# 06-model-switch-unit.sh — the host side of the wall's model switch. ctxdemo (no docker access) rewrites
# deploy/linode/.env; this systemd path unit sees the change and runs `docker compose up -d vllm`, which
# recreates the vLLM container with the new MODEL / MODEL_ARGS. Run as root once. Idempotent.
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "run as root" >&2; exit 1; }
DIR=/srv/projects/ctxdemo/deploy/linode
cat > /etc/systemd/system/ctxdemo-model-switch.service <<UNIT
[Unit]
Description=ctxdemo: apply the model in deploy/linode/.env to the vllm service
After=docker.service
[Service]
Type=oneshot
WorkingDirectory=$DIR
ExecStart=/usr/bin/docker compose up -d --force-recreate vllm
UNIT
cat > /etc/systemd/system/ctxdemo-model-switch.path <<UNIT
[Unit]
Description=ctxdemo: watch deploy/linode/.env for a model switch
[Path]
PathChanged=$DIR/.env
Unit=ctxdemo-model-switch.service
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now ctxdemo-model-switch.path >/dev/null
echo "== $(systemctl is-active ctxdemo-model-switch.path) — watching $DIR/.env"
