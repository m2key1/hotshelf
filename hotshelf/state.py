import json
import sqlite3
import threading
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS pins(
    kind TEXT, key TEXT, name TEXT, granularity TEXT, PRIMARY KEY(kind, key));
CREATE TABLE IF NOT EXISTS log(
    ts TEXT, action TEXT, relpath TEXT, bytes INTEGER, ok INTEGER, detail TEXT);
CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY, v TEXT);
"""


class State:
    """Sqlite-backed pins, activity log and last-run snapshot."""

    def __init__(self, path):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        with self.lock:
            self.conn.executescript(SCHEMA)

    def pins(self):
        with self.lock:
            rows = self.conn.execute("SELECT * FROM pins ORDER BY name").fetchall()
        return [dict(r) for r in rows]

    def add_pin(self, kind, key, name, granularity=None):
        with self.lock, self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO pins VALUES (?,?,?,?)",
                (kind, key, name, granularity))

    def remove_pin(self, kind, key):
        with self.lock, self.conn:
            self.conn.execute("DELETE FROM pins WHERE kind=? AND key=?", (kind, key))

    def log(self, action, relpath="", size=0, ok=True, detail=""):
        with self.lock, self.conn:
            self.conn.execute(
                "INSERT INTO log VALUES (?,?,?,?,?,?)",
                (datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 action, relpath, size, int(ok), detail))

    def log_entries(self, limit=200):
        with self.lock:
            rows = self.conn.execute(
                "SELECT * FROM log ORDER BY rowid DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def set_kv(self, key, value):
        with self.lock, self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO kv VALUES (?,?)", (key, json.dumps(value)))

    def get_kv(self, key, default=None):
        with self.lock:
            row = self.conn.execute("SELECT v FROM kv WHERE k=?", (key,)).fetchone()
        return json.loads(row["v"]) if row else default
