#!/usr/bin/env bash
# Run on KREO through interactive SSH after eth0 is 10.78.0.1/24.
set -euo pipefail

ip -4 -j address show eth0 | python3 -c 'import json,sys; data=json.load(sys.stdin); assert any(a.get("local")=="10.78.0.1" and a.get("prefixlen")==24 for d in data for a in d.get("addr_info",[]))'
test "$(cat /sys/class/net/eth0/carrier)" = 1 || { echo 'No Ethernet carrier on eth0.' >&2; exit 1; }
sudo -v

sudo install -d -o root -g root -m 0700 /etc/piguard-web
backup=/etc/piguard-web/pihole.toml.before-downstream
if [[ ! -f "$backup" ]]; then
  sudo cp -p /etc/pihole/pihole.toml "$backup"
fi
restore() {
  echo 'Pi-hole setup failed; restoring its previous configuration.' >&2
  sudo cp -p "$backup" /etc/pihole/pihole.toml
  sudo systemctl restart pihole-FTL.service
}
trap restore ERR

sudo pihole-FTL --config dns.interface eth0
sudo pihole-FTL --config dns.listeningMode SINGLE
sudo pihole-FTL --config dhcp.start 10.78.0.100
sudo pihole-FTL --config dhcp.end 10.78.0.199
sudo pihole-FTL --config dhcp.router 10.78.0.1
sudo pihole-FTL --config dhcp.netmask 255.255.255.0
sudo pihole-FTL --config dhcp.ipv6 false
sudo pihole-FTL --config dhcp.active true
sudo systemctl restart pihole-FTL.service
sudo systemctl is-active --quiet pihole-FTL.service
dig +time=3 +tries=1 @10.78.0.1 example.com A | grep -q 'status: NOERROR'
sudo pihole-FTL --config dns.interface | grep -qx eth0
sudo pihole-FTL --config dns.listeningMode | grep -qx SINGLE
sudo pihole-FTL --config dhcp.active | grep -qx true

trap - ERR
echo 'Pi-hole DNS and DHCP are configured for the protected Ethernet network.'
echo 'The laptop should renew its Ethernet lease and receive 10.78.0.100-199, gateway 10.78.0.1, DNS 10.78.0.1.'
