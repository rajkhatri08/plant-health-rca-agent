"""The agent's side effects: append-only records, each written once (decisions 17, 74).

Runtime code: no imports from dataset/, eval/ or ingest/. One SQLite file, one table:
records(kind, key, payload). (kind, key) is the primary key, so a second write with the
same key is refused by SQLite itself, whatever process makes it, and insert_once returns
False. Triggers refuse every UPDATE and DELETE: the records are append-only (decision 17).

Exactly once comes from these keys, not from LangGraph (decision 74): LangGraph re-runs a
step that didn't reach its checkpoint, after a crash or on resume, and only the key makes
the second write a no-op.

Kinds and their keys:
- diagnosis   {episode}:{stage}:diagnosis      the diagnosis of one pass (every outcome)
- ledger      the call's cache key             one row per LLM call (decision 76): tokens
                                               and cost; a cache hit costs nothing
- approval    {episode}:{stage}:approval       the human's verdict, from the approval step
- act         {episode}:{stage}:act            the approved recommendation (advisory: a
                                               record, never a write to plant controls)

LedgerClient wraps the LLM client so every call it answers writes its ledger row.
"""

import json
import sqlite3
from decimal import Decimal

from app.agent import llm

KINDS = ("diagnosis", "ledger", "approval", "act")


class RecordError(RuntimeError):
    pass


def diagnosis_key(episode, stage):
    return f"{episode}:{stage}:diagnosis"


def approval_key(episode, stage):
    return f"{episode}:{stage}:approval"


def act_key(episode, stage):
    return f"{episode}:{stage}:act"


class RecordStore:
    def __init__(self, path):
        self.path = str(path)
        with sqlite3.connect(self.path) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS records (
                    kind TEXT NOT NULL, key TEXT NOT NULL, payload TEXT NOT NULL,
                    PRIMARY KEY (kind, key));
                CREATE TRIGGER IF NOT EXISTS records_no_update BEFORE UPDATE ON records
                    BEGIN SELECT RAISE(ABORT, 'records are append-only'); END;
                CREATE TRIGGER IF NOT EXISTS records_no_delete BEFORE DELETE ON records
                    BEGIN SELECT RAISE(ABORT, 'records are append-only'); END;
            """)

    def insert_once(self, kind, key, payload) -> bool:
        """Write the record and return True, or return False if (kind, key) exists."""
        if kind not in KINDS:
            raise RecordError(f"a record kind is one of {KINDS}, not {kind!r}")
        with sqlite3.connect(self.path) as db:
            cur = db.execute("INSERT OR IGNORE INTO records (kind, key, payload) VALUES (?, ?, ?)",
                             (kind, key, json.dumps(payload, sort_keys=True)))
            return cur.rowcount == 1

    def get(self, kind, key):
        with sqlite3.connect(self.path) as db:
            row = db.execute("SELECT payload FROM records WHERE kind = ? AND key = ?", (kind, key)).fetchone()
        return json.loads(row[0]) if row else None

    def all(self, kind=None) -> list:
        """[(kind, key, payload), ...] ordered by kind then key; one kind if given."""
        sql, args = "SELECT kind, key, payload FROM records", ()
        if kind is not None:
            sql, args = sql + " WHERE kind = ?", (kind,)
        with sqlite3.connect(self.path) as db:
            return [(k, key, json.loads(p)) for k, key, p in db.execute(sql + " ORDER BY kind, key", args)]


class LedgerClient:
    """Wraps an LLM client: every answer writes its ledger row, keyed by the call's cache key,
    with the tokens and the cost (Rs; "0" for a cache hit, which spends nothing)."""

    def __init__(self, inner, records):
        self.inner, self.records, self.settings = inner, records, inner.settings

    def complete(self, prompt, schema, *, repeat):
        r = self.inner.complete(prompt, schema, repeat=repeat)
        cost = Decimal(0) if r.cached else llm.cost_inr(self.settings, r.tokens_in, r.tokens_out, r.tokens_thinking)
        self.records.insert_once("ledger", r.key, {
            "model_id": self.settings.model_id, "model_version": r.model_version,
            "schema_version": schema.version, "repeat": repeat, "cached": r.cached,
            "tokens_in": r.tokens_in, "tokens_out": r.tokens_out, "tokens_thinking": r.tokens_thinking,
            "latency_ms": r.latency_ms, "cost_inr": str(cost)})
        return r