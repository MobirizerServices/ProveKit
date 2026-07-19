#!/usr/bin/env bash
# Baseline hardening for the ProveKit VPS (Ubuntu). Safe + idempotent — does NOT change the
# root password or disable password SSH (that's a manual step once you've added your own key,
# to avoid lockout). Run as root:  bash deploy/harden.sh
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

echo "▶ 1/4 apply security updates"
apt-get update -qq
apt-get -y -qq upgrade >/dev/null || apt-get -y upgrade
apt-get -y -qq autoremove >/dev/null || true

echo "▶ 2/4 automatic security updates (unattended-upgrades)"
apt-get install -y -qq unattended-upgrades >/dev/null
# enable periodic update + unattended-upgrade
cat > /etc/apt/apt.conf.d/20auto-upgrades <<'CFG'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
APT::Periodic::AutocleanInterval "7";
CFG
systemctl enable --now unattended-upgrades 2>/dev/null || true

echo "▶ 3/4 fail2ban (SSH brute-force protection)"
apt-get install -y -qq fail2ban >/dev/null
cat > /etc/fail2ban/jail.d/provekit.conf <<'CFG'
[sshd]
enabled = true
maxretry = 5
findtime = 10m
bantime = 1h
CFG
systemctl enable --now fail2ban 2>/dev/null || true
systemctl restart fail2ban 2>/dev/null || true

echo "▶ 4/4 firewall (ensure 22/80/443 only)"
if command -v ufw >/dev/null; then
  ufw allow 22 >/dev/null; ufw allow 80 >/dev/null; ufw allow 443 >/dev/null
  yes | ufw enable >/dev/null 2>&1 || true
fi

echo
echo "=== summary ==="
echo "unattended-upgrades: $(systemctl is-active unattended-upgrades 2>/dev/null || echo n/a)"
echo "fail2ban:            $(systemctl is-active fail2ban 2>/dev/null || echo n/a)"
command -v ufw >/dev/null && ufw status | head -1
if [ -f /var/run/reboot-required ]; then echo "NOTE: a reboot is required to finish applying a kernel update (schedule it — it briefly takes the site down)."; fi
echo
echo "STILL MANUAL (avoid lockout — do after adding your own SSH key):"
echo "  • rotate the root password:            passwd"
echo "  • disable SSH password login:          set 'PasswordAuthentication no' in /etc/ssh/sshd_config.d/, then: systemctl reload ssh"
