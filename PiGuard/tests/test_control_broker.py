import json
from pathlib import Path
import sys
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import control_broker


def test_broker_only_runs_fixed_actions(monkeypatch):
    runner=Mock(return_value=Mock(returncode=0,stdout=json.dumps({'mode':'normal'}),stderr=''))
    monkeypatch.setattr(control_broker.subprocess,'run',runner)
    monkeypatch.setattr(control_broker,'power_state',lambda: 'throttled=0x0')
    assert control_broker.run_action('enable; id')['error']=='unsupported_action'
    runner.assert_not_called()
    status=control_broker.run_action('status')
    assert status['mode']=='normal' and status['power_ok'] is True
    assert runner.call_args.args[0]==['/usr/local/bin/piguard-gateway','status']


def test_broker_reports_failure_without_success(monkeypatch):
    monkeypatch.setattr(control_broker,'power_ready',lambda: True)
    monkeypatch.setattr(control_broker.subprocess,'run',lambda *a,**kw: Mock(returncode=1,stdout='',stderr='{"error":"tor_unavailable","client_path":"unverified"}'))
    result=control_broker.run_action('enable')
    assert result['ok'] is False and result['client_path']=='unverified'


def test_tor_enable_is_refused_on_unstable_power(monkeypatch):
    runner=Mock()
    monkeypatch.setattr(control_broker,'power_ready',lambda: False)
    monkeypatch.setattr(control_broker.subprocess,'run',runner)
    result=control_broker.run_action('enable')
    assert result['error']=='power_unstable' and result['ok'] is False
    runner.assert_not_called()


def test_past_soft_temperature_event_alone_does_not_lock_tor_controls(monkeypatch):
    monkeypatch.setattr(control_broker, 'power_state', lambda: 'throttled=0x80000')
    assert control_broker.power_ready() is True
    assert control_broker.power_ready('throttled=0x80008') is False
    assert control_broker.power_ready('throttled=0x10000') is False
    assert control_broker.power_ready('Not available') is False
