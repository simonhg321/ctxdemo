#!/bin/bash
# update.sh — pull main and rebuild ctxdemo only (vLLM and Caddy untouched). Run as root on the Linode.
set -euo pipefail
cd /srv/projects/ctxdemo && git pull -q --ff-only && echo "== $(git log --oneline -1)"
cd deploy/linode && docker compose up -d --build ctxdemo 2>&1 | tail -2
docker exec caddy caddy reload --config /etc/caddy/conf/Caddyfile --adapter caddyfile 2>&1 | grep -q "adapted" && echo "== caddy reloaded"
sleep 3; docker exec ctxdemo python3 -c 'import urllib.request;print(urllib.request.urlopen("http://127.0.0.1:8200/api/health").read()[:160].decode())'
