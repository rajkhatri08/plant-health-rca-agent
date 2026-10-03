"""The action's side effect: one record per idempotency key, in its own SQLite file.

insert_once(key, payload) writes the record and returns True, or returns False if a
record with that key already exists. The key is the primary key, so a second write is
refused by SQLite itself, whatever process makes it (decision 73, criterion 5).
"""

import json
import sqlite3


class RecordStore:
    def __init__(self, path):
        self.path = str(path)
        with sqlite3.connect(self.path) as db:
            db.execute("CREATE TABLE IF NOT EXISTS records (key TEXT PRIMARY KEY, payload TEXT NOT NULL)")

    def insert_once(self, key, payload) -> bool:
        with sqlite3.connect(self.path) as db:
            cur = db.execute("INSERT OR IGNORE INTO records (key, payload) VALUES (?, ?)",
                             (key, json.dumps(payload, sort_keys=True)))
            return cur.rowcount == 1

    def all(self) -> list:
        with sqlite3.connect(self.path) as db:
            return [(k, json.loads(p)) for k, p in db.execute("SELECT key, payload FROM records ORDER BY key")]
