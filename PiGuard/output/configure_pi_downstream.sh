#!/usr/bin/env bash
# Run on KREO through interactive SSH after a laptop is connected to eth0.
set -euo pipefail

test "$(cat /sys/class/net/eth0/carrier)" = 1 || { echo 'No Ethernet carrier on eth0.' >&2; exit 1; }
ip -4 route show default | grep -q 'dev wlan0' || { echo 'Wi-Fi is not the IPv4 default route.' >&2; exit 1; }
sudo -v

profile=netplan-eth0
backup=/etc/netplan/90-NM-75a1216a-9d1a-30cd-8aca-ace5526ec021.yaml.piguard-before.bak
if [[ ! -e "$backup" ]]; then
  sudo cp -p /etc/netplan/90-NM-75a1216a-9d1a-30cd-8aca-ace5526ec021.yaml "$backup"
fi

sudo nmcli connection modify "$profile" \
  ipv4.method manual ipv4.addresses 10.78.0.1/24 ipv4.gateway '' \
  ipv4.never-default yes ipv6.method disabled connection.autoconnect yes
sudo nmcli connection up "$profile" ifname eth0

ip -4 -j address show eth0 | python3 -c 'import json,sys; data=json.load(sys.stdin); assert any(a.get("local")=="10.78.0.1" and a.get("prefixlen")==24 for d in data for a in d.get("addr_info",[]))'
ip -4 route show default | grep -q 'dev wlan0'
echo 'Downstream Ethernet: 10.78.0.1/24; Wi-Fi remains the default route.'
ip -br addr show eth0
ip -4 route show default
