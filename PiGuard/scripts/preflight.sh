#!/usr/bin/env bash
# Read-only Pi commissioning snapshot. Run on the Pi, without sudo.
set -u
umask 077

if [ "$(uname -s)" != Linux ] || [ ! -r /proc/device-tree/model ]; then
  echo 'Run this script on the Raspberry Pi, not on the development computer.' >&2
  exit 2
fi
model=$(tr -d '\0' </proc/device-tree/model)
case "$model" in
  *Raspberry*) ;;
  *) echo "Unsupported hardware: $model" >&2; exit 2 ;;
esac
if ! command -v timeout >/dev/null 2>&1; then
  echo 'Missing timeout command (GNU coreutils).' >&2
  exit 2
fi

probe() {
  printf '\n### %s\n' "$1"
  shift
  if command -v "$1" >/dev/null 2>&1; then
    timeout 15 "$@" 2>&1
    code=$?
    printf '[exit=%s]\n' "$code"
  else
    printf '[not installed: %s]\n' "$1"
  fi
}

printf 'PiGuard preflight — observations, not an installation pass\n'
printf 'UTC: %s\nHardware: %s\n' "$(date -u +%FT%TZ)" "$model"
probe 'OS release' cat /etc/os-release
probe 'Kernel and architecture' uname -a
probe 'Userspace architecture' dpkg --print-architecture
probe 'Username' whoami
probe 'Host addresses' hostname -I
probe 'Interfaces' ip -brief address
probe 'IPv4 route' ip -4 route show default
probe 'IPv6 route' ip -6 route show default
probe 'Time synchronisation' timedatectl status
probe 'Memory' free -h
probe 'Root filesystem' df -h /
probe 'Temperature' vcgencmd measure_temp
probe 'Power and throttling flags' vcgencmd get_throttled
probe 'Listening sockets (check port 53 before installing)' ss -lntup
probe 'SSH service' systemctl is-active ssh
probe 'Existing Pi-hole' pihole version
probe 'Existing DNS service' systemctl is-active pihole-FTL
probe 'Existing Tailscale' tailscale version
probe 'Python' python3 --version
probe 'Installer hostname resolution' getent ahostsv4 install.pi-hole.net
printf '\nReview missing commands, port conflicts and nonzero exits before installation.\n'
