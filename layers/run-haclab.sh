#!/usr/bin/env bash
# layers/run-haclab.sh — rsync the sidecar to the box and (re)build it. Run from the Mac (VPN + ~/gonzaga/iiat-net home).
set -euo pipefail
HOST=simong@IIAT-HACLAB-01; DEST=/srv/projects/ctxdemo-layers
rsync -az --delete --exclude __pycache__ --exclude tests "$(dirname "$0")/" "$HOST:$DEST/"
ssh -o BatchMode=yes $HOST "cd $DEST && docker compose up -d --build 2>&1 | tail -3"
echo "then:  ssh $HOST 'docker logs -f layers'   until 'loaded Qwen/Qwen3-4B'"
