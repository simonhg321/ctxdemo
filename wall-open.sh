#!/bin/bash
# wall-open.sh — open the act 6 panels as separate frameless Chrome windows (Mac).
# They land in your running Chrome, so they share one bus: type in the driver, the rest follow.
# Drag/size each window on the big screen; when the arrangement is right, freeze it into wall.html?layout=.
#
#   ./wall-open.sh                 # the five peek panels against HACLab
#   ./wall-open.sh replay          # same, canned run (no model needed)
#   ./wall-open.sh gpu             # add the GPU dials + Netdata windows
#   ./wall-open.sh replay gpu      # both
#   BASE=http://127.0.0.1:8222 ./wall-open.sh     # laptop copy (Typhoon's qwen2.5:14b)
#   ROOM=amy ./wall-open.sh        # a second independent set (default room: wall)

BASE=${BASE:-https://iiat.gonzaga.edu:8443/demo}
ROOM=${ROOM:-wall}
PANELS="driver chunks answer almost tiles"
REPLAY=; GPU=
for a in "$@"; do case $a in replay) REPLAY=1;; gpu) GPU=1;; *) echo "unknown arg: $a"; exit 1;; esac; done

app() { open -na "Google Chrome" --args --app="$1"; sleep 0.4; }   # one window per call; the pause keeps Chrome from coalescing them

for p in $PANELS; do
  url="$BASE/static/peek/panel.html?show=$p&room=$ROOM"
  [ "$p" = driver ] && [ -n "$REPLAY" ] && url="$url&replay=1"   # replay is the driver's job; it feeds the others over the bus
  app "$url"
done

if [ -n "$GPU" ]; then
  host=${BASE%/demo}
  app "$host/sysadm/gpu/"
  app "$host/monitor/v3/"
fi

echo "opened: $PANELS${GPU:+ gpu netdata} (room=$ROOM${REPLAY:+, replay})"
echo "close them all: pick any of the windows and Cmd-W each, or quit Chrome."
