#!/usr/bin/env python3
"""Offline Linux packet tests; run ONLY inside a new user/network namespace.

unshare --user --map-root-user --net python3 tests/namespace_gateway.py
All public-looking addresses below exist solely inside the test namespace.
"""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import gateway

IP = '/usr/sbin/ip'
NFT = '/usr/sbin/nft'
children = []
passed = []


def run(args, **kwargs):
    return subprocess.run(args, text=True, capture_output=True, check=True, timeout=10, **kwargs)


def ns(pid, args):
    return ['nsenter', '-t', str(pid), '-n', *args]


def spawn(args):
    p = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    children.append(p)
    return p


def namespace():
    child = spawn(['unshare', '--net', 'sleep', '180'])
    for _ in range(100):
        if os.readlink(f'/proc/{child.pid}/ns/net') != os.readlink('/proc/self/ns/net'):
            return child.pid
        time.sleep(.01)
    raise RuntimeError('Network namespace did not start')


SERVER = '''
import socket, threading, time
def tcp(port, answer, family=socket.AF_INET):
 s=socket.socket(family); s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
 s.bind(('::' if family==socket.AF_INET6 else '0.0.0.0',port)); s.listen()
 while True:
  c,_=s.accept()
  with c:
   c.recv(4096)
   c.sendall(b'HTTP/1.0 200 OK\\r\\nContent-Length: '+str(len(answer)).encode()+b'\\r\\n\\r\\n'+answer)
def udp(port, answer, address='0.0.0.0'):
 s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); s.bind((address,port))
 while True:
  _,addr=s.recvfrom(4096); s.sendto(answer,addr)
def keep(port):
 s=socket.socket(); s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
 s.bind(('0.0.0.0',port)); s.listen()
 while True:
  c,_=s.accept()
  with c:
   while data:=c.recv(100): c.sendall(data)
for fn,args in TASKS:
 threading.Thread(target=fn,args=args,daemon=True).start()
time.sleep(180)
'''


def server(pid, tasks):
    source = SERVER.replace('for fn,args in TASKS:', 'for fn,args in ' + tasks + ':')
    return spawn(ns(pid, [sys.executable, '-c', source]) if pid else [sys.executable, '-c', source])


def http(pid, url):
    return subprocess.run(ns(pid, ['/usr/bin/curl', '--disable', '--silent', '--noproxy', '*',
                                  '--connect-timeout', '1', '--max-time', '2', url]),
                          text=True, capture_output=True, timeout=4)


def udp(pid, target, port):
    source = f"import socket; s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); s.settimeout(1); s.sendto(b'query',({target!r},{port})); print(s.recv(100).decode())"
    return subprocess.run(ns(pid, [sys.executable, '-c', source]) if pid else [sys.executable, '-c', source],
                          text=True, capture_output=True, timeout=3)


def check(ok, name):
    if not ok:
        raise AssertionError(name)
    passed.append(name)
    print('PASS:', name, flush=True)


def apply(cfg, mode, map_uid=None):
    present = subprocess.run([NFT, 'list', 'table', 'inet', gateway.TABLE], capture_output=True).returncode == 0
    content = gateway.rules(cfg, mode, 1001, 1002)
    if map_uid:
        content = content.replace(f'skuid {map_uid}', 'skuid 0')
    if present:
        content = 'delete table inet piguard_gateway\n' + content
    run([NFT, '-f', '-'], input=content)


