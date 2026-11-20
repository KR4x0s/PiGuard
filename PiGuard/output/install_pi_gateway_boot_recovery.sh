#!/usr/bin/env bash
# Install the tested Pi-hole startup ordering fix and retry the selected Tor mode.
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run with sudo on the Pi.' >&2; exit 2; }

source_root=/home/krat0s/PiGuard_Gateway_Dashboard_Final
gateway_source="$source_root/scripts/gateway.py"
unit_source="$source_root/tor/piguard-gateway-resume.service"
gateway_target=/usr/local/lib/piguard-gateway/gateway.py
unit_target=/etc/systemd/system/piguard-gateway-resume.service
stamp=$(date -u +%Y%m%dT%H%M%SZ)
gateway_backup="$gateway_target.before-boot-recovery-$stamp"
unit_backup="$unit_target.before-boot-recovery-$stamp"

[[ -f $gateway_source && -f $unit_source ]] || { echo 'Staged files are missing.' >&2; exit 1; }
python3 -m py_compile "$gateway_source"
cp -p "$gateway_target" "$gateway_backup"
cp -p "$unit_target" "$unit_backup"
restore_install() {
  cp -p "$gateway_backup" "$gateway_target"
  cp -p "$unit_backup" "$unit_target"
  systemctl daemon-reload
  echo 'Install failed; previous gateway source and unit restored.' >&2
}
trap restore_install ERR
install -m 0755 "$gateway_source" "$gateway_target"
install -m 0644 "$unit_source" "$unit_target"
python3 -m py_compile "$gateway_target"
systemctl daemon-reload
trap - ERR

echo "Boot recovery fix installed. Backups: $gateway_backup $unit_backup"
echo 'Re-enabling Tor from the failed closed state; the client stays blocked on any error.'
systemctl reset-failed piguard-gateway-resume.service
/usr/local/bin/piguard-gateway enable
/usr/local/bin/piguard-gateway status
vcgencmd get_throttled
