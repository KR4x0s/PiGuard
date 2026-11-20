# Optional Tor gateway: home and travel

The combined Pi-hole / ML / Tor dashboard source is now in `../PiGuard_ML/`.
CLI operations return JSON to a fixed-command root broker. The Flask dashboard
receives no sudo privileges.

The live Pi has already commissioned the travel-style wired client path on
home Jio Wi-Fi. The home hotspot now runs with Jio Ethernet uplink and built-in
Wi-Fi downlink. Laptop and phone Tor checks passed and repeated after a reboot;
the public Wi-Fi travel trial has not happened.

## Two connection modes

| Profile | Traffic path | Required setup |
| --- | --- | --- |
| Home | Jio LAN → Pi Ethernet uplink → Pi built-in Wi-Fi access point → devices | Protected devices join `PiGuard-Home`; Jio's ordinary Wi-Fi stays separate. |
| Travel | Public Wi-Fi → Pi Wi-Fi uplink → Ethernet → laptop | Laptop Ethernet has the Pi as its gateway and DNS server. Disable the laptop's own public-Wi-Fi connection and other Internet uplinks. Wireless laptop access requires a second Wi-Fi adapter configured as an AP. |

Plugging the Pi into the home router does **not** intercept the router's existing
Wi-Fi/wired clients. Those devices must move behind the Pi or the router must
implement an appropriate routed design. This implementation requires separate,
unbridged interfaces and disjoint upstream/downstream subnets. It refuses a
single-interface setup. The home switch script provisions the hotspot and moves
Pi-hole DHCP from Ethernet to Wi-Fi before the Jio cable is connected.

Start from `home.example.json` or `travel.example.json`. Change the interface names
and gateway subnet to match the actual dedicated downstream network. Provision
that address persistently with the Pi's network manager, and provision DHCP on
that interface (or initially one static client). Do not run a second DHCP server
on the existing router LAN. Example travel addressing:

- Pi Ethernet: `10.78.0.1/24`.
- Laptop Ethernet: `10.78.0.2/24`, gateway `10.78.0.1`, DNS `10.78.0.1`.
- Pi Wi-Fi: DHCP from the public network, supplying the Pi's only IPv4 default route.

Pi-hole must accept requests from the downstream subnet. Use its appropriate
interface/listening configuration; keep its admin UI private. The gateway allows
downstream DHCP, DNS, and the authenticated dashboard's HTTPS port. It blocks
other downstream access to Pi administration. Public Wi-Fi uplink access to DNS
and web administration is blocked. The dashboard frontend is separately installed
after the downstream address exists; the browser cannot configure the network.

## Modes and traffic handling

| Mode | Client Internet | DNS | Persistence |
| --- | --- | --- | --- |
| `normal` (Tor off) | IPv4 NAT through the uplink | Plain TCP/UDP port 53 is redirected to Pi-hole; existing upstream configuration applies | Default at installation |
| `tor` | New client TCP connections redirected to Tor; other forwarded traffic blocked | Pi-hole filters/logs, then its IPv4 DNS upstream traffic is redirected to local DNSCrypt, which sends DoH through Tor | Selected mode survives reboot |
| `blocked` | Stopped | Client DNS stopped | Selected on incomplete/failed transitions or corrupt/missing mode state |

IPv6 forwarding from downstream is blocked in **all three modes**. Tor cannot
transport arbitrary UDP. QUIC, most real-time UDP applications, ICMP, and other
unsupported traffic are blocked in Tor mode; some applications can fall back to
TCP themselves. A stopped or unready Tor process does not restore direct routing.
Only `disable` explicitly selects normal Internet access again.

The Tor transport listens on the configured downstream IPv4 address at TCP 9040.
Its SOCKS listener is loopback-only at 9060. DNSCrypt listens on loopback at 9053,
uses a pinned Cloudflare DoH address/TLS hostname, has no bootstrap resolvers or
remote resolver-list downloads, and cannot make direct Internet connections
under the gateway firewall. It uses TCP through Tor. Pi-hole's upstream files
are not rewritten; nftables captures its port-53 connections by the `pihole` UID.
Other Pi-hole-originated connections are blocked while Tor/blocked mode is selected,
apart from replies and the local DNS relay. Custom upstream ports/private split
DNS may therefore fail. This affects **all clients sharing this Pi-hole**, not
only the downstream subnet, while Tor mode is active.

Pi-hole query logging and the existing alert-only ML observer remain in the DNS
path. Enabling Tor restarts Pi-hole to clear pre-Tor cache and pending queries;
expect a short DNS interruption. HTTPS/DoH inside applications can still bypass
Pi-hole's domain filtering and ML visibility, though their forwarded TCP follows
the Tor path. This is not payload inspection or automatic ML blocking.

Tor routing does not guarantee anonymity: account logins, browser fingerprints,
unencrypted application payloads, and alternate device uplinks can identify a
user. The Pi itself still has ordinary upstream access for administration,
updates, and Tor bootstrap. This mode protects traffic from the designated client
interface, not all Pi-originated traffic or device-to-device traffic on a LAN.
For anonymous browsing, use Tor Browser's privacy protections rather than assuming
a regular browser behind this gateway is equivalent.

## Install after commissioning the downstream network

On the Pi, from the copied `PiGuard` directory:

