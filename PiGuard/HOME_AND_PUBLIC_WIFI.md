# PiGuard home and public Wi-Fi guide

For a deployment-neutral procedure with placeholders for interface names,
addresses, routers and client operating systems, see
[`NETWORK_SETUP_GUIDE.md`](NETWORK_SETUP_GUIDE.md).

This guide covers the active home hotspot and the earlier wired travel-style
layout. The protected Wi-Fi laptop passed Tor, DNS, and IPv6 checks; a second
device received `10.78.0.165` and reported Tor. After reboot, Home + Tor and
all PiGuard services resumed, and both laptop and phone reported Tor again.

## Current home topology

```text
Internet
   |
Jio router LAN and DHCP
   |
Pi eth0 (DHCP uplink: 192.168.31.116/24)
   |
PiGuard + Pi-hole + Tor gateway
   |
Pi wlan0: PiGuard-Home, 10.78.0.1/24
   |
Protected Wi-Fi
   |
Protected devices: DHCP address 10.78.0.100-199
Gateway and DNS: 10.78.0.1
```

The Pi has two separate network sides:

- `eth0` is the Jio LAN uplink. It uses DHCP from the Jio router.
- `wlan0` is the protected hotspot. It has `10.78.0.1/24` and serves Pi-hole
  DHCP and DNS to connected clients.

Devices connected directly to the Jio router's Wi-Fi do **not** pass through
PiGuard. Pi-hole DHCP now serves `wlan0`; do not enable it on Jio-facing `eth0`.

## Addresses and dashboard

- Local dashboard from the protected network:
  `https://10.78.0.1/`
- Private Tailscale dashboard from an authorized device:
  `https://kreo.tail3b2fbd.ts.net/`
- Home Ethernet uplink uses `192.168.31.116` from Jio DHCP. The Jio router's
  reserved-IP list shows `KREO-LAN` at `192.168.31.116` for Pi `eth0` MAC
  `b8:27:eb:e3:c5:3b`, verified on 2026-10-26.
- The older travel-style home Wi-Fi uplink reservation remains
  `192.168.31.235` for Pi `wlan0` MAC `b8:27:eb:b6:90:6e`.
- Downstream gateway: `10.78.0.1/24` on Pi `wlan0` in home mode.

The self-signed certificate at `https://10.78.0.1/` is for local downstream
access. The Tailscale URL has a publicly trusted certificate and remains private
to the authorized tailnet.

## Earlier wired-client validation

The earlier tested setup used the Pi's Jio Wi-Fi as uplink and Ethernet from the
Pi to one laptop. It is no longer the active home topology.

On 2026-10-26, the Omarchy laptop received `10.78.0.119/24` with gateway and
DNS `10.78.0.1`, returned `IsTor:true` from the Tor Project check, and received
a Pi-hole block response for `doubleclick.net`. The same block response was
seen when querying external UDP and TCP DNS endpoints, demonstrating DNS
interception for those probes. The laptop had no IPv6 default route. After a
Pi reboot with no Ethernet cable attached, `eth0` retained `10.78.0.1/24`,
the saved Tor mode resumed, and the laptop repeated the Tor and block checks
after reconnection.

1. Power the Pi and let it connect to the Jio Wi-Fi through `wlan0`.
2. Connect the laptop to Pi `eth0` with an Ethernet cable or USB Ethernet
   adapter.
3. Turn off Wi-Fi on the protected laptop so it cannot bypass PiGuard:

   ```bash
   nmcli radio wifi off
   ```

4. On the tested Omarchy laptop, activate the Ethernet adapter if necessary:

   ```bash
   nmcli device connect enp0s20f0u2
   ```

   If a different adapter is used, find its name with `nmcli device status`.

5. Confirm the laptop received the correct route and DNS:

   ```bash
   ip -4 route show default
   nmcli -f IP4.ADDRESS,IP4.GATEWAY,IP4.DNS device show enp0s20f0u2
   ```

   Expected values are an address such as `10.78.0.119/24`, gateway
   `10.78.0.1`, and DNS `10.78.0.1`.

6. Open `https://10.78.0.1/`, sign in, and open **Gateway & Tor**.
7. Select the required state:
   - **Tor** sends downstream TCP through Tor. UDP, QUIC and IPv6 forwarding
     are blocked.
   - **Normal** uses direct IPv4 routing through Jio while retaining Pi-hole.
   - **Blocked** stops downstream Internet access.
8. Verify Pi-hole from the laptop:

   ```bash
   dig @10.78.0.1 doubleclick.net A +short
   ```

   The tested block response is `0.0.0.0`.

9. When Tor is selected, verify the client rather than relying on the
   dashboard's Pi-side check:

   ```bash
   curl --disable -4 --silent --show-error --max-time 45 \
     https://check.torproject.org/api/ip
   ```

   The response must contain `"IsTor":true`.

### Earlier Wi-Fi uplink reservation (travel-style profile)

The old wired-client profile used `wlan0` as the Jio uplink. Its Jio reservation
remains useful when restoring that travel-style profile. The current home
hotspot instead uses `eth0` as uplink.

The reservation is already present. To recheck it after a router replacement
or configuration reset, confirm the Pi Wi-Fi MAC and address:

   ```bash
   ip link show wlan0
   ip -4 address show wlan0
   ```

