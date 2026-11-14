"""Small transactional JSON document store backed by SQLite.

One bot process owns this database. WAL and SQLite's online backup API make
restarts and backups safe without introducing a separate database service.
"""

import contextlib
import json
from pathlib import Path
import secrets
import sqlite3
import threading
import time


def new_id(prefix=""):
    return prefix + secrets.token_hex(6)


class Store:
    def __init__(self, path):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(str(path), isolation_level=None, check_same_thread=False)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=FULL")
        self.connection.execute("PRAGMA busy_timeout=5000")
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS documents (kind TEXT NOT NULL, key TEXT NOT NULL, "
            "body TEXT NOT NULL, PRIMARY KEY(kind,key))"
        )
        self.lock = threading.RLock()
        self.depth = 0

    @contextlib.contextmanager
    def atomic(self):
        with self.lock:
            name = f"transaction_{self.depth}"
            self.connection.execute(f"SAVEPOINT {name}")
            self.depth += 1
            try:
                yield self
            except BaseException:
                self.connection.execute(f"ROLLBACK TO {name}")
                raise
            finally:
                self.depth -= 1
                self.connection.execute(f"RELEASE {name}")

    def get(self, kind, key, default=None):
        with self.lock:
            row = self.connection.execute(
                "SELECT body FROM documents WHERE kind=? AND key=?", (kind, str(key))
            ).fetchone()
            return json.loads(row[0]) if row else default

    def put(self, kind, key, value):
        value = dict(value)
        value.setdefault("id", str(key))
        body = json.dumps(value, ensure_ascii=False, allow_nan=False)
        with self.lock:
            self.connection.execute(
                "INSERT INTO documents VALUES(?,?,?) ON CONFLICT(kind,key) DO UPDATE SET body=excluded.body",
                (kind, str(key), body),
            )
        return value

    def delete(self, kind, key):
        with self.lock:
            self.connection.execute("DELETE FROM documents WHERE kind=? AND key=?", (kind, str(key)))

    def list(self, kind, **filters):
        with self.lock:
            rows = self.connection.execute(
                "SELECT body FROM documents WHERE kind=? ORDER BY rowid", (kind,)
            ).fetchall()
        values = [json.loads(row[0]) for row in rows]
        return [value for value in values if all(value.get(key) == wanted for key, wanted in filters.items())]

    def event(self, match_id, kind, actor_id, data=None):
        key = new_id("E")
        return self.put("events", key, {"id": key, "match_id": match_id, "kind": kind,
                                      "actor_id": actor_id, "data": data or {}, "created_at": time.time()})

    def backup(self, destination):
        with self.lock, sqlite3.connect(str(destination)) as target:
            self.connection.backup(target)

    def close(self):
        with self.lock:
            self.connection.close()
