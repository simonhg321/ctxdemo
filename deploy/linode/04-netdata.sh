#!/bin/bash
# 04-netdata.sh — Netdata on the host (GPU via nvidia-smi, CPU, RAM, net, disk, docker), reachable ONLY from
# localhost and the docker networks: Caddy proxies it at /monitor/, ctxdemo reads /api/gpu from it.
# Run as root after 03-stack.sh (needs the compose network to exist). Idempotent.
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "run as root" >&2; exit 1; }
if ! command -v netdata >/dev/null; then
  curl -fsSL -o /tmp/netdata-kickstart.sh https://get.netdata.cloud/kickstart.sh
  sh /tmp/netdata-kickstart.sh --stable-channel --disable-telemetry --non-interactive --dont-wait >/tmp/netdata-install.log 2>&1 || { tail -5 /tmp/netdata-install.log; exit 1; }
fi
GW=$(docker network inspect linode_default -f '{{(index .IPAM.Config 0).Gateway}}')
NET=$(docker network inspect linode_default -f '{{(index .IPAM.Config 0).Subnet}}')
mkdir -p /etc/netdata/go.d
printf '[web]\n    bind to = 127.0.0.1:19999 172.17.0.1:19999 %s:19999\n[global]\n    update every = 1\n' "$GW" > /etc/netdata/netdata.conf
printf 'modules:\n  nvidia_smi: yes\n' > /etc/netdata/go.d.conf
printf 'jobs:\n  - name: nvidia_smi\n    binary_path: /usr/bin/nvidia-smi\n    update_every: 1\n' > /etc/netdata/go.d/nvidia_smi.conf
chown -R netdata:netdata /etc/netdata/go.d /etc/netdata/go.d.conf 2>/dev/null || true
ufw status | grep -q "19999.*$NET" || ufw allow from "$NET" to any port 19999 proto tcp comment "netdata from the ctxdemo compose network" >/dev/null
systemctl enable --now netdata >/dev/null 2>&1; systemctl restart netdata; sleep 8
echo "== netdata $(netdata -V 2>/dev/null | head -1) listening: $(ss -tlnp | grep 19999 | awk '{print $4}' | paste -sd' ' -)"
echo "== gpu: $(curl -s "http://127.0.0.1:19999/api/v1/data?context=nvidia_smi.gpu_utilization&after=-3&points=1&format=json" | tr -d ' \n' | head -c 80)"
echo "== from ctxdemo: $(docker exec ctxdemo python3 -c 'import urllib.request;print(urllib.request.urlopen("http://host.docker.internal:19999/api/v1/info",timeout=3).status)' 2>/dev/null)"
