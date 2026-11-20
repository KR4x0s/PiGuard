# PiGuard generalized network setup guide

This guide applies to PiGuard installations with two separate network
interfaces. It covers home and public Wi-Fi, one wired client, and several
clients behind a protected access point, including the Pi's built-in Wi-Fi
when Ethernet is the uplink. Replace every value in angle brackets
with values from the installation worksheet.

## 1. Installation worksheet

Record these values before changing the network:

| Setting | Meaning | Reference value |
| --- | --- | --- |
| `<UPLINK_IF>` | Pi interface connected to the Internet network | `wlan0` |
| `<DOWNLINK_IF>` | Pi interface connected only to protected clients | `eth0` |
| `<DOWNSTREAM_CIDR>` | Persistent Pi gateway address and prefix | `10.78.0.1/24` |
| `<DOWNSTREAM_NET>` | Protected client subnet | `10.78.0.0/24` |
| `<DHCP_START>` | First protected client address | `10.78.0.100` |
| `<DHCP_END>` | Last protected client address | `10.78.0.199` |
| `<AP_ADDRESS>` | Optional protected AP management address | `10.78.0.2` |
| `<HOME_RESERVED_IP>` | Router-reserved Pi uplink address at home | Router-specific |
| `<LOCAL_DASHBOARD>` | Dashboard on the protected network | `https://10.78.0.1/` |
| `<PRIVATE_DASHBOARD>` | Optional private VPN/Tailscale URL | Installation-specific |

The uplink and downstream networks must not overlap. The Pi must have only one
IPv4 default route, and that route must use `<UPLINK_IF>`.

## 2. Supported layouts

| Setup | Internet side | Protected side | Intended clients |
| --- | --- | --- | --- |
| Home, one device | Pi uplink to home router | Direct Ethernet from Pi | One laptop or desktop |
| Home, several devices with wired uplink | Pi Ethernet to home router LAN | Pi built-in Wi-Fi as AP | Protected Wi-Fi clients |
| Home, several devices with Wi-Fi uplink | Pi Wi-Fi to home router | Separate AP/bridge behind Pi Ethernet | Protected Wi-Fi and wired clients |
| Public Wi-Fi, one device | Pi Wi-Fi to public network | Direct Ethernet from Pi | One laptop |
| Public Wi-Fi, several devices | Pi Wi-Fi to public network | Travel AP/bridge behind Pi | Several protected clients |

Devices that remain connected directly to the home router or public Wi-Fi do
not pass through PiGuard. Connecting the Pi to a network does not automatically
intercept that network's existing devices.

Do not connect `<DOWNLINK_IF>` to the ordinary router LAN while Pi-hole DHCP is
enabled on it. That can place two DHCP servers on the same network. The
downstream side must remain a separate physical network.

## 3. The three address rules

PiGuard uses three different address policies:

1. **Home uplink:** keep the Pi uplink on DHCP and create a DHCP reservation in
   the home router. This gives the Pi a stable home management address without
   hard-coding the router's subnet on the Pi.
2. **Public uplink:** always use DHCP. A home address must never be copied to a
   hotel, campus, café, or mobile-hotspot network.
3. **Protected downstream:** configure a persistent private address on the Pi,
   such as `10.78.0.1/24`. Protected clients use this address as both gateway
   and DNS server.

## 4. Commission the Pi downstream network

Complete this once at installation time. Use local console access or another
recovery path while changing network settings.

1. Identify the interfaces and active NetworkManager profiles:

   ```bash
   ip -br link
   nmcli device status
   nmcli connection show
   ```

2. Keep `<UPLINK_IF>` on DHCP. Do not add a default gateway to the downstream
   profile.
3. If a downstream profile already exists, configure it using its actual name:

   ```bash
   sudo nmcli connection modify "<DOWNLINK_PROFILE>" \
     ipv4.method manual \
     ipv4.addresses <DOWNSTREAM_CIDR> \
     ipv4.gateway "" \
     ipv4.never-default yes \
     ipv6.method disabled \
     connection.autoconnect yes
   sudo nmcli connection up "<DOWNLINK_PROFILE>"
   ```

