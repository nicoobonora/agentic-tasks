"""SQLite storage. One transaction per command, raw evidence never overwritten."""
import json
import os
import sqlite3
import time
from pathlib import Path
from contextlib import contextmanager

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS source_pages (
 id TEXT PRIMARY KEY, url TEXT NOT NULL, acquired_at TEXT NOT NULL,
 sha256 TEXT NOT NULL, path TEXT NOT NULL, row_count INTEGER NOT NULL, kind TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sites (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, source TEXT NOT NULL, payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS plugs (
 id TEXT PRIMARY KEY, site_id TEXT NOT NULL REFERENCES sites(id), source TEXT NOT NULL,
 payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS observations (
 id TEXT PRIMARY KEY, plug_id TEXT NOT NULL REFERENCES plugs(id), observed_at TEXT NOT NULL,
 transaction_at TEXT NOT NULL, status TEXT NOT NULL, source_page_id TEXT NOT NULL REFERENCES source_pages(id)
);
CREATE INDEX IF NOT EXISTS obs_time ON observations(plug_id, observed_at, transaction_at);
CREATE TABLE IF NOT EXISTS observation_pages (
 observation_id TEXT NOT NULL REFERENCES observations(id), page_id TEXT NOT NULL REFERENCES source_pages(id),
 PRIMARY KEY(observation_id,page_id)
);
CREATE TABLE IF NOT EXISTS transitions (
 id TEXT PRIMARY KEY, plug_id TEXT NOT NULL, observed_at TEXT NOT NULL,
 previous_status TEXT, status TEXT NOT NULL, observation_id TEXT NOT NULL, gap_before INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS heartbeats (
 observation_id TEXT PRIMARY KEY, plug_id TEXT NOT NULL, observed_at TEXT NOT NULL, repeated INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS episodes (
 id TEXT PRIMARY KEY, plug_id TEXT NOT NULL, start TEXT NOT NULL, end TEXT NOT NULL,
 duration_seconds REAL NOT NULL, left_censored INTEGER NOT NULL, right_censored INTEGER NOT NULL,
 short INTEGER NOT NULL, prolonged INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS documents (
 kind TEXT NOT NULL, id TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(kind,id)
);
CREATE TABLE IF NOT EXISTS discussion_leases (
 run_id TEXT PRIMARY KEY, token TEXT NOT NULL, expires_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
 sequence INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, payload TEXT NOT NULL
);
"""

def connect(path=None):
    path = Path(path or os.getenv("ACS_DB", ROOT / "data/acs.sqlite"))
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=30)
    db.row_factory = sqlite3.Row
    try:
        db.execute("PRAGMA foreign_keys=ON")
        deadline = time.monotonic() + 30
        while True:
            try:
                # Concurrent first connections can collide while enabling WAL;
                # that PRAGMA does not consistently honor SQLite's busy timeout.
                # All schema statements are idempotent, so retry only contention.
                db.executescript(SCHEMA)
                return db
            except sqlite3.OperationalError as exc:
                code = getattr(exc, 'sqlite_errorcode', 0) & 0xff
                if code not in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED) or time.monotonic() >= deadline:
                    raise
                time.sleep(.05)
    except BaseException:
        db.close()
        raise

@contextmanager
def transaction(path=None):
    db = connect(path)
    try:
        with db:
            yield db
    finally:
        db.close()

def put(db, kind, ident, payload):
    db.execute("INSERT OR REPLACE INTO documents VALUES (?,?,?)", (kind, ident, json.dumps(payload)))

def get(db, kind, ident):
    row = db.execute("SELECT payload FROM documents WHERE kind=? AND id=?", (kind, ident)).fetchone()
    return json.loads(row[0]) if row else None

def documents(db, kind):
    return [json.loads(r[0]) for r in db.execute("SELECT payload FROM documents WHERE kind=? ORDER BY id", (kind,))]
