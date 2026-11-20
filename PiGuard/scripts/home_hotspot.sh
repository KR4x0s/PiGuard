#!/usr/bin/env bash
# Convert the commissioned wired-client travel layout into a wired-uplink,
# built-in-Wi-Fi home access point. Run prepare with eth0 unplugged; activate
# from the Pi console after connecting Jio LAN to eth0.
set -euo pipefail
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
umask 077

state=/var/lib/piguard-home-hotspot
config=/etc/piguard-tor/gateway.json
home='{"profile":"home","uplink":"eth0","downlink":"wlan0","gateway":"10.78.0.1/24"}'
eth_profile=netplan-eth0
wifi_profile=netplan-wlan0-TharunJIO
ap_profile=PiGuard-Home
gateway_cmd=/usr/local/lib/piguard-gateway/gateway.py

die() { echo "Home hotspot: $*" >&2; exit 1; }
[[ $EUID -eq 0 && $# -eq 1 ]] || die 'Usage: sudo bash home_hotspot.sh prepare|activate|status|restore'
command -v nmcli >/dev/null && command -v pihole-FTL >/dev/null || die 'NetworkManager and Pi-hole are required.'

read_config() {
  PYTHONPATH=/usr/local/lib/piguard-gateway python3 - "$config" <<'PY'
import sys
from gateway import load_config
c = load_config(sys.argv[1])
print(c['profile'], c['uplink'], c['downlink'])
PY
}

check_eth_unplugged() {
  [[ $(cat /sys/class/net/eth0/carrier 2>/dev/null || echo 0) == 0 ]] ||
    die 'Unplug eth0 first. Its current DHCP server must never touch Jio LAN.'
}

case $1 in
  prepare)
    check_eth_unplugged
    [[ $(read_config) == 'travel wlan0 eth0' ]] || die 'Expected the commissioned travel profile.'
    [[ ! -e $state/prepared ]] || die 'Already prepared. Use status or activate.'
    [[ $(nmcli -g ipv4.method connection show "$eth_profile") == manual ]] || die 'Unexpected eth0 profile.'
    install -d -m 0700 "$state"
    cp -a "$config" "$state/gateway.travel.json"
    cp -a /etc/pihole/pihole.toml "$state/pihole.travel.toml"
    nmcli -g ipv4.method,ipv4.addresses,ipv4.never-default,ipv6.method connection show "$eth_profile" > "$state/eth.travel.txt"
    nmcli -g connection.autoconnect,ipv4.never-default connection show "$wifi_profile" > "$state/wifi.travel.txt"
    # This must happen before eth0 is put on Jio LAN. The second read verifies
    # that Pi-hole wrote its live root-owned configuration.
    pihole-FTL --config dhcp.active false
    [[ $(pihole-FTL --config dhcp.active) == false ]] || die 'Pi-hole DHCP did not disable; keep eth0 unplugged.'
    systemctl restart pihole-FTL.service
    if ss -H -ulpn | awk '$4 ~ /:67$/ {found=1} END {exit !found}'; then
      die 'A DHCP server is still listening on UDP 67; keep eth0 unplugged.'
    fi
    nmcli connection modify "$eth_profile" ipv4.method auto ipv4.addresses '' ipv4.gateway '' ipv4.never-default no ipv4.route-metric 100 ipv6.method disabled
    rm -f /etc/NetworkManager/conf.d/90-piguard-downstream.conf
    nmcli general reload conf
    nmcli connection down "$eth_profile" || true
    touch "$state/prepared"
    echo 'Prepared: Pi-hole DHCP is OFF and eth0 now uses DHCP. Connect Jio LAN to Pi eth0, then run activate at the Pi monitor and keyboard.'
    ;;
  activate)
    [[ -e $state/prepared ]] || die 'Run prepare first with eth0 unplugged.'
    current=$(read_config)
    [[ $current == 'travel wlan0 eth0' || $current == 'home eth0 wlan0' ]] || die "Unexpected gateway profile: $current"
    ui=/home/krat0s/piguard-home-ui
    [[ -f $ui/gateway.py && -f $ui/network.py && -f $ui/setup.html && -f $ui/gateway.html ]] ||
      die 'Staged gateway and dashboard files are missing.'
    [[ $(cat /sys/class/net/eth0/carrier 2>/dev/null || echo 0) == 1 ]] || die 'Connect Jio LAN to eth0 first.'
    # eth0 must already have a DHCP address on the Jio subnet before wlan0
    # stops acting as the management uplink.
    eth_ip=$(nmcli -g IP4.ADDRESS device show eth0 | head -n 1)
    [[ $eth_ip == 192.168.31.*/* ]] || die "eth0 has no Jio DHCP lease yet: ${eth_ip:-none}."
    pihole-FTL --config dhcp.active false
    if ! nmcli -g connection.id connection show "$ap_profile" >/dev/null 2>&1; then
      install -m 0600 /dev/null "$state/wifi-key"
      openssl rand -hex 16 > "$state/wifi-key"
      nmcli connection add type wifi ifname wlan0 con-name "$ap_profile" ssid "$ap_profile" mode ap autoconnect yes
      nmcli connection modify "$ap_profile" 802-11-wireless.band bg 802-11-wireless.channel 6 802-11-wireless-security.key-mgmt wpa-psk 802-11-wireless-security.proto rsn 802-11-wireless-security.psk "$(cat "$state/wifi-key")" ipv4.method manual ipv4.addresses 10.78.0.1/24 ipv4.never-default yes ipv6.method disabled connection.autoconnect-priority 100
    fi
    nmcli connection modify "$wifi_profile" connection.autoconnect no ipv4.never-default yes
    install -m 0755 "$ui/gateway.py" "$gateway_cmd"
    if [[ $current == 'travel wlan0 eth0' ]]; then
      printf '%s\n' "$home" > "$state/gateway.home.json"
      install -m 0644 "$state/gateway.home.json" "$state/gateway.next.json"
      mv -f "$state/gateway.next.json" "$config"
    fi
    # Block clients using the home topology before wlan0 changes role.
    "$gateway_cmd" block
    nmcli connection up "$ap_profile" ifname wlan0
    [[ $(nmcli -g IP4.ADDRESS device show wlan0 | head -n 1) == 10.78.0.1/24 ]] || die 'AP did not receive 10.78.0.1/24; gateway remains blocked.'
    pihole-FTL --config dns.interface wlan0
    pihole-FTL --config dns.listeningMode SINGLE
    pihole-FTL --config dhcp.active true
    systemctl restart pihole-FTL.service nginx.service
    [[ $(pihole-FTL --config dhcp.active) == true && $(pihole-FTL --config dns.interface) == wlan0 ]] || die 'Pi-hole AP settings did not persist.'
    [[ $(ip -4 route show default | wc -l) == 1 && $(ip -4 route show default) == *'dev eth0'* ]] || die 'Expected one default IPv4 route on eth0; gateway remains blocked.'
    "$gateway_cmd" enable
    touch "$state/active"
    release=$(readlink -f /opt/piguard/current)
    [[ -d $release/piguard/templates ]] || die 'Active dashboard release is missing.'
    install -m 0644 "$ui/network.py" "$release/piguard/network.py"
    install -m 0644 "$ui/setup.html" "$release/piguard/templates/setup.html"
    install -m 0644 "$ui/gateway.html" "$release/piguard/templates/gateway.html"
    systemctl restart piguard-dashboard.service
    systemctl reset-failed piguard-gateway-resume.service
    echo 'Home hotspot is active. Connect a client to SSID PiGuard-Home using the password shown below.'
    cat "$state/wifi-key"
    echo 'After client checks, reboot the Pi and repeat them. Travel restore requires unplugging eth0 first.'
    ;;
  status)
    printf 'Profile: %s\n' "$(read_config)"
    printf 'eth0: %s\n' "$(nmcli -g IP4.ADDRESS device show eth0 | head -n 1)"
    printf 'wlan0: %s\n' "$(nmcli -g IP4.ADDRESS device show wlan0 | head -n 1)"
    printf 'DHCP: %s\n' "$(pihole-FTL --config dhcp.active)"
    printf 'DNS interface: %s\n' "$(pihole-FTL --config dns.interface)"
    "$gateway_cmd" status
    ;;
  restore)
    check_eth_unplugged
    [[ -f $state/gateway.travel.json ]] || die 'Travel backup is missing.'
    pihole-FTL --config dhcp.active false
    nmcli connection modify "$ap_profile" connection.autoconnect no 2>/dev/null || true
    nmcli connection down "$ap_profile" 2>/dev/null || true
    nmcli connection modify "$eth_profile" ipv4.method manual ipv4.addresses 10.78.0.1/24 ipv4.gateway '' ipv4.never-default yes ipv6.method disabled
    install -d -m 0755 /etc/NetworkManager/conf.d
    printf '[device-piguard-downstream]\nmatch-device=interface-name:eth0\nignore-carrier=yes\n' > /etc/NetworkManager/conf.d/90-piguard-downstream.conf
    nmcli general reload conf
    nmcli connection up "$eth_profile" ifname eth0
    cp -a "$state/gateway.travel.json" "$config"
    "$gateway_cmd" block
    nmcli connection modify "$wifi_profile" connection.autoconnect yes ipv4.never-default no
    nmcli connection up "$wifi_profile" ifname wlan0
    pihole-FTL --config dns.interface eth0
    pihole-FTL --config dns.listeningMode SINGLE
    pihole-FTL --config dhcp.active true
    systemctl restart pihole-FTL.service nginx.service
    "$gateway_cmd" enable
    rm -f "$state/active" "$state/prepared"
    echo 'Travel profile restored. eth0 is the protected client port again.'
    ;;
  *) die 'Usage: sudo bash home_hotspot.sh prepare|activate|status|restore' ;;
esac
