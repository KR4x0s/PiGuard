#!/usr/bin/python3
"""IPv4 routed PiGuard gateway. Fixed commands + JSON output for a future UI.

normal: Pi-hole/ML + ordinary NAT; tor: filtered DNS and TCP through Tor;
blocked: downstream Internet stopped. No automatic fallback from tor to normal.
"""
import argparse
import fcntl
import ipaddress
import json
import os
from pathlib import Path
import pwd
import re
import subprocess
import sys
import tempfile
import time

from tor_mode import check_connection

CONFIG = Path('/etc/piguard-tor/gateway.json')
MODE = Path('/etc/piguard-tor/mode')
NFT = '/usr/sbin/nft'
IP = '/usr/sbin/ip'
SYSTEMCTL = '/usr/bin/systemctl'
PIHOLE = '/usr/local/bin/pihole'
TABLE = 'piguard_gateway'
SERVICES = ['piguard-tor.service', 'piguard-tor-dns.service']
MODES = {'normal', 'tor', 'blocked'}


def command(args, *, data=None, timeout=30, required=True):
    result = subprocess.run(args, input=data, text=True, capture_output=True,
                            timeout=timeout, check=False)
    if required and result.returncode:
        raise RuntimeError(f'{Path(args[0]).name} failed: {result.stderr.strip()[:500]}')
    return result


