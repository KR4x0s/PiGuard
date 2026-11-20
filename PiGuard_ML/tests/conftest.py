import time
import sqlite3
from pathlib import Path
import pytest

@pytest.fixture
def source(tmp_path):
    path = tmp_path/'source.db'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE queries(id INTEGER PRIMARY KEY, timestamp REAL, domain TEXT, type INTEGER, status INTEGER)')
    return path


def put_query(path, identifier=1, domain='x123.com', status=2, timestamp=None):
    with sqlite3.connect(path) as db:
        db.execute('INSERT INTO queries VALUES(?,?,?,?,?)',
                   (identifier, time.time() if timestamp is None else timestamp, domain, 1, status))


class FixtureScorer:
    contract = {'model_id': 'fixture-model'}
    def score(self, domains):
        from piguard_dga_features import project_domain, InputError
        result = []
        for value in domains:
            try:
                domain, label = project_domain(value)
                result.append({'status': 'scored', 'domain': domain, 'label': label,
                    'model_id': 'fixture-model', 'dga_score': .95, 'threshold': .8, 'suspicious': True})
            except InputError as exc:
                result.append({'status': 'skipped', 'reason': str(exc)})
        return result

@pytest.fixture
def scorer():
    return FixtureScorer()
