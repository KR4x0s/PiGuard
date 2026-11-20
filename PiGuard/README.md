# PiGuard — Raspberry Pi implementation

For a generalized home and public Wi-Fi procedure, see
[`NETWORK_SETUP_GUIDE.md`](NETWORK_SETUP_GUIDE.md). The installation-specific
example is in [`HOME_AND_PUBLIC_WIFI.md`](HOME_AND_PUBLIC_WIFI.md). Older
commissioning status notes below are retained as historical evidence.

Target: Raspberry Pi 3B+. The connected device reports a 59.5 GiB SD card (64 GB nominal), superseding the earlier 32 GB plan. This folder starts hardware commissioning; the existing training and inference package is in `../PiGuard_ML/`.

## Live status — 2026-10-26

The Jio router already reserves `192.168.31.235` for the Pi `wlan0` MAC
`b8:27:eb:b6:90:6e`; both values were checked in the router and on the Pi.
The gateway, private dashboard, Pi-hole, alert-only ML observer, and Tailscale
Serve are installed. A boot with no Ethernet carrier exposed a NetworkManager
address problem: nginx could not bind to `10.78.0.1`, and gateway resume failed.
`scripts/repair_boot_runtime.sh` installed an `eth0`-only `ignore-carrier`
setting, restarted those units, and disabled the noisy ACL directory watcher;
the ACL refresh timer remains active. The Pi then reported no failed systemd
units, `throttled=0x0`, DNS ready, and a Tor exit on a Pi-side SOCKS check.
The dashboard and Pi-hole DNS are inaccessible from ordinary Jio Wi-Fi, as
intended. On the wired Omarchy laptop, Wi-Fi was disabled, DHCP gave
`10.78.0.119/24` with gateway and DNS `10.78.0.1`, and the Tor check returned
`IsTor:true`. Pi-hole blocked `doubleclick.net`; DNS requests aimed at external
UDP and TCP resolvers were intercepted and received the same block answer.
The laptop had no IPv6 default route. Three reboot checks passed, including one
with Ethernet unplugged: `eth0` retained `10.78.0.1/24`, nginx and Tor started,
and the laptop again confirmed Tor and the Pi-hole block after reconnection.
The ML observer briefly reported a source-access error on the first two
reboots while Pi-hole recreated its SQLite sidecar files. The ACL timer was
then given extra early-boot refreshes. On the third reboot the observer logged
no source error, the saved Tor mode resumed, and the health endpoint settled
at `ready=true`, `dns_ready=true` with no failed systemd units. ML readiness
still has a boot warm-up while Pi-hole, Tor, and the first observer poll start.

The operator has since chosen a different home layout: Jio LAN to Pi `eth0`,
and the Pi's built-in `wlan0` as the protected hotspot. The switch in
`scripts/home_hotspot.sh` is active: the Pi reports `eth0` as its only IPv4
default route, `wlan0` as `PiGuard-Home` at `10.78.0.1/24`, Home + Tor in the
private dashboard, and active Pi-hole, Tor, DNSCrypt, dashboard, and observer
services. The Omarchy laptop joined `PiGuard-Home`, received `10.78.0.152/24`
with gateway and DNS `10.78.0.1`, reported `IsTor:true`, and received Pi-hole's
`0.0.0.0` block for `doubleclick.net` both directly and through a DNS request
aimed at `1.1.1.1`. It had no IPv6 default route. A second device obtained
`10.78.0.165` and reported `IsTor:true` with its other Internet link off.
A reboot restored the Home + Tor mode, `PiGuard-Home`, Jio Ethernet DHCP,
Pi-hole, Tor, DNSCrypt, dashboard, and ML observer with no failed systemd
units. The operator reported the laptop's Tor and Pi-hole tests still passed
after reboot, and the phone again reported `IsTor:true` on the protected Wi-Fi
with mobile data off. The Pi briefly reached its soft temperature limit during boot;
the active limit cleared, temperature fell to about 52°C, and the dashboard
now treats the past event as a warning while continuing to block Tor control
for active heat or undervoltage. Public Wi-Fi travel testing remains deferred.
The public Wi-Fi travel trial is deferred by the operator.
Longer-term alert burden and combined gateway resource use are not established
by these checks. The dated notes below describe earlier commissioning stages
and are retained as history.

