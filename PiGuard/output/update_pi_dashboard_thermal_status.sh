#!/usr/bin/env bash
set -euo pipefail
if [[ $EUID -ne 0 ]]; then echo 'Run with sudo' >&2; exit 2; fi
source_root=/home/krat0s/PiGuard_ML_Dashboard_Final/piguard
active=$(readlink -f /opt/piguard/current)
[[ -f $source_root/dashboard.py && -f $source_root/templates/gateway.html && -f $active/piguard/dashboard.py ]] || { echo 'Dashboard source missing' >&2; exit 1; }
backup=/etc/piguard-web/dashboard-thermal-$(date -u +%Y%m%dT%H%M%SZ)
install -d -m 0700 "$backup"
cp -p "$active/piguard/dashboard.py" "$backup/dashboard.py"
cp -p "$active/piguard/templates/gateway.html" "$backup/gateway.html"
cp -p "$active/piguard/templates/setup.html" "$backup/setup.html"
restore() {
  cp -p "$backup/dashboard.py" "$active/piguard/dashboard.py"
  cp -p "$backup/gateway.html" "$active/piguard/templates/gateway.html"
  cp -p "$backup/setup.html" "$active/piguard/templates/setup.html"
  systemctl restart piguard-dashboard || true
}
trap restore ERR
install -m 0644 "$source_root/dashboard.py" "$active/piguard/dashboard.py"
install -m 0644 "$source_root/templates/gateway.html" "$active/piguard/templates/gateway.html"
install -m 0644 "$source_root/templates/setup.html" "$active/piguard/templates/setup.html"
"$active/.venv/bin/python" -m py_compile "$active/piguard/dashboard.py"
systemctl restart piguard-dashboard
for i in {1..20}; do
  if curl -fsS --max-time 3 http://127.0.0.1:8080/healthz; then
    trap - ERR
    echo
    echo "Dashboard thermal message updated. Backup: $backup"
    vcgencmd get_throttled
    vcgencmd measure_temp
    exit 0
  fi
  sleep 2
done
echo 'Dashboard failed readiness' >&2
exit 1