4. If no profile exists for an Ethernet downstream, create one:

   ```bash
   sudo nmcli connection add type ethernet \
     ifname <DOWNLINK_IF> \
     con-name "PiGuard downstream" \
     ipv4.method manual \
     ipv4.addresses <DOWNSTREAM_CIDR> \
     ipv4.never-default yes \
     ipv6.method disabled \
     connection.autoconnect yes
   ```

5. Verify the result:

   ```bash
   ip -4 address show dev <DOWNLINK_IF>
   ip -4 route show default
   ```

   The downstream address must match `<DOWNSTREAM_CIDR>`. Every default route
   must use `<UPLINK_IF>`.

## 5. Configure Pi-hole DHCP and DNS

Configure Pi-hole only after the downstream interface has its persistent
address.

1. Open the authenticated Pi-hole administration page from PiGuard.
2. Enable DHCP on `<DOWNLINK_IF>` with:
   - range `<DHCP_START>` through `<DHCP_END>`;
   - router `<DOWNSTREAM_GATEWAY>`; this is the address portion of
     `<DOWNSTREAM_CIDR>`;
   - DNS server `<DOWNSTREAM_GATEWAY>`.
3. Make Pi-hole listen on the downstream interface and loopback. Do not expose
   DNS or its web interface on a public uplink.
4. Keep the home router's DHCP server enabled for its ordinary, unprotected
   network.
5. Connect one test client and verify it receives an address inside
   `<DOWNSTREAM_NET>` with the Pi as gateway and DNS.

## 6. Home setup: one protected device

```text
Home router or home AP
        |
   Pi uplink
        |
PiGuard gateway
        |
 Pi downstream Ethernet
        |
 One protected device
```

1. Connect `<UPLINK_IF>` to the home network.
2. Connect the client directly to `<DOWNLINK_IF>`.
3. Disable the client's other Internet paths during verification: Wi-Fi,
   cellular tethering, other Ethernet adapters, and third-party VPNs.
4. Renew or activate the client Ethernet connection.
5. Confirm the client address is in `<DOWNSTREAM_NET>` and its gateway and DNS
   both equal `<DOWNSTREAM_GATEWAY>`.
6. Open `<LOCAL_DASHBOARD>` and sign in.
7. Start in **Normal** mode. Verify ordinary web access and Pi-hole blocking.
8. Select **Enable Tor**, wait for mode **Tor**, and verify Tor from the client.

### Reserve the home uplink address

1. On the Pi, record the uplink MAC address and current address:

   ```bash
   ip link show <UPLINK_IF>
   ip -4 address show dev <UPLINK_IF>
   ```

2. Open the home router's DHCP reservation, address reservation, or static
   lease page.
3. Bind the Pi uplink MAC to `<HOME_RESERVED_IP>`.
4. Reconnect or reboot the Pi and confirm it receives the reserved address.

The reservation is for stable home management. The protected clients continue
to use `<DOWNSTREAM_GATEWAY>`.

## 7. Home setup: protected Wi-Fi for several devices

If the Pi uses **Ethernet as its home uplink**, its built-in Wi-Fi can be the
protected AP. Configure a NetworkManager AP profile with a manual downstream
address, WPA2 or WPA3 password, no default route, and Pi-hole DHCP/DNS bound to
the AP interface. The installation-specific switch and recovery procedure is
in [`HOME_AND_PUBLIC_WIFI.md`](HOME_AND_PUBLIC_WIFI.md).

If the Pi uses **Wi-Fi as its uplink**, use a separate wireless access point or
router in true AP/bridge mode. One Pi radio should not be assumed to serve as
both a reliable uplink and protected AP.

For a separate AP:

1. Configure the downstream AP in **AP/bridge mode**.
2. Disable its DHCP server, NAT and router mode. Pi-hole remains the downstream
   DHCP server.
