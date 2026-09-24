#!/usr/bin/env bash
# HACLab model switch, host side (run ONCE as root): a systemd path unit watches /srv/projects/vllm/.env and, when the
# wall's switcher rewrites it, recreates the vllm container with the new MODEL. Same design as deploy/linode/06-*.sh.
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "run as root: sudo bash $0" >&2; exit 1; }
DIR=/srv/projects/vllm
cat > /etc/systemd/system/ctxdemo-model-switch.service <<UNIT
[Unit]
Description=ctxdemo: apply the model in $DIR/.env to the vllm service
After=docker.service
[Service]
Type=oneshot
WorkingDirectory=$DIR
ExecStart=/usr/bin/docker compose up -d --force-recreate vllm
UNIT
cat > /etc/systemd/system/ctxdemo-model-switch.path <<UNIT
[Unit]
Description=ctxdemo: watch $DIR/.env for a model switch
[Path]
PathChanged=$DIR/.env
Unit=ctxdemo-model-switch.service
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now ctxdemo-model-switch.path >/dev/null
echo "== $(systemctl is-active ctxdemo-model-switch.path) — watching $DIR/.env"
