#!/usr/bin/env bash
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run with sudo' >&2; exit 2; }
systemctl disable --now piguard-observer piguard-dashboard piguard-source-access.path piguard-source-access.timer
for source in /etc/pihole/pihole-FTL.db /etc/pihole/pihole-FTL.db-wal /etc/pihole/pihole-FTL.db-shm; do
  if [[ -f $source && ! -L $source ]]; then setfacl -x u:piguard "$source"; fi
done
echo 'PiGuard stopped; retained model releases, alerts, and Pi-hole configuration.'
