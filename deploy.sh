#!/usr/bin/env bash
# deploy.sh — rsync this dir to the box and (re)build the container. Run from the Mac.
set -euo pipefail
HOST=simong@IIAT-HACLAB-01; DEST=/srv/projects/ctxdemo
ssh -o BatchMode=yes $HOST "mkdir -p $DEST/data"
rsync -az --delete --exclude .venv --exclude .git --exclude __pycache__ --exclude .pytest_cache --exclude data \
  "$(dirname "$0")/" "$HOST:$DEST/"
ssh -o BatchMode=yes $HOST "cd $DEST && docker compose up -d --build 2>&1 | tail -3 && sleep 3 && curl -s 127.0.0.1:8200/api/health"
echo