3. Give the AP a management address such as `<AP_ADDRESS>` inside
   `<DOWNSTREAM_NET>` and outside the DHCP pool.
4. Connect the Pi downstream port to the AP port specified by its AP-mode
   instructions. Avoid ordinary routed WAN mode.
5. Configure a dedicated protected SSID with WPA2 or WPA3 security.
6. Join one test device. Confirm its address, gateway and DNS before adding more
   clients.
7. Use a downstream Ethernet switch if both the AP and wired clients are
   required.

Clients on the original home Wi-Fi remain unprotected. Move each intended
client to the protected SSID.

## 8. Public Wi-Fi setup: one protected device

```text
Public Wi-Fi
     |
 Pi Wi-Fi uplink (DHCP)
     |
 PiGuard gateway
     |
 Direct Ethernet
     |
 One protected device
```

Carry the Pi, a stable power supply, Ethernet cable, and the client's Ethernet
adapter.

1. Connect the client to `<DOWNLINK_IF>` and disable the client's Wi-Fi and
   other uplinks.
2. Open `<LOCAL_DASHBOARD>` and select **Restore normal routing** before
   handling a captive portal.
3. Connect Pi `<UPLINK_IF>` to the public SSID using the desktop network menu or
   `sudo nmtui`. Leave IPv4 on DHCP.
4. Complete any captive portal before enabling Tor. A browser on the Pi is the
   most reliable option because the public network sees the Pi uplink MAC. In
   normal mode, a downstream client can also open a plain HTTP page to trigger
   the portal.
5. Confirm the Pi's default route uses `<UPLINK_IF>`:

   ```bash
   ip -4 route show default
   ```

6. Renew the client Ethernet connection and confirm it received the downstream
   gateway and DNS.
7. Test a normal HTTPS site in **Normal** mode.
8. Select **Enable Tor**. If the transition succeeds, verify Tor from the
   downstream client.

Public uplink users must not be able to reach the PiGuard dashboard, Pi-hole web
interface, or DNS service. Use `<LOCAL_DASHBOARD>` from the protected side. A
private VPN dashboard URL can work after the captive portal allows Internet
access.

Follow the venue's acceptable-use policy. Some managed public networks prohibit
connection sharing or block Tor.

## 9. Public Wi-Fi setup: several protected devices

Use the same uplink procedure as the one-device public setup. On the downstream
side, connect a small AP in bridge mode and follow the AP rules from the home
multi-device setup.

If the Pi has only one Wi-Fi adapter and that adapter is the public uplink, a
second Wi-Fi adapter or a separate travel AP is required for protected wireless
clients. Do not bridge the public network directly to protected clients.

## 10. Client setup and inspection

### Linux with NetworkManager

```bash
nmcli device status
nmcli radio wifi off
nmcli device connect <CLIENT_ETHERNET_IF>
ip -4 route show default
nmcli -f IP4.ADDRESS,IP4.GATEWAY,IP4.DNS device show <CLIENT_ETHERNET_IF>
```

Restore Wi-Fi when intentionally leaving PiGuard:

```bash
nmcli radio wifi on
```

### macOS

Use **System Settings → Network**. Turn Wi-Fi off during verification, connect
Ethernet, and inspect **Details → TCP/IP** and **DNS**. The router and DNS server
must both be `<DOWNSTREAM_GATEWAY>`.

### Windows

Turn Wi-Fi off in **Settings → Network & internet**, connect Ethernet, then run:

```powershell
ipconfig /all
route print -4
```

The Ethernet adapter must show an address inside `<DOWNSTREAM_NET>`, with the Pi
as default gateway and DNS server.

## 11. Mode selection

| Mode | Client Internet | DNS behavior |
| --- | --- | --- |
| **Normal** | Direct IPv4 NAT through the uplink | Pi-hole filters and logs DNS |
| **Tor** | Downstream TCP is redirected through Tor | Pi-hole filters DNS; its upstream DNS uses the Tor path |
| **Blocked** | Client Internet is stopped | Client DNS is stopped |

