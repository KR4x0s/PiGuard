# Deploy the combined PiGuard dashboard

The source is in `../PiGuard_ML/` and this directory. The Pi had
`vcgencmd get_throttled` = `0x50005` on 2026-10-25. On 2026-10-26 it reported
`throttled=0x0`, and the gateway was enabled. Keep checking power during client
testing; the earlier value is historical.
Use the Pi console for network changes and enter sudo passwords in your own
terminal. Preserve the existing ML release and its `/var/lib/piguard/state.db`.
The commands below record the initial wired-client commissioning path. The
active home layout now uses Jio Ethernet as uplink and the built-in Pi Wi-Fi as
the protected hotspot; use [`HOME_AND_PUBLIC_WIFI.md`](HOME_AND_PUBLIC_WIFI.md)
for current switching, verification, and recovery.

## 1. Upgrade the dashboard code

Copy the packaged source to the Pi. In its staged `PiGuard_ML` directory, run:

```bash
sudo bash scripts/install_pi.sh releases/final-001 fc4f50f35b2f70d976cb10036e0eb6dff2253f5ef54b5c21d685683b33cf8b21
sudo -u piguard env PYTHONPATH=/opt/piguard/current /opt/piguard/current/.venv/bin/python -m piguard.accounts --state /var/lib/piguard/state.db --username YOUR_ADMIN --role admin
sudo -u piguard env PYTHONPATH=/opt/piguard/current /opt/piguard/current/.venv/bin/python -m piguard.accounts --state /var/lib/piguard/state.db --username YOUR_VIEWER --role viewer
```

The account command asks for passwords interactively. No default password is
installed. The dashboard remains loopback-only until the frontend is installed.

## 2. Initial wired-client commissioning (historical)

With console access, keep `wlan0` as the only DHCP uplink/default route. Inspect
`nmcli connection show`. For an existing `eth0` profile, substitute its name:

```bash
sudo nmcli connection modify 'PROFILE_NAME' ipv4.method manual ipv4.addresses 10.78.0.1/24 ipv4.gateway '' ipv4.never-default yes ipv6.method disabled
sudo nmcli connection up 'PROFILE_NAME'
```

If `eth0` has no profile:

```bash
sudo nmcli connection add type ethernet ifname eth0 con-name 'PiGuard downstream' ipv4.method manual ipv4.addresses 10.78.0.1/24 ipv4.never-default yes ipv6.method disabled connection.autoconnect yes
sudo nmcli connection up 'PiGuard downstream'
```

Check `ip -4 addr show eth0` and `ip -4 route show default`. Do not set a gateway
on `eth0`. For the home uplink, reserve the Pi's `wlan0` MAC/current address in
the router's DHCP settings. Public Wi-Fi uplink addresses remain DHCP-assigned.

On the Pi, restrict Pi-hole DNS/DHCP to the protected Ethernet, then check the
actual configuration before activating DHCP:

```bash
sudo pihole-FTL --config dns.interface eth0
sudo pihole-FTL --config dns.listeningMode SINGLE
sudo pihole-FTL --config dhcp.start 10.78.0.100
sudo pihole-FTL --config dhcp.end 10.78.0.199
sudo pihole-FTL --config dhcp.router 10.78.0.1
sudo pihole-FTL --config dhcp.active true
sudo systemctl restart pihole-FTL
```

Connect one laptop to Pi Ethernet. Confirm the laptop gets an address in the
configured range, DNS and gateway `10.78.0.1`, then verify an ordinary query and
a controlled Pi-hole block. Keep the laptop's previous network settings saved.

## 3. Install private HTTPS and the broker

From the staged `PiGuard` directory, after installing Debian `nginx` and
`openssl` from the distribution repositories:

```bash
sudo bash scripts/install_dashboard_frontend.sh
```

The installer moves the Pi-hole web interface to loopback port 8081, places it
under `/pihole/`, starts the fixed-action broker, and serves the site only on
`https://10.78.0.1/`. It saves the previous Pi-hole configuration under
`/etc/piguard-web/`. The generated certificate is self-signed; verify the
printed SHA-256 fingerprint before trusting it on a client device. Do not bypass
a browser certificate warning without checking that fingerprint.

For remote access, enroll the Pi and authorized client devices in Tailscale,
enable MagicDNS/HTTPS, restrict access with tailnet grants, then run on the Pi:

```bash
sudo tailscale serve --bg http://127.0.0.1:8090
tailscale serve status
```

Use the returned private HTTPS URL from an authorized device off home Wi-Fi.
Do not use Funnel or forward a public router port. See the [Tailscale Serve
documentation](https://tailscale.com/docs/reference/tailscale-cli/serve).

## 4. Enable routing only after power and client checks

From the staged `PiGuard` directory, use `tor/travel.example.json` for the
`wlan0` uplink/`eth0` downstream profile. The current home example instead
uses `eth0` uplink/`wlan0` protected AP. After reviewing `validate` and
`render`, run:

```bash
python3 scripts/gateway.py validate --config tor/travel.example.json
python3 scripts/gateway.py render --config tor/travel.example.json --mode tor
sudo bash scripts/install_gateway_deps.sh
sudo bash scripts/install_gateway.sh tor/travel.example.json
```

Installation selects normal routing with Tor off. From the wired laptop, prove
normal Internet access and Pi-hole blocking, then use the dashboard to enable
Tor. Verify `https://check.torproject.org/` **from that laptop**, plus DNS,
IPv6/UDP bypass, Tor failure, reboot, and explicit normal-mode recovery.
Record Pi memory, temperature, power, DNS latency, and throughput. The protected
home access point remains pending until a separate AP is available.
