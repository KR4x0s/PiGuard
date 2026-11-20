#!/usr/bin/env python3
"""Create a clearly synthetic, local-only dashboard preview using a real candidate model."""
import json
import random
import string
import sqlite3
import sys
import time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from piguard.model import Scorer
from piguard.observer import Observer
from piguard.storage import set_meta

root=Path(__file__).resolve().parents[1]
run=root/'runs/2026-10-25-baseline'
preview=root/'state/preview'
preview.mkdir(parents=True,exist_ok=True)
release=run/'candidates/compact_random_forest'
digest=(release/'MANIFEST.sha256').read_text().strip()
source=preview/'source.db'
if source.exists():
    raise SystemExit('Preview exists; leave existing records intact')
scorer=Scorer(release,digest)
rng=random.Random(42)
generated=[''.join(rng.choices(string.ascii_lowercase+string.digits,k=24))+'.com' for _ in range(200)]
flagged=[r['domain'] for r in scorer.score(generated) if r.get('suspicious')][:3]
with sqlite3.connect(source) as db:
    db.execute('CREATE TABLE queries(id INTEGER PRIMARY KEY,timestamp REAL,domain TEXT,type INTEGER,status INTEGER)')
    names=flagged+['example.com','printer.local']
    db.executemany('INSERT INTO queries VALUES(?,?,?,?,?)',[(i,time.time()-i*10,n,1,2) for i,n in enumerate(names*4,1)])
observer=Observer(source,preview/'state.db',scorer,replay=True)
observer.tick()
with observer.db:
    health={'heartbeat':time.time(),'model_ready':True,'model_id':scorer.contract['model_id'],
            'last_read_at':time.time(),'checkpoint':20,'backlog':0,'error':'SYNTHETIC_PREVIEW: not live Pi-hole traffic'}
    set_meta(observer.db,'health',health)
config={'source_db':str(source),'state_db':str(preview/'state.db'),'release':str(release),'manifest_sha256':digest}
(preview/'config.json').write_text(json.dumps(config,indent=2))
print(preview/'config.json')
