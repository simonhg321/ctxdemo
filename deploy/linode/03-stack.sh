#!/bin/bash
# 03-stack.sh — clone the repo with the deploy key, set the shared password, bring up vLLM + ctxdemo + Caddy.
# Run as root:  bash 03-stack.sh <user> <password> [<presenter-user> <presenter-password>]
#   first pair = the audience (on the slide); second pair = /presenter/ (Simon; defaults to the first pair)
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "run as root" >&2; exit 1; }
USER_="${1:?usage: 03-stack.sh <user> <password> [presenter-user presenter-password]}"; PASS_="${2:?usage}"
PUSER_="${3:-$USER_}"; PPASS_="${4:-$PASS_}"
REPO=git@github.com:simonhg321/ctxdemo.git; DEST=/srv/projects/ctxdemo

# 1. git over the deploy key (read-only on GitHub).
grep -q "ctxdemo_deploy" /root/.ssh/config 2>/dev/null || cat >> /root/.ssh/config <<'CONF'
Host github.com
  IdentityFile /root/.ssh/ctxdemo_deploy
  IdentitiesOnly yes
  StrictHostKeyChecking accept-new
CONF
command -v git >/dev/null || apt-get install -y -qq git >/dev/null
if [ -d $DEST/.git ]; then git -C $DEST pull -q --ff-only; else git clone -q $REPO $DEST; fi
echo "== code: $(git -C $DEST log --oneline -1)"

# 2. Shared password -> bcrypt line Caddy imports.
mkdir -p /srv/data/caddy /srv/data/logs /srv/data/hf
HASH=$(docker run --rm caddy:2 caddy hash-password --plaintext "$PASS_")
printf '%s %s\n' "$USER_" "$HASH" > /srv/data/caddy/htpasswd
PHASH=$(docker run --rm caddy:2 caddy hash-password --plaintext "$PPASS_")
printf '%s %s\n' "$PUSER_" "$PHASH" > /srv/data/caddy/htpasswd-presenter
chmod 600 /srv/data/caddy/htpasswd /srv/data/caddy/htpasswd-presenter
echo "== htpasswd: audience $USER_ · presenter $PUSER_"

# 3. .env for compose: the model vLLM starts with (the wall's switch rewrites MODEL/MODEL_ARGS) + the switch password.
cd $DEST/deploy/linode
if [ ! -f .env ]; then
  printf 'MODEL=Qwen/Qwen3-8B-FP8\nMODEL_ARGS=--reasoning-parser qwen3 --enable-auto-tool-choice --tool-call-parser hermes\n' > .env
fi
grep -q '^CTXDEMO_ADMIN_PASSWORD=' .env || printf 'CTXDEMO_ADMIN_PASSWORD=%s\n' "$PPASS_" >> .env
chmod 600 .env
echo "== .env: $(grep ^MODEL= .env) · switch password = the presenter password"

# 4. Up. vLLM pulls the model on first start (~8.7 GB) — ctxdemo waits for its healthcheck.
docker compose pull -q vllm caddy
docker compose up -d --build 2>&1 | grep -E "Started|Created|Error|error" | sed 's/^/   /'
echo "== waiting for vLLM (first start downloads the model; a few minutes)"
for i in $(seq 1 120); do
  st=$(docker inspect -f '{{.State.Health.Status}}' vllm 2>/dev/null || echo none)
  [ "$st" = healthy ] && break
  [ $((i % 6)) -eq 0 ] && echo "   vllm: $st ($((i*10))s) $(docker logs vllm 2>&1 | grep -oE 'Loading weights took [0-9.]+ s|[0-9]+/[0-9]+ .*it/s|Downloading' | tail -1)"
  sleep 10
done
echo "== vllm: $(docker inspect -f '{{.State.Health.Status}}' vllm)"
docker compose ps --format '   {{.Name}}  {{.Status}}'
echo "== health via ctxdemo: $(docker exec ctxdemo python3 -c 'import urllib.request;print(urllib.request.urlopen("http://127.0.0.1:8200/api/health").read()[:120].decode())' 2>/dev/null)"
echo "== open: https://demo.instockornot.club/   (user $USER_)"
