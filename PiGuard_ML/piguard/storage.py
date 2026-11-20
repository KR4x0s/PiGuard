"""PiGuard-owned state; no mutation of Pi-hole's database."""
import json
import sqlite3
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS alerts(
 id INTEGER PRIMARY KEY, day TEXT NOT NULL, domain TEXT NOT NULL, label TEXT NOT NULL,
 model_id TEXT NOT NULL, score REAL NOT NULL, threshold REAL NOT NULL,
 first_seen REAL NOT NULL, last_seen REAL NOT NULL, scored_at REAL NOT NULL,
 query_count INTEGER NOT NULL DEFAULT 1, statuses TEXT NOT NULL,
 review_status TEXT NOT NULL DEFAULT 'new' CHECK(review_status IN ('new','benign','needs_investigation')),
 note TEXT NOT NULL DEFAULT '', reviewed_at REAL,
 feature_version TEXT, features TEXT,
 UNIQUE(day,domain,model_id));
CREATE INDEX IF NOT EXISTS alerts_seen ON alerts(last_seen);
CREATE TABLE IF NOT EXISTS daily(day TEXT NOT NULL, key TEXT NOT NULL, count INTEGER NOT NULL,
 PRIMARY KEY(day,key));
CREATE TABLE IF NOT EXISTS review_log(id INTEGER PRIMARY KEY, alert_id INTEGER NOT NULL,
 previous_status TEXT NOT NULL, new_status TEXT NOT NULL, note TEXT NOT NULL, changed_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE,
 password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('admin','viewer')),
 created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, kind TEXT NOT NULL,
 detail TEXT NOT NULL, actor TEXT NOT NULL, created_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS events_created ON events(created_at);
"""


def connect(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    db = sqlite3.connect(path, timeout=2)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript(SCHEMA)
    # Additive migration preserves earlier preview and deployed review records.
    columns = {row[1] for row in db.execute("PRAGMA table_info(alerts)")}
    for name in ("feature_version", "features"):
        if name not in columns:
            db.execute(f"ALTER TABLE alerts ADD COLUMN {name} TEXT")
    db.commit()
    return db


def get_meta(db, key, default=None):
    row = db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return json.loads(row[0]) if row else default


def set_meta(db, key, value):
    db.execute("INSERT INTO meta VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
               (key, json.dumps(value, allow_nan=False)))


def increment(db, day, key, count=1):
    db.execute("INSERT INTO daily VALUES(?,?,?) ON CONFLICT(day,key) DO UPDATE SET count=count+excluded.count",
               (day, key, count))


def add_alert(db, record, result, day, now):
    existing = db.execute("SELECT id,statuses FROM alerts WHERE day=? AND domain=? AND model_id=?",
                          (day, result["domain"], result["model_id"])).fetchone()
    statuses = json.loads(existing["statuses"]) if existing else {}
    key = str(record["status"])
    statuses[key] = statuses.get(key, 0) + 1
    db.execute("""INSERT INTO alerts(day,domain,label,model_id,score,threshold,first_seen,last_seen,
        scored_at,statuses,feature_version,features) VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(day,domain,model_id) DO UPDATE SET
        first_seen=min(first_seen,excluded.first_seen), last_seen=max(last_seen,excluded.last_seen),
        scored_at=excluded.scored_at, query_count=query_count+1, statuses=excluded.statuses""",
        (day, result["domain"], result["label"], result["model_id"], result["dga_score"], result["threshold"],
         record["timestamp"], record["timestamp"], now, json.dumps(statuses),
         result.get("feature_version"), json.dumps(result.get("features")) if result.get("features") else None))


def prune(db, now=None):
    now = time.time() if now is None else now
    db.execute("DELETE FROM review_log WHERE alert_id IN (SELECT id FROM alerts WHERE last_seen < ?)",
               (now - 14*86400,))
    db.execute("DELETE FROM alerts WHERE last_seen < ?", (now - 14*86400,))
    db.execute("DELETE FROM daily WHERE day < date(?, 'unixepoch', '-90 days')", (now,))
    db.execute("DELETE FROM events WHERE created_at < ?", (now - 90*86400,))
