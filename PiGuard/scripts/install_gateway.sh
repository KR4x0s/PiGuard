#!/usr/bin/env bash
# Install only on a commissioned, separate downstream interface. Tor starts OFF.
set -euo pipefail
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
umask 022
[[ $EUID -eq 0 && $# -eq 1 ]] || { echo 'Usage: sudo bash scripts/install_gateway.sh PROFILE.json' >&2; exit 2; }
[[ -d /run/systemd/system ]] || { echo 'Requires Raspberry Pi OS / Debian with systemd.' >&2; exit 1; }
[[ ! -e /etc/piguard-tor/gateway.json ]] || { echo 'Already installed; configuration is preserved. Use piguard-gateway controls.' >&2; exit 1; }
for dependency in /usr/bin/tor /usr/sbin/dnscrypt-proxy /usr/sbin/nft /usr/sbin/ip /usr/bin/dig /usr/bin/curl /usr/bin/python3; do
  [[ -x $dependency ]] || { echo "Missing $dependency. See tor/README.md prerequisites." >&2; exit 1; }
done
source_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
profile=$(realpath -- "$1")
# Refuse guessed topology before modifying host configuration.
PYTHONPATH="$source_root/scripts" python3 - "$profile" <<'PY'
import sys
from gateway import load_config, preflight
preflight(load_config(sys.argv[1]), require_forward=False)
PY
downlink=$(PYTHONPATH="$source_root/scripts" python3 - "$profile" <<'PY'
import sys
from gateway import load_config
print(load_config(sys.argv[1])['downlink'])
PY
)
[[ -x /usr/bin/nmcli ]] || { echo 'NetworkManager is required for persistent downstream addressing.' >&2; exit 1; }
downlink_profile=$(nmcli -g GENERAL.CONNECTION device show "$downlink")
[[ -n $downlink_profile && $downlink_profile != -- ]] || { echo 'Downstream NetworkManager profile is missing.' >&2; exit 1; }
[[ $(nmcli -g ipv4.method connection show "$downlink_profile") == manual ]] || { echo 'Downstream profile must use a static IPv4 address.' >&2; exit 1; }
# A static gateway address must exist before a client cable is plugged in.
# Otherwise nginx cannot bind and the saved gateway mode cannot resume at boot.
install -d -m 0755 /etc/NetworkManager/conf.d
printf '[device-piguard-downstream]\nmatch-device=interface-name:%s\nignore-carrier=yes\n' "$downlink" \
  > /etc/NetworkManager/conf.d/90-piguard-downstream.conf
nmcli general reload conf
for service_user in piguard-tor piguard-tor-dns; do
  if ! id "$service_user" >/dev/null 2>&1; then
    useradd --system --user-group --no-create-home --shell /usr/sbin/nologin "$service_user"
  fi
done
install -d -o root -g root -m 0755 /etc/piguard-tor /usr/local/lib/piguard-gateway
install -d -o piguard-tor -g piguard-tor -m 0700 /var/lib/piguard-tor
install -m 0755 "$source_root/scripts/gateway.py" /usr/local/lib/piguard-gateway/gateway.py
install -m 0644 "$source_root/scripts/tor_mode.py" /usr/local/lib/piguard-gateway/tor_mode.py
install -m 0644 "$profile" /etc/piguard-tor/gateway.json
install -m 0644 "$source_root/tor/dnscrypt-proxy.toml" /etc/piguard-tor/dnscrypt-proxy.toml
PYTHONPATH=/usr/local/lib/piguard-gateway python3 - <<'PY'
from pathlib import Path
from gateway import tor_config, save_mode, load_config
Path('/etc/piguard-tor/torrc').write_text(tor_config(load_config()))
save_mode('normal')
PY
runuser -u piguard-tor -- /usr/bin/tor --verify-config -f /etc/piguard-tor/torrc
/usr/sbin/dnscrypt-proxy -check -config /etc/piguard-tor/dnscrypt-proxy.toml
install -m 0644 "$source_root"/tor/piguard-*.service /etc/systemd/system/
ln -s /usr/local/lib/piguard-gateway/gateway.py /usr/local/bin/piguard-gateway
# Networking cannot start on a subsequent boot if guard loading fails.
for manager in NetworkManager.service systemd-networkd.service networking.service; do
  if [[ $(systemctl show "$manager" --property=LoadState --value) == loaded ]]; then
    install -d -m 0755 "/etc/systemd/system/$manager.d"
    cat > "/etc/systemd/system/$manager.d/90-piguard-guard.conf" <<'UNIT'
[Unit]
Requires=piguard-gateway-guard.service
After=piguard-gateway-guard.service
UNIT
  fi
done
systemctl daemon-reload
# Guard first, then forwarding. No restart of NetworkManager or client DNS changes.
systemctl enable --now piguard-gateway-guard.service
printf '%s\n' 'net.ipv4.ip_forward=1' > /etc/sysctl.d/90-piguard-gateway.conf
sysctl -w net.ipv4.ip_forward=1
systemctl enable piguard-gateway-resume.service
echo 'Installed in normal gateway mode (Tor OFF). Enable later with: sudo piguard-gateway enable'
echo 'No hotspot, DHCP server, router settings, or client settings were provisioned.'