In the Jio router's **Network → LAN IPv4 → List of LAN IPv4 Reserved IPs**, the
`KREO` entry has address `192.168.31.235` and MAC `b8:27:eb:b6:90:6e`.
Recheck the lease after the next Pi reboot.

This reservation stabilizes home SSH and management. It does not change the
protected downstream address and is not used on public Wi-Fi.

## Protected home Wi-Fi for several devices

The built-in Pi Wi-Fi can serve as the protected access point when Jio LAN is
connected to Pi `eth0` as the uplink. This reverses the travel wiring; do not
plug `eth0` into Jio while Pi-hole DHCP is enabled there.

1. With both Ethernet cables unplugged, run
   `sudo bash /home/krat0s/home_hotspot.sh prepare` at the Pi console. It
   disables Pi-hole DHCP, verifies UDP 67 is closed, and changes `eth0` to DHCP.
2. Connect a Jio LAN port to Pi `eth0`. Wait until `eth0` receives a
   `192.168.31.x` DHCP address.
3. At the Pi monitor and keyboard, run
   `sudo bash /home/krat0s/home_hotspot.sh activate`. The command creates
   `PiGuard-Home` with a generated WPA2 password shown only on the Pi console,
   changes Pi `wlan0` to `10.78.0.1/24`, moves Pi-hole DHCP/DNS to `wlan0`, and
   selects Tor after verifying the sole default route uses `eth0`.
4. Join a laptop or phone to `PiGuard-Home`, turn off its other Internet links,
   and verify address `10.78.0.100-199`, gateway/DNS `10.78.0.1`, a Pi-hole
   block, and `IsTor:true` from the client. Repeat after a Pi reboot.

Existing Jio Wi-Fi clients remain outside PiGuard until they join the protected
SSID. To restore the wired travel profile, unplug `eth0` first and run
`sudo bash /home/krat0s/home_hotspot.sh restore` at the Pi console. The public
Wi-Fi travel trial is a separate test and has not yet happened.

## Public Wi-Fi: one protected device

Carry the Pi, its stable power supply, an Ethernet cable, and the laptop's
Ethernet adapter.

1. Connect the laptop to Pi `eth0` and keep laptop Wi-Fi off.
2. Open the local dashboard at `https://10.78.0.1/` and select
   **Restore normal routing** before dealing with a captive portal.
3. Connect Pi `wlan0` to the public Wi-Fi using the Pi desktop network menu or:

   ```bash
   sudo nmtui
   ```

   Select **Activate a connection**, choose the public SSID, and enter its
   credentials locally. Leave `wlan0` on DHCP. Do not assign the home address
   `192.168.31.235` on a public network.
4. If the network has a captive portal, complete it before enabling Tor. The
   most reliable method is the browser on the Pi itself. In normal mode, the
   wired laptop can also try `http://neverssl.com/` to trigger the portal.
5. On the Pi, confirm the public Wi-Fi is the only default route:

   ```bash
   ip -4 route show default
   ```

   The default route must use `wlan0`.
6. Reactivate the laptop Ethernet connection if needed:

   ```bash
   nmcli device connect enp0s20f0u2
   ```

7. Confirm the laptop still receives a `10.78.0.x` address with gateway and DNS
   `10.78.0.1`.
8. Test direct browsing in normal mode. Then open **Gateway & Tor**, select
   **Enable Tor**, and wait for mode **Tor**.
9. Run the client Tor verification command shown above. Only the laptop result
   with `"IsTor":true` confirms that laptop's path.

The public Wi-Fi cannot open PiGuard, Pi-hole or DNS through Pi `wlan0`; the
firewall blocks those uplink-facing services. Use `https://10.78.0.1/` from the
wired laptop. After the public uplink is authenticated, the Tailscale URL may
also work from enrolled devices.

## Recovery

If the laptop has no `10.78.0.x` address:

```bash
nmcli device status
nmcli device connect enp0s20f0u2
```

Reconnect the cable or adapter and retry if the device is unavailable. Confirm
the Pi is powered and `eth0` has link.

If a Tor transition fails, PiGuard intentionally remains **Blocked**. It does
not fall back to direct Internet. Use the local dashboard to retry **Enable
Tor** after the uplink is healthy, or explicitly choose **Restore normal
routing** when direct access is intended.

If a public network blocks Tor, normal mode can still provide Pi-hole-filtered
direct IPv4 access, subject to that network's policy. Do not interpret a
successful Pi-side Tor service check as proof of the laptop path.

Turn laptop Wi-Fi back on only after disconnecting it from the protected test or
when intentionally leaving PiGuard:

```bash
nmcli radio wifi on
```

## Operational limits

- Tor mode supports downstream TCP. It blocks arbitrary UDP, QUIC, ICMP
  forwarding and IPv6 forwarding. Video calls, games and some real-time apps may
  fail unless they fall back to TCP.
- A regular browser behind this gateway does not gain Tor Browser's fingerprint
  protections. Use Tor Browser when anonymity against browser fingerprinting is
  required.
- Application-level encrypted DNS can bypass Pi-hole filtering and ML domain
  visibility, although its TCP traffic still follows the selected gateway path.
- PiGuard ML remains alert-only; it does not automatically block a domain based
  on its score.