def load_config(path=CONFIG):
    cfg = json.loads(Path(path).read_text())
    if not isinstance(cfg, dict) or set(cfg) != {'profile', 'uplink', 'downlink', 'gateway'}:
        raise ValueError('Configuration must contain only profile, uplink, downlink, gateway.')
    if any(not isinstance(value, str) for value in cfg.values()):
        raise ValueError('All configuration values must be strings.')
    if cfg['profile'] not in {'home', 'travel'}:
        raise ValueError('Profile must be home or travel.')
    for field in ('uplink', 'downlink'):
        name = cfg[field]
        if not isinstance(name, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,15}', name) or name == 'lo':
            raise ValueError('Use an ordinary dedicated interface name, not a bridge/VLAN/loopback.')
    if cfg['uplink'] == cfg['downlink']:
        raise ValueError('Uplink and downlink must be separate interfaces.')
    addr = ipaddress.IPv4Interface(cfg['gateway'])
    private_ranges = [ipaddress.ip_network(x) for x in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16')]
    if (not any(addr.network.subnet_of(n) for n in private_ranges)
            or not 16 <= addr.network.prefixlen <= 29
            or addr.ip in {addr.network.network_address, addr.network.broadcast_address}):
        raise ValueError('Gateway must be a usable RFC1918 IPv4 address with prefix /16 to /29.')
    cfg['gateway'] = str(addr)
    return cfg


def tor_config(cfg):
    address = ipaddress.IPv4Interface(cfg['gateway']).ip
    return f'''# Managed by PiGuard. Transport ports are restricted by the gateway guard.
ClientOnly 1
SocksPort 127.0.0.1:9060 IsolateSOCKSAuth
TransPort {address}:9040 IsolateClientAddr
TransProxyType default
# DNSCrypt uses a pinned resolver IP; it performs no local hostname lookup.
SafeSocks 0
SafeLogging 1
DataDirectory /var/lib/piguard-tor
Log notice stdout
RunAsDaemon 0
ControlPort 0
ORPort 0
DirPort 0
'''


def rules(cfg, mode, pihole_uid, dns_uid):
    if mode not in MODES:
        raise ValueError('Invalid mode.')
    if any(type(uid) is not int or uid <= 0 for uid in (pihole_uid, dns_uid)):
        raise ValueError('Services must use dedicated non-root users.')
    down, up = cfg['downlink'], cfg['uplink']
    addr = ipaddress.IPv4Interface(cfg['gateway'])
    net = str(addr.network)
    # Delete/recreate only our table, in one nft transaction (never flush ruleset).
    lines = [f'table inet {TABLE} {{',
             ' chain ingress { type filter hook prerouting priority -310; policy accept;',
             f'  iifname "{down}" meta nfproto ipv6 counter drop',
             f'  iifname "{down}" udp sport 68 udp dport 67 accept',
             f'  iifname "{down}" ip saddr != {net} counter drop', ' }',
             ' chain input { type filter hook input priority -5; policy accept;',
             f'  iifname "{up}" udp sport 68 udp dport 67 counter drop',
             f'  iifname "{up}" meta l4proto {{ tcp, udp }} th dport 53 counter drop',
             f'  iifname "{up}" tcp dport {{ 80, 443, 8080, 8090 }} counter drop',
             f'  iifname != "{down}" tcp dport 9040 counter drop',
             f'  iifname "{down}" udp sport 68 udp dport 67 accept',
             f'  iifname "{down}" tcp dport 443 accept']
    if mode != 'blocked':
        lines += [f'  iifname "{down}" meta l4proto {{ tcp, udp }} th dport 53 accept']
    if mode == 'tor':
        lines += [f'  iifname "{down}" tcp dport 9040 ct status dnat accept']
    lines += [f'  iifname "{down}" counter drop', ' }',
              ' chain forward { type filter hook forward priority -5; policy accept;']
    if mode == 'normal':
        lines += [f'  iifname "{down}" oifname "{up}" ip saddr {net} accept',
                  f'  iifname "{up}" oifname "{down}" meta nfproto ipv4 ct state established,related accept']
    lines += [f'  iifname "{down}" counter drop', f'  oifname "{down}" counter drop', ' }',
              ' chain dns_egress { type filter hook output priority -5; policy accept;',
              f'  meta skuid {dns_uid} ip daddr 127.0.0.1 tcp dport 9060 accept',
              f'  meta skuid {dns_uid} ct direction reply accept',
              f'  meta skuid {dns_uid} counter drop',
              f'  meta skuid {pihole_uid} oifname "{up}" udp sport 67 udp dport 68 counter drop']
    if mode != 'normal':
        # A DHCP OFFER/ACK may be broadcast, so conntrack does not always
        # classify it as a reply. Keep lease renewal available in Tor and
        # blocked modes without permitting Pi-hole egress on the uplink.
        lines += [f'  meta skuid {pihole_uid} oifname "{down}" udp sport 67 udp dport 68 accept',
                  f'  meta skuid {pihole_uid} ct direction reply accept',
                  f'  meta skuid {pihole_uid} ip daddr 127.0.0.1 meta l4proto {{ tcp, udp }} th dport 9053 accept',
                  f'  meta skuid {pihole_uid} counter drop']
    lines += [' }', ' chain prerouting { type nat hook prerouting priority -110; policy accept;']
    if mode != 'blocked':
        lines += [f'  iifname "{down}" meta nfproto ipv4 meta l4proto {{ tcp, udp }} th dport 53 redirect to :53']
    if mode == 'tor':
        # DNS is handled above. Never send private/local destinations to exits.
        reserved = ('0.0.0.0/8, 10.0.0.0/8, 100.64.0.0/10, 127.0.0.0/8, '
                    '169.254.0.0/16, 172.16.0.0/12, 192.0.0.0/24, 192.0.2.0/24, '
                    '192.168.0.0/16, 198.18.0.0/15, 198.51.100.0/24, 203.0.113.0/24, '
                    '224.0.0.0/4, 240.0.0.0/4')
        lines += [f'  iifname "{down}" ip daddr {{ {reserved} }} return',
                  f'  iifname "{down}" meta nfproto ipv4 tcp flags & (fin | syn | rst | ack) == syn redirect to :9040']
    lines += [' }', ' chain output_nat { type nat hook output priority -110; policy accept;']
    if mode != 'normal':
        lines += [f'  meta skuid {pihole_uid} meta nfproto ipv4 meta l4proto {{ tcp, udp }} th dport 53 redirect to :9053']
    lines += [' }', ' chain postrouting { type nat hook postrouting priority 110; policy accept;']
    if mode == 'normal':
        lines += [f'  iifname "{down}" oifname "{up}" ip saddr {net} masquerade']
    lines += [' }', '}', '']
    return '\n'.join(lines)


def read_mode():
    # Missing/corrupt state is blocked, never silently normal.
    try:
        mode = MODE.read_text().strip()
    except FileNotFoundError:
        return 'blocked'
    return mode if mode in MODES else 'blocked'


def save_mode(mode):
    if mode not in MODES:
        raise ValueError('Invalid mode.')
    fd, name = tempfile.mkstemp(dir=MODE.parent, prefix='.mode-')
    try:
        with os.fdopen(fd, 'w') as f:
            f.write(mode + '\n')
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, MODE)
        directory = os.open(MODE.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(name).unlink(missing_ok=True)


def apply_rules(cfg, mode):
    pihole_uid = pwd.getpwnam('pihole').pw_uid
    dns_uid = pwd.getpwnam('piguard-tor-dns').pw_uid
    exists = command([NFT, 'list', 'table', 'inet', TABLE], required=False).returncode == 0
    content = (f'delete table inet {TABLE}\n' if exists else '') + rules(cfg, mode, pihole_uid, dns_uid)
    command([NFT, '--check', '--file', '-'], data=content)
    command([NFT, '--file', '-'], data=content)


def preflight(cfg, require_forward=True):
    addresses = json.loads(command([IP, '-j', 'address', 'show']).stdout)
    by_name = {a['ifname']: a for a in addresses}
    for name in (cfg['uplink'], cfg['downlink']):
        if name not in by_name or 'master' in by_name[name] or Path('/sys/class/net', name, 'bridge').exists():
            raise RuntimeError('Two existing, unbridged interfaces are required.')
    down = by_name[cfg['downlink']]
    expected = ipaddress.IPv4Interface(cfg['gateway'])
    if not any(a.get('family') == 'inet' and a.get('local') == str(expected.ip)
               and a.get('prefixlen') == expected.network.prefixlen for a in down['addr_info']):
        raise RuntimeError('Configure the dedicated downstream gateway address first.')
    if any(a.get('family') == 'inet' and ipaddress.ip_interface(f"{a['local']}/{a['prefixlen']}").network.overlaps(expected.network)
           for a in by_name[cfg['uplink']]['addr_info']):
        raise RuntimeError('Upstream and downstream subnets overlap.')
    routes = json.loads(command([IP, '-j', 'route', 'show', 'default']).stdout)
    if not routes or any(r.get('dev') != cfg['uplink'] for r in routes):
        raise RuntimeError('The only IPv4 default route must use the configured uplink.')
    if 'flowtable' in command([NFT, '-j', 'list', 'ruleset']).stdout:
        raise RuntimeError('Disable nft flowtable/offload before using this gateway.')
    pid = command([SYSTEMCTL, 'show', 'pihole-FTL.service', '--property=MainPID', '--value']).stdout.strip()
    if not pid.isdecimal() or int(pid) <= 0:
        raise RuntimeError('Pi-hole must be running.')
    process = Path('/proc', pid, 'status').read_text()
    uid_line = next((line for line in process.splitlines() if line.startswith('Uid:')), '')
    if not uid_line or any(int(uid) != pwd.getpwnam('pihole').pw_uid for uid in uid_line.split()[1:]):
        raise RuntimeError('Pi-hole must run entirely as the pihole user for DNS egress enforcement.')
    if require_forward and Path('/proc/sys/net/ipv4/ip_forward').read_text().strip() != '1':
        raise RuntimeError('Configure IPv4 forwarding before activating the gateway.')


def verify_dns(attempts=3):
    # Exercise Pi-hole itself, including its captured upstream query path.
    # DNSCrypt can report its service active before its first Tor-backed DoH
    # server is ready. Keep clients blocked through bounded retries.
    for attempt in range(attempts):
        result = command(['/usr/bin/dig', '@127.0.0.1', 'example.com', 'A', '+short',
                          '+time=10', '+tries=1'], timeout=15, required=False)
        if result.returncode == 0 and any(
            re.fullmatch(r'\d+\.\d+\.\d+\.\d+', line)
            and not ipaddress.ip_address(line).is_unspecified
            for line in result.stdout.splitlines()
        ):
            return
        if attempt + 1 < attempts:
            time.sleep(5)
    raise RuntimeError('Pi-hole did not return a usable DNS answer after retries. Gateway remains blocked.')


def wait_for_pihole(timeout=60, proc_root=Path('/proc')):
    """Let FTL finish starting before a boot-time Tor transition begins.

    The persistent guard is already loaded. In particular, do not persist
    ``blocked`` merely because systemd started this unit a second before FTL.
    """
    for attempt in range(timeout):
        pid = command([SYSTEMCTL, 'show', 'pihole-FTL.service',
                       '--property=MainPID', '--value'], required=False).stdout.strip()
        if pid.isdecimal() and int(pid) > 0 and (proc_root / pid / 'status').exists():
            return
        if attempt + 1 < timeout:
            time.sleep(1)
    raise RuntimeError('Pi-hole did not start; gateway guard remains loaded.')


def transition(cfg, target):
    # Persist the guarded state first. Any failure/crash retries from blocked at boot.
    save_mode('blocked')
    apply_rules(cfg, 'blocked')
    if target == 'tor':
        preflight(cfg)
        command([SYSTEMCTL, 'start', *SERVICES], timeout=60)
        # A cold Tor start can take longer than one HTTPS check while loading
        # relay descriptors. Keep the client blocked during one bounded retry.
        for attempt in range(2):
            try:
                check_connection()
                break
            except RuntimeError:
                if attempt:
                    raise
                time.sleep(5)
        # Flush pre-Tor DNS cache without stopping FTL, which also serves client DHCP.
        command([PIHOLE, 'reloaddns'], timeout=30)
        preflight(cfg)
        verify_dns()
        for service in SERVICES:
            command([SYSTEMCTL, 'is-active', '--quiet', service])
    else:
        command([SYSTEMCTL, 'stop', *SERVICES], timeout=60)
    if target != 'blocked':
        apply_rules(cfg, target)
        try:
            save_mode(target)
        except Exception:
            apply_rules(cfg, 'blocked')
            raise
    return {'mode': target, 'profile': cfg['profile'], 'client_path': 'not_yet_verified',
            'message': 'Client devices must use the dedicated downstream network.'}


def get_status(cfg):
    loaded = command([NFT, '-j', 'list', 'table', 'inet', TABLE], required=False)
    services = {}
    for name in SERVICES:
        services[name] = command([SYSTEMCTL, 'is-active', name], required=False).stdout.strip() or 'unknown'
    return {'mode': read_mode(), 'profile': cfg['profile'], 'uplink': cfg['uplink'],
            'downlink': cfg['downlink'], 'guard_present': loaded.returncode == 0,
            'services': services, 'client_path': 'not_checked',
            'note': 'Mode and service state do not prove client traffic uses Tor.'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['validate', 'render', 'enable', 'disable', 'block',
                                         'status', 'check', 'boot-guard', 'resume'])
    parser.add_argument('--config', type=Path)
    parser.add_argument('--mode', choices=sorted(MODES), default='tor', help='render only')
    args = parser.parse_args(argv)
    try:
        if args.config and args.action not in {'validate', 'render'}:
            raise ValueError('Live operations use only the fixed root-owned installed configuration.')
        cfg = load_config(args.config or CONFIG)
        if args.action == 'validate':
            print(json.dumps(cfg, indent=2))
            return 0
        if args.action == 'render':
            print(rules(cfg, args.mode, 1001, 1002), end='')
            return 0
        if os.geteuid() != 0:
            raise RuntimeError('Run this fixed gateway control command with sudo on the Pi.')
        # Serializes CLI, dashboard broker, and boot operations.
        Path('/run/piguard-gateway').mkdir(mode=0o700, exist_ok=True)
        with open('/run/piguard-gateway/control.lock', 'a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if args.action in {'enable', 'disable', 'block'}:
                target = {'enable': 'tor', 'disable': 'normal', 'block': 'blocked'}[args.action]
                result = transition(cfg, target)
            elif args.action == 'boot-guard':
                apply_rules(cfg, read_mode())
                result = {'mode': read_mode(), 'guard': 'loaded'}
            elif args.action == 'resume':
                if read_mode() == 'tor':
                    wait_for_pihole()
                    result = transition(cfg, 'tor')
                else:
                    result = {'mode': read_mode()}
            elif args.action == 'check':
                if read_mode() != 'tor':
                    raise RuntimeError('Tor mode is not selected.')
                result = check_connection()
                verify_dns()
                result['dns'] = 'Pi-hole answer verified; client path still requires a client test'
            else:
                result = get_status(cfg)
        print(json.dumps(result, indent=2))
        return 0
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({'error': str(exc), 'client_path': 'unverified'}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
