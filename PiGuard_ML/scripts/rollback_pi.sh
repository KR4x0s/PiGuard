#!/usr/bin/env bash
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run with sudo' >&2; exit 2; }
previous=$(readlink -f /opt/piguard/previous)
[[ $previous == /opt/piguard/releases/* && -d $previous ]] || { echo 'No previous release' >&2; exit 1; }
ln -s "$previous" /opt/piguard/rollback.next
mv -Tf /opt/piguard/rollback.next /opt/piguard/current
systemctl restart piguard-observer piguard-dashboard
echo 'Restored previous release; alerts and DNS settings were preserved.'
