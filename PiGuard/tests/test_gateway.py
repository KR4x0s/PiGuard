import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import gateway
import tor_mode


@pytest.fixture
def cfg():
    return gateway.load_config(Path(__file__).resolve().parents[1] / 'tor/travel.example.json')


def test_home_hotspot_policy_uses_wifi_only_for_clients():
    home = gateway.load_config(Path(__file__).resolve().parents[1] / 'tor/home.example.json')
    assert (home['uplink'], home['downlink']) == ('eth0', 'wlan0')
    policy = gateway.rules(home, 'tor', 1001, 1002)
    assert 'iifname "eth0" meta l4proto { tcp, udp } th dport 53 counter drop' in policy
    assert 'iifname "eth0" udp sport 68 udp dport 67 counter drop' in policy
    assert 'meta skuid 1001 oifname "eth0" udp sport 67 udp dport 68 counter drop' in policy
    assert 'iifname "eth0" tcp dport { 80, 443, 8080, 8090 } counter drop' in policy
    assert 'meta skuid 1001 oifname "wlan0" udp sport 67 udp dport 68 accept' in policy
    assert 'iifname "wlan0" meta nfproto ipv6 counter drop' in policy
    assert 'iifname "wlan0" meta nfproto ipv4 tcp flags & (fin | syn | rst | ack) == syn redirect to :9040' in policy
    assert 'iifname "eth0" meta nfproto ipv4 tcp flags & (fin | syn | rst | ack) == syn redirect to :9040' not in policy


@pytest.mark.parametrize('change', [
    {'uplink': 'eth0'}, {'downlink': 'lo'}, {'downlink': 'eth0";flush ruleset;'},
    {'gateway': '8.8.8.8/24'}, {'gateway': '10.0.0.0/24'}, {'gateway': '10.0.0.255/24'},
    {'gateway': '10.0.0.1/32'}, {'gateway': '::1/64'}, {'profile': 'unknown'}, {'extra': 'value'},
    {'profile': []}, {'gateway': True},
])
def test_reject_unsafe_config(cfg, change, tmp_path):
    path = tmp_path / 'config.json'
    path.write_text(json.dumps(cfg | change))
    with pytest.raises(ValueError):
        gateway.load_config(path)


def test_no_fallback_on_failed_tor_verification(cfg, monkeypatch):
    events = []
    monkeypatch.setattr(gateway, 'save_mode', lambda m: events.append(('save', m)))
    monkeypatch.setattr(gateway, 'apply_rules', lambda c, m: events.append(('rules', m)))
    monkeypatch.setattr(gateway, 'preflight', lambda c: None)
    monkeypatch.setattr(gateway, 'command', lambda a, **kw: events.append(('command', a)))
    monkeypatch.setattr(gateway, 'check_connection', Mock(side_effect=RuntimeError('offline')))
    monkeypatch.setattr(gateway.time, 'sleep', lambda _: None)
    with pytest.raises(RuntimeError, match='offline'):
        gateway.transition(cfg, 'tor')
    assert events[:2] == [('save', 'blocked'), ('rules', 'blocked')]
    assert not any(x in events for x in [('save', 'normal'), ('rules', 'normal'), ('rules', 'tor')])


def test_cold_tor_bootstrap_retries_while_blocked(cfg, monkeypatch):
    modes = []
    monkeypatch.setattr(gateway, 'save_mode', lambda mode: modes.append(mode))
    monkeypatch.setattr(gateway, 'apply_rules', lambda c, mode: modes.append(mode))
    monkeypatch.setattr(gateway, 'preflight', lambda c: None)
    monkeypatch.setattr(gateway, 'command', lambda *a, **kw: None)
    monkeypatch.setattr(gateway, 'verify_dns', lambda: None)
    check = Mock(side_effect=[RuntimeError('bootstrapping'), {'tor_path':'verified_for_this_request'}])
    monkeypatch.setattr(gateway, 'check_connection', check)
    monkeypatch.setattr(gateway.time, 'sleep', lambda _: None)
    assert gateway.transition(cfg, 'tor')['mode'] == 'tor'
    assert check.call_count == 2
    assert modes == ['blocked', 'blocked', 'tor', 'tor']


def test_boot_resume_waits_for_pihole_process(tmp_path, monkeypatch):
    (tmp_path / '321').mkdir()
    (tmp_path / '321' / 'status').write_text('Name:\tpihole-FTL\n')
    replies = iter(['0', '321'])
    monkeypatch.setattr(gateway, 'command', lambda *a, **kw: Mock(stdout=next(replies)))
    sleeps = []
    monkeypatch.setattr(gateway.time, 'sleep', sleeps.append)
    gateway.wait_for_pihole(timeout=2, proc_root=tmp_path)
    assert sleeps == [1]


def test_boot_resume_keeps_mode_when_pihole_never_starts(tmp_path, monkeypatch):
    monkeypatch.setattr(gateway, 'command', lambda *a, **kw: Mock(stdout='0'))
    monkeypatch.setattr(gateway.time, 'sleep', lambda *_: None)
    with pytest.raises(RuntimeError, match='guard remains loaded'):
        gateway.wait_for_pihole(timeout=2, proc_root=tmp_path)


