import json
import sqlite3
import time
import pytest
from piguard.observer import Observer, source_open
from piguard.storage import get_meta, prune
from conftest import put_query


def test_tail_then_restart_exactly_once(source,tmp_path,scorer):
    put_query(source,1)
    state=tmp_path/'state.db'
    ob=Observer(source,state,scorer)
    assert ob.tick()==0
    put_query(source,2)
    put_query(source,3,'a.x123.com',3)
    assert ob.tick()==2
    assert ob.tick()==0
    ob.db.close()
    ob=Observer(source,state,scorer)
    assert ob.tick()==0
    row=ob.db.execute('SELECT * FROM alerts').fetchone()
    assert row['query_count']==2
    assert json.loads(row['statuses'])=={'2':1,'3':1}
    assert get_meta(ob.db,'health')['last_read_at']


def test_replay_skips_local_and_bad_timestamp(source,tmp_path,scorer):
    put_query(source,1,'printer.local')
    put_query(source,2,'example.com',timestamp=-1)
    put_query(source,3,'example.com')
    ob=Observer(source,tmp_path/'state.db',scorer,replay=True)
    assert ob.tick()==3
    assert ob.db.execute('SELECT count(*) FROM alerts').fetchone()[0]==1
    assert get_meta(ob.db,'checkpoint')['id']==3
    assert ob.db.execute("SELECT count FROM daily WHERE key='skipped:special_use_name'").fetchone()[0]==1
    assert ob.db.execute("SELECT count FROM daily WHERE key='invalid_timestamp'").fetchone()[0]==1


def test_source_is_readonly(source):
    db=source_open(source)
    with pytest.raises(sqlite3.OperationalError):
        db.execute('DELETE FROM queries')
    db.close()


def test_model_failure_does_not_advance(source,tmp_path,scorer,monkeypatch):
    ob=Observer(source,tmp_path/'state.db',scorer)
    ob.tick()
    put_query(source,1)
    real=scorer.score
    monkeypatch.setattr(scorer,'score',lambda _: (_ for _ in ()).throw(RuntimeError('private-domain.example')))
    with pytest.raises(RuntimeError):
        ob.tick()
    assert get_meta(ob.db,'checkpoint')['id']==0
    assert get_meta(ob.db,'health')['error']=='model:RuntimeError'
    monkeypatch.setattr(scorer,'score',real)
    assert ob.tick()==1


def test_transaction_failure_rolls_back_alerts_and_checkpoint(source,tmp_path,scorer,monkeypatch):
    import piguard.observer as module
    ob=Observer(source,tmp_path/'state.db',scorer)
    ob.tick()
    put_query(source,1)
    real=module.set_meta
    def fail(db,key,value):
        if key=='checkpoint':
            raise sqlite3.OperationalError('full')
        return real(db,key,value)
    monkeypatch.setattr(module,'set_meta',fail)
    with pytest.raises(sqlite3.OperationalError):
        ob.tick()
    assert ob.db.execute('SELECT count(*) FROM alerts').fetchone()[0]==0
    assert get_meta(ob.db,'checkpoint')['id']==0
    monkeypatch.setattr(module,'set_meta',real)
    ob.tick()
    assert ob.db.execute('SELECT query_count FROM alerts').fetchone()[0]==1


def test_reset_and_anchor_change_are_visible(source,tmp_path,scorer):
    put_query(source,1)
    ob=Observer(source,tmp_path/'state.db',scorer,replay=True)
    ob.tick()
    generation=get_meta(ob.db,'checkpoint')['generation']
    with sqlite3.connect(source) as db:
        db.execute("UPDATE queries SET domain='changed.com' WHERE id=1")
    assert ob.tick()==0
    assert get_meta(ob.db,'checkpoint')['generation'] != generation
    assert get_meta(ob.db,'health')['gap_count']==1
    with sqlite3.connect(source) as db:
        db.execute('DELETE FROM queries')
    ob.tick()
    assert get_meta(ob.db,'health')['gap_count']==2
    put_query(source,1)
    assert ob.tick()==1


def test_bounded_batch_and_backlog(source,tmp_path,scorer):
    with sqlite3.connect(source) as db:
        db.executemany('INSERT INTO queries VALUES(?,?,?,?,?)',[(i,time.time(),'example.com',1,2) for i in range(1,602)])
    ob=Observer(source,tmp_path/'state.db',scorer,replay=True)
    assert ob.tick()==500
    assert get_meta(ob.db,'health')['backlog']==101
    assert ob.tick()==101
    assert ob.db.execute('SELECT query_count FROM alerts').fetchone()[0]==601


def test_prune_preserves_checkpoint_and_recent_data(source,tmp_path,scorer):
    now=time.time()
    put_query(source,1,timestamp=now-15*86400)
    put_query(source,2,timestamp=now)
    ob=Observer(source,tmp_path/'state.db',scorer,replay=True)
    ob.tick(now)
    assert ob.db.execute('SELECT count(*) FROM alerts').fetchone()[0]==1
    assert get_meta(ob.db,'checkpoint')['id']==2
    assert ob.db.execute('SELECT count(*) FROM daily').fetchone()[0]>0


def test_schema_failure_and_idle_health(source,tmp_path,scorer):
    ob=Observer(source,tmp_path/'state.db',scorer)
    ob.tick()
    ob.tick()
    assert get_meta(ob.db,'health')['error'] is None
    with sqlite3.connect(source) as db:
        db.execute('DROP TABLE queries')
    with pytest.raises(ValueError,match='unsupported'):
        ob.tick()
    assert get_meta(ob.db,'health')['error']=='source:ValueError'


def test_concurrent_observer_cannot_double_count(source,tmp_path,scorer,monkeypatch):
    state=tmp_path/'state.db'
    first=Observer(source,state,scorer)
    first.tick()
    put_query(source,1)
    from conftest import FixtureScorer
    second=Observer(source,state,FixtureScorer())
    original=scorer.score
    def race(domains):
        second.tick()
        return original(domains)
    monkeypatch.setattr(scorer,'score',race)
    with pytest.raises(RuntimeError,match='checkpoint_changed'):
        first.tick()
    assert first.db.execute('SELECT query_count FROM alerts').fetchone()[0]==1
    assert get_meta(first.db,'checkpoint')['id']==1
