#!/usr/bin/env bash
# Repair an existing PiGuard installation after a no-carrier boot.
set -euo pipefail
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
[[ $EUID -eq 0 ]] || { echo 'Run with sudo on the Pi.' >&2; exit 2; }
[[ -f /etc/piguard-tor/gateway.json ]] || { echo 'Gateway is not installed.' >&2; exit 1; }

downlink=$(PYTHONPATH=/usr/local/lib/piguard-gateway python3 - <<'PY'
from gateway import load_config
print(load_config()['downlink'])
PY
)
profile=$(nmcli -g GENERAL.CONNECTION device show "$downlink")
[[ -n $profile && $profile != -- ]] || { echo 'Downstream NetworkManager profile is missing.' >&2; exit 1; }
[[ $(nmcli -g ipv4.method connection show "$profile") == manual ]] || { echo 'Downstream profile must have a static IPv4 address.' >&2; exit 1; }
install -d -m 0755 /etc/NetworkManager/conf.d
config=/etc/NetworkManager/conf.d/90-piguard-downstream.conf
if [[ -f $config ]]; then
  cp -p "$config" "$config.before-repair-$(date -u +%Y%m%dT%H%M%SZ)"
fi
printf '[device-piguard-downstream]\nmatch-device=interface-name:%s\nignore-carrier=yes\n' "$downlink" > "$config"
nmcli general reload conf
nmcli connection up "$profile" ifname "$downlink"
ip -4 address show dev "$downlink"

# The minute timer already refreshes read ACLs. The directory watcher can
# repeatedly trigger on ordinary Pi-hole activity and hit systemd's start limit.
systemctl disable --now piguard-source-access.path
systemctl reset-failed piguard-source-access.path nginx.service piguard-gateway-resume.service
systemctl is-active --quiet piguard-source-access.timer
systemctl start nginx.service
systemctl start piguard-gateway-resume.service
systemctl --no-pager --failed
echo 'Boot services repaired. Check the dashboard and select Tor explicitly if the saved mode is blocked.'