## Current state — 2026-10-25

Pi-hole Core v6.5 / FTL v6.8 and the PiGuard evaluated alert-only ML observer/dashboard are installed and running on the Raspberry Pi 3B+. The active release is `/opt/piguard/releases/20261025T134356Z-fc4f50f35b2f`. The model, collector, dashboard, DNS probe, and private loopback HTTP health endpoint report ready. The observer has advanced through live persisted DNS records after the final upgrade. The installer enabled both services and the scoped database-access helper at boot. The 67-test suite passed on Mac and Pi; final-release reference predictions matched on Pi. See `../PiGuard_ML/README.md` and `../PiGuard_ML/IMPLEMENTATION_STATUS.md`.

The compact forest passed the locked Pi resource policy: 178.40 MiB peak scorer RSS and 1,205.57 ms p95 for 500 uncached labels, within the 256 MiB and 2,000 ms limits. Its one-time held-out test measured 56.81% recall and 0.76% false-positive rate on 13,683 public rows. This does not establish household detection precision or unseen-family performance. One-client DNS verification, DNS latency comparison, and seven-day alert review remain open.

Mac Wi-Fi DNS is **automatic**. A 2026-10-25 retry using Pi-hole DNS caused ChatGPT to repeatedly reconnect; returning to automatic DNS restored connectivity, as confirmed by the user. Keep client DNS unchanged until the application-path issue is investigated. PiGuard ML runs asynchronously after Pi-hole answers DNS and did not cause that earlier incident. Tailscale is not installed. Administrative Pi commands require the operator's sudo password in their own terminal.

## 1. Establish access

Connect the Pi to the router (Ethernet preferred for the baseline) and finish the OS first-boot setup. Run these in the Pi terminal:

```bash
whoami
hostname -I
cat /etc/os-release
uname -m
```

If SSH is disabled, run `sudo raspi-config`, then choose Interface Options → SSH → Enable. From the Mac, connect using `ssh USERNAME@PI_IP`. Replace these placeholders with observed values. Verify a new host fingerprint against the Pi's `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub`; do not disable host verification. Enter passwords in your own terminal, not chat.

Copy this folder from the Mac after SSH works:

```bash
scp -r '/Users/kratos_2004/Downloads/Major Proj/PiGuard' USERNAME@PI_IP:~/
```

On the Pi, save the baseline:

```bash
cd ~/PiGuard
umask 077
bash scripts/preflight.sh > "evidence/preflight-$(date -u +%Y%m%dT%H%M%SZ).txt"
```

Review OS support, disk space, clock, power warnings, and any existing process on DNS port 53 before installation. A preflight exit of zero means the snapshot completed, not that every check passed. Reserve the Pi's LAN address in the router's DHCP settings. Keep the router as DHCP server during initial commissioning.

## 2. Install and test local DNS

For this connected Pi, run the prepared installer from a Mac terminal:

```bash
ssh -t -i ~/.ssh/piguard_ed25519 -o IdentitiesOnly=yes krat0s@KREO.local 'bash ~/PiGuard/scripts/install_pihole.sh'
```

It captures a preflight snapshot, installs DNS diagnostic tools, downloads the official installer, records its hash, opens its interactive wizard, and checks local DNS afterward. It does not perform a full OS upgrade. Enter the sudo password only in your terminal. The equivalent manual steps are below.

Once the baseline is reviewed, on the Pi:

```bash
sudo apt update
sudo apt install curl ca-certificates dnsutils python3 python3-venv
```

Reboot after OS/kernel updates as needed and reconnect. Download the official Pi-hole installer to a temporary file and run it only after a successful download:

```bash
installer=$(mktemp)
if curl --fail --show-error --location https://install.pi-hole.net --output "$installer"; then
    sudo bash "$installer"
fi
rm -f "$installer"
```

Select the verified network interface and upstream resolver, accept the initial recommended blocklist, and enable query logging for the controlled test. Plain Cloudflare upstream IPs do not provide encrypted DNS. Record the selected options. Keep DHCP disabled in Pi-hole. Use the installer-reported admin URL and retain its password privately; `sudo pihole setpassword` changes it interactively.

