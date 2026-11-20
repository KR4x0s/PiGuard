"""Short, read-only Pi-hole transactions with atomic results/checkpoint commits."""
from __future__ import annotations
import argparse
import hashlib
import json
import logging
import os
import socket
import sqlite3
import struct
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from piguard.model import Scorer
from piguard.storage import connect, get_meta, set_meta, increment, add_alert, prune

LOG = logging.getLogger("piguard")


def source_open(path):
    uri = Path(path).resolve().as_uri() + "?mode=ro"
    db = sqlite3.connect(uri, uri=True, timeout=.25)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA query_only=ON")
    columns = {row[1] for row in db.execute("PRAGMA table_info(queries)")}
    if not {"id", "timestamp", "domain", "type", "status"}.issubset(columns):
        db.close()
        raise ValueError("unsupported_source_schema")
    return db


def anchor(row):
    if row is None:
        return None
    content = [row["id"], row["timestamp"], row["domain"], row["type"]]
    return hashlib.sha256(json.dumps(content).encode()).hexdigest()


def dns_probe(server="127.0.0.1", port=53):
    query_id = int.from_bytes(os.urandom(2), "big")
    wire = struct.pack("!HHHHHH", query_id, 0x100, 1, 0, 0, 0) + b"\x07example\x03com\x00\x00\x01\x00\x01"
    start = time.perf_counter()
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(1)
            sock.connect((server, port))
            sock.send(wire)
            data = sock.recv(4096)
        ident, flags = struct.unpack("!HH", data[:4])
        ok = ident == query_id and bool(flags & 0x8000) and flags & 15 == 0
        return {"status": "reachable" if ok else "dns_error", "checked_at": time.time(),
                "latency_ms": (time.perf_counter()-start)*1000}
    except (OSError, struct.error):
        return {"status": "unavailable", "checked_at": time.time()}


