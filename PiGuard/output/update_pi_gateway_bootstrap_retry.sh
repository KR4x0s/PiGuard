#!/usr/bin/env bash
set -euo pipefail
if [[ $EUID -ne 0 ]]; then echo 'Run with sudo' >&2; exit 2; fi
source=/home/krat0s/PiGuard_Gateway_Dashboard_Final/scripts/gateway.py
target=/usr/local/lib/piguard-gateway/gateway.py
[[ -f $source && -f $target ]] || { echo 'Gateway source or installation missing' >&2; exit 1; }
backup="$target.before-bootstrap-retry-$(date -u +%Y%m%dT%H%M%SZ)"
cp -p "$target" "$backup"
trap 'cp -p "$backup" "$target"' ERR
python3 -m py_compile "$source"
install -m 0755 "$source" "$target"
python3 -m py_compile "$target"
trap - ERR
echo "Gateway retry installed. Backup: $backup"
/usr/local/bin/piguard-gateway status