def test_tor_dns_check_waits_for_first_usable_answer(monkeypatch):
    replies = iter([Mock(returncode=9, stdout=''), Mock(returncode=0, stdout='104.20.23.154\n')])
    monkeypatch.setattr(gateway, 'command', lambda *a, **kw: next(replies))
    sleeps = []
    monkeypatch.setattr(gateway.time, 'sleep', sleeps.append)
    gateway.verify_dns(attempts=2)
    assert sleeps == [5]


def test_tor_dns_check_fails_closed_after_retries(monkeypatch):
    monkeypatch.setattr(gateway, 'command', lambda *a, **kw: Mock(returncode=9, stdout=''))
    monkeypatch.setattr(gateway.time, 'sleep', lambda *_: None)
    with pytest.raises(RuntimeError, match='Gateway remains blocked'):
        gateway.verify_dns(attempts=2)


def test_success_requires_both_tor_and_pihole(cfg, monkeypatch):
    events = []
    monkeypatch.setattr(gateway, 'save_mode', lambda m: events.append(('save', m)))
    monkeypatch.setattr(gateway, 'apply_rules', lambda c, m: events.append(('rules', m)))
    monkeypatch.setattr(gateway, 'preflight', lambda c: None)
    monkeypatch.setattr(gateway, 'command', lambda a, **kw: events.append(('command', a)))
    monkeypatch.setattr(gateway, 'check_connection', lambda: events.append(('check', 'tor')))
    monkeypatch.setattr(gateway, 'verify_dns', lambda: events.append(('check', 'dns')))
    assert gateway.transition(cfg, 'tor')['mode'] == 'tor'
    assert ('command', [gateway.PIHOLE, 'reloaddns']) in events
    assert events.index(('command', [gateway.PIHOLE, 'reloaddns'])) < events.index(('check', 'dns'))
    assert events.index(('check', 'dns')) < events.index(('rules', 'tor'))
    assert events[-1] == ('save', 'tor')
    events.clear()
    gateway.transition(cfg, 'normal')
    assert events[:2] == [('save', 'blocked'), ('rules', 'blocked')]
    assert events[-2:] == [('rules', 'normal'), ('save', 'normal')]


def test_state_write_failure_reblocks(cfg, monkeypatch):
    modes = []
    def save(mode):
        if mode == 'normal':
            raise OSError('disk full')
    monkeypatch.setattr(gateway, 'save_mode', save)
    monkeypatch.setattr(gateway, 'apply_rules', lambda c, m: modes.append(m))
    monkeypatch.setattr(gateway, 'command', Mock())
    with pytest.raises(OSError):
        gateway.transition(cfg, 'normal')
    assert modes == ['blocked', 'normal', 'blocked']


def test_state_missing_or_corrupt_is_blocked(tmp_path, monkeypatch):
    path = tmp_path / 'mode'
    monkeypatch.setattr(gateway, 'MODE', path)
    assert gateway.read_mode() == 'blocked'
    path.write_text('garbage')
    assert gateway.read_mode() == 'blocked'
    gateway.save_mode('tor')
    assert gateway.read_mode() == 'tor'
    assert path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize('payload', ['{"IsTor":false}', '{"IsTor":"true"}', '[]', 'not json', '{}'])
def test_tor_verification_requires_boolean_true(monkeypatch, payload):
    monkeypatch.setattr(tor_mode, 'run', lambda *a, **kw: subprocess.CompletedProcess([], 0, payload, ''))
    with pytest.raises(RuntimeError):
        tor_mode.check_connection()


def test_curl_never_falls_back_or_uses_local_dns(monkeypatch):
    calls = []
    def run(args, **kw):
        calls.append(args)
        return subprocess.CompletedProcess(args, 7, '', 'connection refused')
    monkeypatch.setattr(tor_mode, 'run', run)
    with pytest.raises(RuntimeError, match='no direct connection'):
        tor_mode.check_connection()
    assert len(calls) == 1
    args = calls[0]
    assert args[1] == '--disable'
    assert args[args.index('--proxy') + 1] == 'socks5h://127.0.0.1:9060'
    assert args[args.index('--noproxy') + 1] == ''


def test_bad_live_config_override_is_rejected(tmp_path):
    assert gateway.main(['enable', '--config', str(tmp_path / 'evil')]) == 1


def test_firewall_transaction_only_replaces_own_table(cfg, monkeypatch):
    calls = []
    monkeypatch.setattr(gateway.pwd, 'getpwnam', lambda name: Mock(pw_uid=1001 if name == 'pihole' else 1002))
    def command(args, **kwargs):
        calls.append((args, kwargs.get('data')))
        return subprocess.CompletedProcess(args, 0, '', '')
    monkeypatch.setattr(gateway, 'command', command)
    gateway.apply_rules(cfg, 'tor')
    assert calls[-2][0] == [gateway.NFT, '--check', '--file', '-']
    assert calls[-1][1] == calls[-2][1]
    assert calls[-1][1].startswith('delete table inet piguard_gateway\n')
    assert 'flush ruleset' not in calls[-1][1]


@pytest.mark.parametrize('mode', ['tor', 'blocked'])
def test_dhcp_replies_survive_restricted_pihole_egress(cfg, mode):
    policy = gateway.rules(cfg, mode, 1001, 1002)
    allow = 'meta skuid 1001 oifname "eth0" udp sport 67 udp dport 68 accept'
    drop = 'meta skuid 1001 counter drop'
    assert policy.index(allow) < policy.index(drop)
    assert 'oifname "wlan0" udp sport 67 udp dport 68 accept' not in policy