def main():
    # Refuse to execute in any namespace already containing a physical interface.
    links = json.loads(run([IP, '-j', 'link']).stdout)
    if [link['ifname'] for link in links] != ['lo'] or os.getuid() != 0:
        raise RuntimeError('Use a NEW unshare --user --map-root-user --net namespace.')
    client, outside = namespace(), namespace()
    for local, remote, pid, local_v4, remote_v4, local_v6, remote_v6 in [
        ('eth0', 'client0', client, '10.78.0.1/24', '10.78.0.2/24', 'fd00:77::1/64', 'fd00:77::2/64'),
        ('wlan0', 'outside0', outside, '192.0.2.1/24', '192.0.2.2/24', 'fd00:88::1/64', 'fd00:88::2/64'),
    ]:
        run([IP, 'link', 'add', local, 'type', 'veth', 'peer', 'name', remote])
        run([IP, 'link', 'set', remote, 'netns', str(pid)])
        run([IP, 'address', 'add', local_v4, 'dev', local])
        run([IP, '-6', 'address', 'add', local_v6, 'dev', local, 'nodad'])
        run([IP, 'link', 'set', local, 'up'])
        for args in [['address', 'add', remote_v4, 'dev', remote],
                     ['-6', 'address', 'add', remote_v6, 'dev', remote, 'nodad'],
                     ['link', 'set', remote, 'up'], ['link', 'set', 'lo', 'up']]:
            run(ns(pid, [IP, *args]))
    run([IP, 'link', 'set', 'lo', 'up'])
    run([IP, 'route', 'add', 'default', 'via', '192.0.2.2'])
    run(ns(client, [IP, 'route', 'add', 'default', 'via', '10.78.0.1']))
    run(ns(client, [IP, '-6', 'route', 'add', 'default', 'via', 'fd00:77::1']))
    run(ns(outside, [IP, 'address', 'add', '8.8.8.8/32', 'dev', 'lo']))
    run(ns(outside, [IP, 'route', 'add', 'default', 'via', '192.0.2.1']))
    run(ns(outside, [IP, '-6', 'route', 'add', 'default', 'via', 'fd00:88::1']))
    run(['/usr/sbin/sysctl', '-w', 'net.ipv4.ip_forward=1', 'net.ipv6.conf.all.forwarding=1'])
    server(outside, "[(tcp,(8080,b'DIRECT')), (keep,(8082,)), (tcp,(8081,b'IPV6',socket.AF_INET6)), (udp,(5000,b'UDP_DIRECT','8.8.8.8'))]")
    fake_tor = server(None, "[(tcp,(9040,b'TOR_REDIRECT'))]")
    server(None, "[(udp,(53,b'PIHOLE')), (udp,(9053,b'DNS_OVER_TOR','127.0.0.1')), (tcp,(9053,b'TCP_DNS_OVER_TOR')), (tcp,(9060,b'SOCKS_ONLY'))]")
    # Allow IPv6 link-local DAD/neighbor discovery to settle in the fresh veths.
    time.sleep(2)
    cfg = {'profile': 'travel', 'uplink': 'wlan0', 'downlink': 'eth0', 'gateway': '10.78.0.1/24'}
    v6url = 'http://[fd00:88::2]:8081'
    for _ in range(3):
        v6_baseline = http(client, v6url)
        if v6_baseline.stdout == 'IPV6':
            break
        time.sleep(1)
    if v6_baseline.stdout != 'IPV6':
        print('IPv6 baseline diagnostics:', v6_baseline, flush=True)
        for pid in (client, outside, os.getpid()):
            print(run(ns(pid, [IP, '-6', 'route'])).stdout, flush=True)
    check(v6_baseline.stdout == 'IPV6', 'IPv6 baseline works before guard')
    apply(cfg, 'normal')
    check(http(client, 'http://8.8.8.8:8080').stdout == 'DIRECT', 'Normal IPv4 uses upstream')
    check(udp(client, '8.8.8.8', 5000).stdout.strip() == 'UDP_DIRECT', 'Normal UDP uses upstream')
    check(udp(client, '1.1.1.1', 53).stdout.strip() == 'PIHOLE', 'External DNS is captured by Pi-hole')
    check(http(client, v6url).returncode != 0, 'IPv6 bypass is blocked')
    persistent_source = '''
import socket,sys
s=socket.create_connection(('8.8.8.8',8082),timeout=1)
for line in sys.stdin:
 try:
  s.sendall(line.encode()); print(s.recv(100).decode().strip(),flush=True)
 except (TimeoutError,OSError): print('BLOCKED',flush=True)
'''
    persistent = subprocess.Popen(ns(client, [sys.executable, '-c', persistent_source]),
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    children.append(persistent)
    persistent.stdin.write('BEFORE\n'); persistent.stdin.flush()
    check(persistent.stdout.readline().strip() == 'BEFORE', 'Existing direct TCP connection works before Tor')
    apply(cfg, 'tor')
    persistent.stdin.write('AFTER\n'); persistent.stdin.flush()
    check(persistent.stdout.readline().strip() == 'BLOCKED', 'Existing direct TCP connection cannot bypass Tor transition')
    persistent.stdin.close()
    check(http(client, 'http://8.8.8.8:8080').stdout == 'TOR_REDIRECT', 'Tor mode redirects client TCP')
    check(udp(client, '8.8.8.8', 5000).returncode != 0, 'Tor mode blocks unsupported UDP')
    check(udp(client, '1.1.1.1', 53).stdout.strip() == 'PIHOLE', 'Tor mode retains Pi-hole DNS path')
    check(http(client, v6url).returncode != 0, 'Tor mode blocks IPv6 bypass')
    check(http(client, 'http://192.0.2.2:8080').returncode != 0, 'Tor mode rejects private/reserved targets')
    check(http(outside, 'http://192.0.2.1:9040').returncode != 0, 'Upstream cannot access transparent proxy')
    fake_tor.terminate(); fake_tor.wait(timeout=3)
    check(http(client, 'http://8.8.8.8:8080').returncode != 0, 'Tor process failure has no direct fallback')
    apply(cfg, 'tor', map_uid=1001)
    check(udp(None, '8.8.8.8', 53).stdout.strip() == 'DNS_OVER_TOR', 'Pi-hole upstream DNS is redirected locally')
    check(http(os.getpid(), 'http://8.8.8.8:53').stdout == 'TCP_DNS_OVER_TOR', 'Pi-hole upstream TCP DNS is redirected locally')
    check(udp(None, '8.8.8.8', 5000).returncode != 0, 'Pi-hole cannot leak other upstream traffic')
    apply(cfg, 'tor', map_uid=1002)
    check(http(os.getpid(), 'http://127.0.0.1:9060').stdout == 'SOCKS_ONLY', 'DNS resolver can reach only local Tor')
    check(http(os.getpid(), 'http://8.8.8.8:8080').returncode != 0, 'DNS resolver direct Internet fallback is blocked')
    apply(cfg, 'blocked')
    check(http(client, 'http://8.8.8.8:8080').returncode != 0, 'Blocked state stops client Internet')
    check(udp(client, '1.1.1.1', 53).returncode != 0, 'Blocked state stops client DNS')
    apply(cfg, 'normal')
    check(http(client, 'http://8.8.8.8:8080').stdout == 'DIRECT', 'Explicit disable restores normal IPv4')
    print(json.dumps({'passed': len(passed), 'tests': passed,
                      'scope': 'Isolated kernel packet tests with fake Tor/DNS endpoints; no live Tor verification.'}))


if __name__ == '__main__':
    try:
        main()
    finally:
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()
            child.wait(timeout=5)
            errors = child.stderr.read()
            if errors:
                print(errors, file=sys.stderr)