On the Pi, test local resolution:

```bash
cd ~/PiGuard
python3 scripts/check_dns.py 127.0.0.1 --output "evidence/dns-local-$(date -u +%Y%m%dT%H%M%SZ).json"
```

Repeat the same script on the Mac with the Pi's LAN IP to test client reachability. IPv6 record lookup (AAAA) over an IPv4 server address does not test IPv6 transport; repeat against a configured Pi IPv6 address separately if used.

For controlled blocking: first check that `example.org` resolves, then add `example.org` as an exact deny entry in Pi-hole's admin UI. Query it explicitly using `dig @PI_IP example.org A` and inspect the matching query-log entry for the blocking reason. Remove only the temporary entry you added and confirm resolution returns. An NXDOMAIN or null address alone is not proof that Pi-hole blocked it.

## 3. Verify one ordinary client

Record its previous DNS settings, then configure just one test device to use the Pi. Keep alternate resolvers and browser secure-DNS settings in the evidence record because they can bypass filtering. Exercise normal browser/application requests and match them to Pi-hole's query log. Repeat controlled blocking through the client's normal DNS path. Explicit `dig @PI_IP` tests alone do not establish application integration.

Repeat the checks after rebooting the Pi. Restore the client's previous DNS settings if resolution fails. Expand to router-wide DNS only after one-client operation and recovery are verified; check DHCP-advertised IPv6 DNS too. Do not forward public router ports to Pi-hole.

## 4. Next implementation stages

1. Tailscale enrollment and remote DNS from one authorized device, verified off the home Wi-Fi: pending.
2. Trained candidate transfer, dependency compatibility, Pi prediction parity, held-out final evaluation, and final service activation: completed.
3. Read-only Pi-hole query observer with separate alert storage and retention: running; live restart recovery still to verify.
4. Private status/review interface: running; controlled DNS overhead, combined peak memory, and seven-day alert behavior still to evaluate.

ML starts in alert-only mode. Optional home/travel Tor gateway backend source is in
[`tor/README.md`](tor/README.md), with CLI and dashboard broker controls. It
requires a separate downstream network; it is not installed
or active on the live Pi. A DNS-only deployment does not route clients through Tor.
The combined dashboard source is built in `../PiGuard_ML/` and the fixed-command
broker/frontend installer is in `scripts/` and `deploy/`. It has passed local
tests and a synthetic browser preview, but is not installed on the live Pi.
The Pi still reports undervoltage/throttling `0x50005`; do not claim gateway
readiness until power and client-path validation are complete. See the gateway
validation record for test limits.

## Evidence

Keep device snapshots and test JSON under `evidence/`. These may contain local network identifiers and are excluded from version control. Label each run with its network connection, client, configuration, and reboot state. Local script validation is separate from real Pi measurements.

Official references checked on 2026-10-24:

- [Raspberry Pi SSH access](https://www.raspberrypi.com/documentation/computers/remote-access.html)
- [Pi-hole prerequisites](https://docs.pi-hole.net/main/prerequisites/)
- [Pi-hole installation](https://docs.pi-hole.net/main/basic-install/)
- [Pi-hole allow/deny management](https://docs.pi-hole.net/guides/whitelist-blacklist/)

## ML implementation update — 2026-10-25

The alert-only ML runtime, dashboard, evaluated compact-forest release, and installer are implemented in `../PiGuard_ML/`. See its `README.md` and `IMPLEMENTATION_STATUS.md`. All 67 automated tests passed locally after the evaluation change; the earlier suite passed on the Pi. Final-release reference parity passed on the Pi. The evaluated observer and dashboard are active, and the checkpoint advanced through live records after activation. The selected model passed the locked 500-label Pi benchmark and was evaluated once on the held-out set. The original full forest exceeded the memory limit.

Mac Wi-Fi DNS is now **automatic**: the 2026-10-25 Pi-hole retry caused ChatGPT to repeatedly reconnect, and the user confirmed recovery after rollback. Keep the Mac on automatic DNS pending investigation. Do not interpret successful explicit DNS probes as successful ordinary application integration.