class Observer:
    def __init__(self, source, state, scorer, replay=False):
        self.source, self.state, self.scorer = Path(source), Path(state), scorer
        self.replay = replay
        self.db = connect(state)

    def tick(self, now=None):
        now = time.time() if now is None else now
        last = get_meta(self.db, "health", {})
        health = {**last, "heartbeat": now, "model_ready": True,
                  "model_stage": getattr(self.scorer, "stage", "candidate"),
                  "model_id": self.scorer.contract["model_id"], "error": None}
        phase = "source"
        try:
            # Materialize a bounded batch and close the source before scoring or writing state.
            src = source_open(self.source)
            try:
                identity = f"{self.source.stat().st_dev}:{self.source.stat().st_ino}"
                cp = get_meta(self.db, "checkpoint")
                maximum = int(src.execute("SELECT coalesce(max(id),0) FROM queries").fetchone()[0])
                reset = cp is not None and (cp["identity"] != identity or cp["id"] > maximum)
                if cp and cp["id"] and not reset:
                    reset = anchor(src.execute("SELECT id,timestamp,domain,type FROM queries WHERE id=?",
                                               (cp["id"],)).fetchone()) != cp["anchor"]
                if cp is None or reset:
                    initial = 0 if cp is None and self.replay else maximum
                    row = src.execute("SELECT id,timestamp,domain,type FROM queries WHERE id=?", (initial,)).fetchone()
                    cp = {"generation": str(uuid.uuid4()), "identity": identity, "id": initial, "anchor": anchor(row)}
                    if reset:
                        health["gap_count"] = health.get("gap_count", 0) + 1
                        health["last_gap_at"] = now
                    with self.db:
                        set_meta(self.db, "checkpoint", cp)
                rows = [dict(row) for row in src.execute(
                    "SELECT id,timestamp,domain,type,status FROM queries WHERE id>? ORDER BY id LIMIT 500", (cp["id"],))]
                backlog = int(src.execute("SELECT count(*) FROM queries WHERE id>?", (cp["id"],)).fetchone()[0])
            finally:
                src.close()
            health.update(last_read_at=now, backlog=max(0, backlog-len(rows)))
            phase = "model"
            score_start = time.perf_counter()
            results = self.scorer.score([row["domain"] for row in rows])
            health["last_batch_ms"] = (time.perf_counter() - score_start) * 1000
            phase = "store"
            with self.db:
                self.db.execute("BEGIN IMMEDIATE")
                if get_meta(self.db, "checkpoint") != cp:
                    raise RuntimeError("checkpoint_changed_by_another_observer")
                for row, result in zip(rows, results):
                    # Invalid timestamps cannot be allowed to poison a whole batch indefinitely.
                    try:
                        timestamp = float(row["timestamp"])
                        if not 0 <= timestamp <= now + 300:
                            raise ValueError("bad_timestamp")
                        day = datetime.fromtimestamp(timestamp, timezone.utc).strftime("%Y-%m-%d")
                    except (ValueError, TypeError, OverflowError, OSError):
                        increment(self.db, datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m-%d"), "invalid_timestamp")
                        continue
                    increment(self.db, day, "queries_observed")
                    if row["status"] in {1, 4, 5, 6, 7, 8, 9, 10, 11, 15, 16, 18}:
                        increment(self.db, day, "pihole_blocked")
                    if result["status"] == "skipped":
                        increment(self.db, day, "skipped:" + result["reason"])
                    else:
                        increment(self.db, day, "scored")
                        if result["suspicious"]:
                            increment(self.db, day, "flagged_queries")
                            add_alert(self.db, row, result, day, now)
                if rows:
                    cp.update(id=rows[-1]["id"], anchor=anchor(rows[-1]))
                    health.update(last_advanced_at=now, last_query_at=rows[-1]["timestamp"])
                set_meta(self.db, "checkpoint", cp)
                health["checkpoint"] = cp["id"]
                set_meta(self.db, "health", health)
                if now - get_meta(self.db, "last_prune", 0) >= 3600:
                    prune(self.db, now)
                    set_meta(self.db, "last_prune", now)
            return len(rows)
        except Exception as exc:
            # Do not log SQLite messages or source values, which may contain private query data.
            health.update(error=f"{phase}:{type(exc).__name__}", error_at=now,
                          error_count=health.get("error_count", 0) + 1)
            try:
                with self.db:
                    set_meta(self.db, "health", health)
            except sqlite3.Error:
                LOG.error("State store unavailable")
            LOG.error("Observer failure in %s (%s)", phase, type(exc).__name__)
            raise


def load_config(path):
    config_path = Path(path).resolve()
    config = json.loads(config_path.read_text())
    for key in ("source_db", "state_db", "release"):
        value = Path(config[key])
        config[key] = str(value if value.is_absolute() else config_path.parent / value)
    return config


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", required=True)
    p.add_argument("--once", action="store_true")
    p.add_argument("--replay", action="store_true", help="Replay from zero only into a new state database")
    args = p.parse_args()
    os.umask(0o077)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = load_config(args.config)
    if args.replay and Path(cfg["state_db"]).exists():
        p.error("Replay requires a separate, new state database")
    try:
        scorer = Scorer(Path(cfg["release"]), cfg["manifest_sha256"])
    except Exception as exc:
        with connect(cfg["state_db"]) as db:
            set_meta(db, "health", {"heartbeat": time.time(), "model_ready": False,
                                    "error": f"model_startup:{type(exc).__name__}"})
        raise SystemExit("Model readiness verification failed; inspect the release and dependency contract") from None
    observer = Observer(cfg["source_db"], cfg["state_db"], scorer, args.replay)
    failures = 0
    last_probe = 0
    while True:
        try:
            start = time.monotonic()
            processed = observer.tick()
            while processed == 500 and time.monotonic() - start < 2:
                processed = observer.tick()
            if time.time()-last_probe >= 60:
                probe = dns_probe(cfg.get("dns_server", "127.0.0.1"))
                with observer.db:
                    set_meta(observer.db, "dns", probe)
                last_probe = time.time()
            failures = 0
        except Exception:
            failures += 1
            if args.once:
                raise SystemExit(1)
        if args.once:
            break
        time.sleep(min(60, 15 * 2**min(failures, 2)))


if __name__ == "__main__":
    main()