```bash
python3 scripts/gateway.py validate --config tor/travel.example.json
# Inspect generated policy; render uses illustrative numeric UIDs and makes no changes.
python3 scripts/gateway.py render --config tor/travel.example.json --mode tor
sudo bash scripts/install_gateway_deps.sh
sudo bash scripts/install_gateway.sh tor/travel.example.json
```

Use your edited profile instead of the example. Dependencies are Debian `tor`,
`dnscrypt-proxy`, `nftables`, `dnsutils`, `curl`, Python 3, plus existing Pi-hole v6.
The dependency script temporarily suppresses package service starts, disables
default units belonging to newly installed Tor/DNSCrypt packages, and preserves
existing instances. It refuses to overwrite an existing `policy-rc.d`; an
administrator must use that host's package-management policy in that case.

The installer validates the actual interfaces, route, Pi-hole process UID, and
absence of nft flowtables before changing anything. It requires the downstream
address to exist already. It installs root-owned code/configuration, dedicated
Tor/DNS users, a persistent firewall guard, and IPv4 forwarding. **Tor remains
off; the normal IPv4 gateway is enabled.** It does not change Mac DNS settings.
Existing installations are preserved rather than overwritten by rerunning it.

## Dashboard controls

```bash
sudo piguard-gateway status
sudo piguard-gateway enable     # normal → blocked → verified Tor service/DNS → tor
sudo piguard-gateway check      # check Tor exit and a Pi-hole answer; no mode change
sudo piguard-gateway disable    # blocked → stop Tor/DNS relay → normal IPv4 gateway
sudo piguard-gateway block      # stop client Internet without allowing direct fallback
```

The helper accepts a fixed command set. Live operations cannot supply arbitrary
configuration paths or shell commands. Mutations are serialized with a lock.
`status` shows the selected mode, guard presence, and services; it does **not**
claim a verified client path. `check` makes one HTTPS request to the Tor Project's
check API, with proxy DNS and no direct fallback, and probes Pi-hole. It does not
prove that a laptop is using this gateway.

Mode state is atomically persisted. At boot, the guard restores the selected
policy before the installed NetworkManager/networkd/networking services can
start; those services require a successful guard. The resume service attempts
Tor startup only for a saved Tor mode. Bootstrap can take longer than the bounded
check. A failed attempt stays blocked; inspect logs and retry `enable` once Tor
is ready. Firewall reloads use atomic transactions affecting only
`inet piguard_gateway`, never `flush ruleset`. Do not run another firewall manager
that deletes this table, add flowtable/hardware offload, or bridge the interfaces.

The dashboard uses a narrow authenticated local broker for these fixed actions,
CSRF protection, a clear normal/Tor/blocked state, and an explicit notice before
normal routing is restored. The web process has no general sudo permission and
no Tor control port is exposed. Home/travel profile changes require
recommissioning the physical interfaces and network settings; they are not a
cosmetic switch while traffic is flowing.

## Acceptance on a real protected client

Before treating either profile as ready:

1. Verify normal gateway Internet and Pi-hole blocking from one downstream client.
   Match its DNS query to Pi-hole and subsequent ML observation. Keep alternate
   Wi-Fi, cellular, VPN routes, and browser secure-DNS behavior in the evidence.
2. Enable Tor. From that client, without a separately configured proxy, request
   `https://check.torproject.org/api/ip` and require `IsTor: true`. The helper's
   loopback SOCKS check alone is insufficient.
3. Inspect the **uplink** for direct client destination connections and plaintext
   client DNS. Test external DNS targets, UDP/QUIC and IPv6 bypass attempts.
4. Stop Tor while selected; verify new and already-established client connections
   cannot continue directly. Restart/reenable and test recovery.
5. Reboot in Tor mode, including unavailable Internet/Tor conditions. Verify that
   clients stay blocked until Tor is usable. Explicitly disable and verify normal
   Pi-hole/ML gateway operation returns.
6. Measure combined Pi-hole/ML/Tor/DNS memory, DNS latency, throughput, temperature,
   and power. Configured Tor (192 MiB) and DNSCrypt (96 MiB) limits are caps, not
   evidence that the 1 GB Pi 3B+ can sustain the combined workload.

Useful diagnostics:

```bash
sudo nft list table inet piguard_gateway
sudo journalctl -u piguard-gateway-guard -u piguard-gateway-resume -u piguard-tor -u piguard-tor-dns --since '10 minutes ago'
```

Do not remotely flush the firewall to recover a Tor failure. Use `block`, or
explicitly use `disable` to permit normal routing. Boot-time guard failures can
require local-console repair because the network manager deliberately depends
on the guard. This first implementation does not provide an automated uninstall.

## Validation and sources

See `VALIDATION.md` for what was actually tested and what remains pending.

- [Tor SOCKS protocol and its TCP/DNS behavior](https://spec.torproject.org/socks-extensions.html).
- [Tor manual: transparent proxy and isolation options](https://manpages.debian.org/trixie/tor/tor.1.en.html).
- [DNSCrypt official configuration: TCP and SOCKS support](https://github.com/DNSCrypt/dnscrypt-proxy/blob/master/dnscrypt-proxy/example-dnscrypt-proxy.toml).
- [Pinned resolver source](https://github.com/DNSCrypt/dnscrypt-resolvers/blob/master/v3/public-resolvers.md).
- [Tor Project on using other browsers](https://support.torproject.org/tor-browser/security/using-tor-with-other-browsers/).
