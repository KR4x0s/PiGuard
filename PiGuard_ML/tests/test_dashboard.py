import time
import pytest
from piguard.dashboard import create_app, csv_safe
from piguard.accounts import set_user
from piguard.observer import Observer
from piguard.storage import connect,set_meta
from conftest import put_query

@pytest.fixture
def client(source,tmp_path,scorer):
    state=tmp_path/'state.db'
    put_query(source,1,'example.com')
    Observer(source,state,scorer,replay=True).tick()
    with connect(state) as db:
        set_user(db,'operator','very-long-test-password','admin')
        set_user(db,'spectator','very-long-viewer-password','viewer')
    app=create_app(state,'test-secret',
                   gateway_call=lambda action: {'ok':True,'mode':'normal','profile':'travel','guard_present':True,
                                                'power':'throttled=0x0','power_ok':True},
                   network_probe=lambda: {'uplink':[],'downstream':[],'downstream_ready':False,'route_ok':False,
                                          'pihole_active':True,'tailscale_active':False,'power':'Not available',
                                          'power_ok':False,'mac':'Unavailable'})
    app.config['TESTING']=True
    client=app.test_client()
    client.get('/login')
    with client.session_transaction() as session:
        csrf=session['csrf']
    assert client.post('/login',data={'csrf':csrf,'username':'operator','password':'very-long-test-password'}).status_code==303
    return client


def test_home_filter_detail_export(client):
    assert b'example.com' in client.get('/').data
    assert b'No matching alerts' in client.get('/alerts?domain=missing').data
    assert client.get('/alerts?status=wrong').status_code==400
    assert client.get('/alerts?page=oops').status_code==400
    assert client.get('/alerts/999').status_code==404
    assert b'Decision evidence' in client.get('/alerts/1').data
    assert b'example.com' in client.get('/export.csv').data
    assert client.get('/healthz').status_code==200
    assert b'10.78.0.1' in client.get('/setup').data
    assert b'Stable' in client.get('/setup').data


def test_review_csrf_escape_and_persistence(client):
    client.get('/')
    assert client.post('/alerts/1',data={'review_status':'benign'}).status_code==403
    with client.session_transaction() as session:
        csrf=session['csrf']
    assert client.post('/alerts/1',data={'csrf':csrf,'review_status':'wrong'}).status_code==400
    response=client.post('/alerts/1',data={'csrf':csrf,'review_status':'benign','note':'<script>alert(1)</script>'})
    assert response.status_code==303
    detail=client.get('/alerts/1').data
    assert b'&lt;script&gt;' in detail and b'<script>' not in detail
    assert b'example.com' in client.get('/alerts?status=benign').data
    assert b'No matching alerts' in client.get('/alerts?status=new').data


def test_stale_health_and_host_guard(tmp_path):
    app=create_app(tmp_path/'state.db','secret')
    client=app.test_client()
    assert client.get('/healthz').status_code==503
    assert client.get('/').status_code==302
    assert client.get('/authz/admin').status_code==401
    with connect(tmp_path/'state.db') as db:
        set_user(db,'operator','very-long-test-password','admin')
    client.get('/login')
    with client.session_transaction() as session:
        csrf=session['csrf']
    client.post('/login',data={'csrf':csrf,'username':'operator','password':'very-long-test-password'})
    assert b'observation needs attention' in client.get('/').data
    assert client.get('/',headers={'Host':'attacker.example'}).status_code==400
    assert 'frame-ancestors' in client.get('/').headers['Content-Security-Policy']

@pytest.mark.parametrize('value',['=SUM(1,2)','+cmd','-cmd','@cmd','  =SUM(1,2)','\t=cmd'])
def test_csv_escape(value):
    assert csv_safe(value).startswith("'")


def test_viewer_cannot_review_or_control(client):
    client.get('/')
    with client.session_transaction() as session:
        csrf=session['csrf']
    client.post('/logout',data={'csrf':csrf})
    client.get('/login')
    with client.session_transaction() as session:
        csrf=session['csrf']
    assert client.post('/login',data={'csrf':csrf,'username':'spectator','password':'very-long-viewer-password'}).status_code==303
    assert b'example.com' in client.get('/alerts').data
    assert client.get('/authz/admin').status_code==403
    with client.session_transaction() as session:
        csrf=session['csrf']
    assert client.post('/alerts/1',data={'csrf':csrf,'review_status':'benign'}).status_code==403
    assert client.post('/gateway/enable',data={'csrf':csrf}).status_code==403


def test_gateway_action_audit_and_csrf(client):
    assert client.post('/gateway/enable').status_code==403
    assert b'Enable Tor' in client.get('/gateway').data
    assert b'Pi hardware reports Not available' not in client.get('/gateway').data
    with client.session_transaction() as session:
        csrf=session['csrf']
    assert client.post('/gateway/enable',data={'csrf':csrf}).status_code==200
    assert b'Client path: ' in client.get('/gateway').data or b'Unverified' in client.get('/gateway').data


def test_historical_temperature_is_advisory_after_cooling(tmp_path):
    state=tmp_path/'state.db'
    with connect(state) as db:
        set_user(db,'operator','very-long-test-password','admin')
    app=create_app(state,'test-secret',
                   gateway_call=lambda action: {'mode':'normal','guard_present':True,
                                                'power':'throttled=0x80000','power_ok':True},
                   network_probe=lambda: {'power':'Not available','power_ok':False})
    app.config['TESTING']=True
    client=app.test_client()
    client.get('/login')
    with client.session_transaction() as session:
        csrf=session['csrf']
    assert client.post('/login',data={'csrf':csrf,'username':'operator',
                                     'password':'very-long-test-password'}).status_code==303
    page=client.get('/gateway').data
    assert b'soft temperature limit' in page
    assert b'undervoltage' not in page
    assert b'limit is no longer active' in page
    assert b'<button disabled>Enable Tor</button>' not in page


def test_failed_gateway_action_is_not_shown_as_success(source,tmp_path,scorer):
    state=tmp_path/'state.db'
    with connect(state) as db:
        set_user(db,'operator','very-long-test-password','admin')
    def gateway(action):
        return {'mode':'blocked','ok':False,'error':'tor_unavailable','client_path':'unverified'}
    app=create_app(state,'test-secret',gateway_call=gateway)
    client=app.test_client()
    client.get('/login')
    with client.session_transaction() as session:
        csrf=session['csrf']
    client.post('/login',data={'csrf':csrf,'username':'operator','password':'very-long-test-password'})
    with client.session_transaction() as session:
        csrf=session['csrf']
    response=client.post('/gateway/enable',data={'csrf':csrf})
    assert response.status_code==503
    assert b'Action failed' in response.data and b'Blocked' in response.data


def test_blocked_query_count_from_source(source,tmp_path,scorer):
    from conftest import put_query
    put_query(source,1,'example.com',status=1)
    put_query(source,2,'example.net',status=2)
    state=tmp_path/'state.db'
    Observer(source,state,scorer,replay=True).tick()
    with connect(state) as db:
        assert db.execute("SELECT count FROM daily WHERE key='pihole_blocked'").fetchone()[0]==1
