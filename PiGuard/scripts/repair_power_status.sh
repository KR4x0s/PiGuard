#!/usr/bin/env bash
# Apply the tested historical-soft-temperature status fix to the active PiGuard UI.
set -euo pipefail
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
[[ $EUID -eq 0 && $# -eq 0 ]] || { echo 'Usage: sudo bash repair_power_status.sh' >&2; exit 2; }
source_dir=/home/krat0s/piguard-home-ui
release=$(readlink -f /opt/piguard/current)
[[ -d $release/piguard/templates && -d /usr/local/lib/piguard-control ]] || {
  echo 'PiGuard dashboard or broker installation is missing.' >&2; exit 1;
}
for file in control_broker.py dashboard.py network.py gateway.html setup.html; do
  [[ -f $source_dir/$file ]] || { echo "Missing staged file: $file" >&2; exit 1; }
done
python3 -m py_compile "$source_dir/control_broker.py" "$source_dir/dashboard.py" "$source_dir/network.py"
install -m 0755 "$source_dir/control_broker.py" /usr/local/lib/piguard-control/control_broker.py
install -m 0644 "$source_dir/dashboard.py" "$release/piguard/dashboard.py"
install -m 0644 "$source_dir/network.py" "$release/piguard/network.py"
install -m 0644 "$source_dir/gateway.html" "$release/piguard/templates/gateway.html"
install -m 0644 "$source_dir/setup.html" "$release/piguard/templates/setup.html"
systemctl restart piguard-control.service piguard-dashboard.service
systemctl is-active --quiet piguard-control.service piguard-dashboard.service
echo 'PiGuard dashboard and broker power-status fix active.'
