#!/bin/bash
# 01-harden.sh — first thing on a fresh Ubuntu 24.04 Linode. Run as root:  bash 01-harden.sh
# Keys-only ssh, firewall 22/80/443, fail2ban, security auto-updates (kernel/nvidia held), stop the usual
# unneeded daemons. Idempotent. Does NOT touch Docker or NVIDIA (that is 02-gpu-docker.sh).
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "run as root" >&2; exit 1; }

echo "== listening before"; ss -tulpn | tail -n +2 | awk '{print $1, $5, $7}' | sort -u

# 0. Do not lock ourselves out: root must already have a key.
if ! grep -qsE '^(ssh-|ecdsa-)' /root/.ssh/authorized_keys; then
  echo "REFUSING: no ssh key in /root/.ssh/authorized_keys — add yours first (ssh-copy-id root@BOX)" >&2; exit 1
fi
echo "== key present: $(grep -cE '^(ssh-|ecdsa-)' /root/.ssh/authorized_keys) key(s)"

# 1. sshd: keys only. A drop-in wins over sshd_config; validate before restart.
cat > /etc/ssh/sshd_config.d/10-hardening.conf <<'CONF'
PasswordAuthentication no
KbdInteractiveAuthentication no
ChallengeResponseAuthentication no
PermitRootLogin prohibit-password
PubkeyAuthentication yes
MaxAuthTries 3
LoginGraceTime 30
X11Forwarding no
ClientAliveInterval 300
ClientAliveCountMax 2
CONF
# Ubuntu's cloud image ships a drop-in that re-enables passwords; neutralise it if present.
if [ -f /etc/ssh/sshd_config.d/50-cloud-init.conf ]; then
  sed -i 's/^PasswordAuthentication yes/PasswordAuthentication no/' /etc/ssh/sshd_config.d/50-cloud-init.conf
fi
sshd -t && systemctl restart ssh && echo "== sshd: keys only ($(sshd -T | grep -E '^passwordauthentication'))"

# 2. Packages.
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq ufw fail2ban unattended-upgrades apt-listchanges >/dev/null

# 3. Firewall.
ufw default deny incoming >/dev/null
ufw default allow outgoing >/dev/null
ufw allow 22/tcp  >/dev/null
ufw allow 80/tcp  >/dev/null
ufw allow 443/tcp >/dev/null
ufw --force enable >/dev/null
echo "== ufw:"; ufw status | grep -E "Status|ALLOW" | sed 's/^/   /'

# 4. fail2ban on sshd.
cat > /etc/fail2ban/jail.d/sshd.local <<'CONF'
[sshd]
enabled = true
backend = systemd
maxretry = 4
findtime = 10m
bantime = 1h
CONF
systemctl enable --now fail2ban >/dev/null
echo "== fail2ban: $(fail2ban-client status sshd 2>/dev/null | grep -E 'Currently banned' | xargs)"

# 5. Unattended security updates; hold kernel + nvidia so the driver never drifts from the module (HACLab lesson).
cat > /etc/apt/apt.conf.d/20auto-upgrades <<'CONF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
CONF
cat > /etc/apt/apt.conf.d/52unattended-upgrades-local <<'CONF'
Unattended-Upgrade::Allowed-Origins { "${distro_id}:${distro_codename}-security"; };
Unattended-Upgrade::Package-Blacklist { "linux-"; "nvidia-"; "libnvidia-"; "cuda-"; };
Unattended-Upgrade::Automatic-Reboot "false";
CONF
systemctl enable --now unattended-upgrades >/dev/null
echo "== unattended-upgrades: security only, kernel/nvidia held, no auto-reboot"

# 6. Daemons a demo server does not need: stop + mask if installed. Nothing uninstalled.
for u in snapd.service snapd.socket snapd.seeded.service ModemManager.service avahi-daemon.service avahi-daemon.socket cups.service cups.socket cups-browsed.service rpcbind.service rpcbind.socket bluetooth.service; do
  if systemctl list-unit-files "$u" >/dev/null 2>&1 && systemctl list-unit-files | grep -q "^$u"; then
    systemctl disable --now "$u" >/dev/null 2>&1 || true
    systemctl mask "$u" >/dev/null 2>&1 || true
    echo "== stopped+masked $u"
  fi
done

echo "== listening after"; ss -tulpn | tail -n +2 | awk '{print $1, $5, $7}' | sort -u
echo "== done. Test from another terminal BEFORE closing this one:  ssh root@$(hostname -I | awk '{print $1}')"
