"""Durable local state and ordered Firebase outbox; collection never needs cloud reads."""
import json
import logging
import os
from pathlib import Path
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager


class LocalQueue:
    def __init__(self, queue_file="cart.sqlite3", logger=None):
        self.logger = logger or logging.getLogger("outbox")
        self.lock = threading.RLock()
        self.consumer = threading.Lock()
        path = Path(queue_file)
        legacy = path if path.suffix == ".json" else path.with_name("firebase_queue.json")
        self.queue_file = str(path.with_suffix(".sqlite3") if path.suffix == ".json" else path)
        self.connection = sqlite3.connect(self.queue_file, timeout=10, check_same_thread=False)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=FULL")
        if self.connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise sqlite3.DatabaseError("Local journal corrupt; restore backup, do not reset it")
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS outbox (
              seq INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT UNIQUE NOT NULL,
              path TEXT NOT NULL, operation TEXT NOT NULL, payload TEXT NOT NULL,
              created REAL NOT NULL, coalesce_key TEXT);
            CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, payload TEXT NOT NULL);
        """)
        if legacy.exists() and not self.get_state("legacy_imported", False):
            items = json.loads(legacy.read_text())
            if not isinstance(items, list):
                raise ValueError("Legacy outbox must be an array; source retained")
            with self.transaction():
                for item in items:
                    self.enqueue(item["path"], item["data"], item.get("operation", "update"))
                self.set_state("legacy_imported", True)
        os.chmod(self.queue_file, 0o600)

    @contextmanager
    def transaction(self):
        with self.lock:
            nested = self.connection.in_transaction
            if not nested:
                self.connection.execute("BEGIN IMMEDIATE")
            try:
                yield self
                if not nested:
                    self.connection.commit()
            except BaseException:
                if not nested:
                    self.connection.rollback()
                raise

    def enqueue(self, path, data, operation="update", *, event_id=None, coalesce_key=None):
        if operation not in {"update", "set", "delete"}:
            raise ValueError("Unsupported outbox operation")
        if operation == "update" and not isinstance(data, dict):
            raise ValueError("Firebase update requires a mapping")
        encoded = json.dumps(data, allow_nan=False, separators=(",", ":"))
        identity = event_id or uuid.uuid4().hex
        with self.transaction():
            if coalesce_key:
                self.connection.execute("DELETE FROM outbox WHERE coalesce_key=?", (coalesce_key,))
            self.connection.execute(
                "INSERT OR IGNORE INTO outbox(event_id,path,operation,payload,created,coalesce_key) VALUES(?,?,?,?,?,?)",
                (identity, path, operation, encoded, time.time(), coalesce_key))
        return identity

    def set_state(self, key, value):
        with self.transaction():
            self.connection.execute("INSERT OR REPLACE INTO state VALUES(?,?)",
                                    (key, json.dumps(value, allow_nan=False)))

    def get_state(self, key, default=None):
        with self.lock:
            row = self.connection.execute("SELECT payload FROM state WHERE key=?", (key,)).fetchone()
            return json.loads(row[0]) if row else default

    def process(self, firebase_ref, logger=None, limit=100):
        processed = 0
        with self.consumer:
            with self.lock:
                rows = self.connection.execute(
                    "SELECT seq,path,operation,payload FROM outbox ORDER BY seq LIMIT ?", (limit,)).fetchall()
            for seq, path, operation, payload in rows:
                try:
                    target = firebase_ref.child(path) if path else firebase_ref
                    if operation == "delete":
                        target.delete()
                    else:
                        getattr(target, operation)(json.loads(payload))
                except Exception:
                    (logger or self.logger).warning("Outbox upload failed; retaining ordered events", exc_info=True)
                    break
                with self.transaction():
                    self.connection.execute("DELETE FROM outbox WHERE seq=?", (seq,))
                processed += 1
        return processed

    def size(self):
        with self.lock:
            return self.connection.execute("SELECT count(*) FROM outbox").fetchone()[0]

    def get_queue_contents(self):
        with self.lock:
            return [{"path": p, "operation": o, "data": json.loads(d)} for p, o, d in
                    self.connection.execute("SELECT path,operation,payload FROM outbox ORDER BY seq")]

    def close(self):
        with self.lock:
            self.connection.close()