A failed Tor transition stays **Blocked**. PiGuard does not silently fall back
to a direct connection. Choose **Restore normal routing** only when direct access
is intended.

## 12. Verification checklist

Run tests from the downstream client with every alternate uplink disabled.

1. Confirm the client route and DNS point to `<DOWNSTREAM_GATEWAY>`.
2. Confirm an ordinary domain resolves:

   ```bash
   dig @<DOWNSTREAM_GATEWAY> example.com A +short
   ```

3. Query a domain that is known to be on the installation's Pi-hole blocklist:

   ```bash
   dig @<DOWNSTREAM_GATEWAY> <KNOWN_BLOCKED_DOMAIN> A +short
   ```

   Confirm the matching query and blocking reason in Pi-hole. A null address by
   itself is not sufficient evidence.
4. In **Normal** mode, confirm ordinary HTTPS works and the Tor check reports
   `"IsTor":false`.
5. In **Tor** mode, run:

   ```bash
   curl --disable -4 --silent --show-error --max-time 45 \
     https://check.torproject.org/api/ip
   ```

   The downstream client response must contain `"IsTor":true`.
6. Confirm direct DNS bypass attempts are intercepted according to policy by
   testing both UDP and TCP against an external resolver.
7. Confirm downstream IPv6 Internet access fails when the gateway policy blocks
   IPv6.
8. Reboot the Pi and repeat the client route, DNS, Pi-hole and Tor tests.

The dashboard's Pi-side Tor check proves only that one request from the Pi used
Tor. It cannot prove the downstream client's route.

## 13. Dashboard access

- Use `<LOCAL_DASHBOARD>` from the protected downstream network.
- Record and verify the local certificate fingerprint before accepting a
  self-signed certificate.
- Use `<PRIVATE_DASHBOARD>` only through the authorized private VPN/tailnet.
- Do not enable public router port forwarding or a public tunnel/Funnel.
- Keep the Flask application and native Pi-hole web service on loopback behind
  the authenticated frontend.

## 14. Recovery

### Client receives no downstream address

1. Check the cable, adapter and link lights.
2. Confirm the client Ethernet device is available and reconnect it.
3. Confirm the Pi downstream interface has `<DOWNSTREAM_CIDR>`.
4. Confirm Pi-hole DHCP is active only on `<DOWNLINK_IF>`.

### Client has an address but DNS fails

1. Confirm its DNS server is `<DOWNSTREAM_GATEWAY>`.
2. Query Pi-hole explicitly with `dig` or `nslookup`.
3. Inspect Pi-hole service health and query logs.
4. Check whether PiGuard is deliberately in **Blocked** mode.

### Normal mode has no Internet

1. Check the Pi default route and uplink address.
2. Complete any captive portal.
3. Test the uplink from the Pi.
4. Confirm the public network permits connection sharing.

### Tor mode fails

1. Leave the client blocked while checking the uplink, Tor bootstrap and DNS
   relay health.
2. Retry **Enable Tor** after the underlying service is healthy.
3. Explicitly choose **Restore normal routing** only if direct access is an
   acceptable recovery.

### Dashboard is unavailable

Use the downstream address first. If network access is lost, use local Pi
console access. Do not flush the whole firewall as a recovery shortcut.

## 15. Operational limits

- Tor mode carries downstream TCP. Arbitrary UDP, QUIC, ICMP forwarding and
  IPv6 forwarding are blocked by the current gateway design.
- Video calls, games and other real-time applications may fail in Tor mode.
- A regular browser behind the gateway does not receive Tor Browser's
  fingerprint protections.
- Application-level encrypted DNS can bypass Pi-hole filtering and ML domain
  visibility, although its TCP connection still follows the selected gateway
  path.
- PiGuard ML scores are alert-only review signals. They do not automatically
  block domains and do not prove infection.

