"""SQLite store: the single transactional source of truth for a run (plan §4.2, §7.2).

* Records are JSON documents keyed by id. Kinds outside ``MUTABLE_KINDS`` are append-only.
* Every state change and its event are written in one transaction.
* Evidence is de-duplicated by (source, version, locator, content hash).
* Actions are de-duplicated by input fingerprint.
* A run lock prevents two processes from driving the same run.
JSONL/Markdown files are exports regenerated from this database.
"""
from __future__ import annotations

import json
import os
import socket
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Optional, TypeVar

from .models import (
    ALL_RECORD_TYPES, MUTABLE_KINDS, CandidateRevision, Evidence, Record, canonical_json, sha256_text, utcnow,
)

DB_SCHEMA_VERSION = 1

MIGRATIONS: dict[int, list[str]] = {
    1: [
        """CREATE TABLE IF NOT EXISTS records (
            id TEXT PRIMARY KEY, run_id TEXT NOT NULL, kind TEXT NOT NULL, json TEXT NOT NULL,
            content_hash TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""",
        "CREATE INDEX IF NOT EXISTS idx_records_kind ON records(run_id, kind)",
        """CREATE TABLE IF NOT EXISTS evidence_keys (
            run_id TEXT NOT NULL, dedup_key TEXT NOT NULL, evidence_id TEXT NOT NULL,
            PRIMARY KEY (run_id, dedup_key))""",
        """CREATE TABLE IF NOT EXISTS action_fingerprints (
            run_id TEXT NOT NULL, fingerprint TEXT NOT NULL, action_id TEXT NOT NULL,
            PRIMARY KEY (run_id, fingerprint))""",
        """CREATE TABLE IF NOT EXISTS events (
            seq INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, ts TEXT NOT NULL,
            type TEXT NOT NULL, payload TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS budget (
            id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, action_id TEXT,
            attempt INTEGER NOT NULL DEFAULT 1, backend_run_id TEXT, dimension TEXT NOT NULL,
            reserved REAL NOT NULL, actual REAL, state TEXT NOT NULL, cost_type TEXT NOT NULL,
            created_at TEXT NOT NULL, settled_at TEXT)""",
        "CREATE INDEX IF NOT EXISTS idx_budget_dim ON budget(run_id, dimension, state)",
        """CREATE TABLE IF NOT EXISTS run_lock (
            run_id TEXT PRIMARY KEY, pid INTEGER NOT NULL, host TEXT NOT NULL, acquired_at TEXT NOT NULL)""",
        "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    ],
}

R = TypeVar("R", bound=Record)


class StoreError(RuntimeError):
    pass


class ImmutableRecordError(StoreError):
    pass


class RunLocked(StoreError):
    pass


class Store:
    def __init__(self, path: Path, run_id: str):
        self.path = Path(path)
        self.run_id = run_id
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path), isolation_level=None, timeout=30)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._depth = 0
        self.migrate()

    # ------------------------------------------------------------------ schema
    def migrate(self) -> None:
        self.conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        row = self.conn.execute("SELECT value FROM meta WHERE key='db_schema_version'").fetchone()
        current = int(row[0]) if row else 0
        for version in sorted(v for v in MIGRATIONS if v > current):
            with self.tx():
                for stmt in MIGRATIONS[version]:
                    self.conn.execute(stmt)
                self.conn.execute(
                    "INSERT OR REPLACE INTO meta(key, value) VALUES ('db_schema_version', ?)", (str(version),))

    def close(self) -> None:
        self.conn.close()

    # ------------------------------------------------------------------ transactions
    @contextmanager
    def tx(self) -> Iterator["Store"]:
        """Nested-safe transaction. BEGIN IMMEDIATE takes the write lock up front so budget
        reservations by parallel workers serialise instead of reading the same balance."""
        if self._depth == 0:
            self.conn.execute("BEGIN IMMEDIATE")
        self._depth += 1
        try:
            yield self
        except BaseException:
            self._depth -= 1
            if self._depth == 0:
                self.conn.execute("ROLLBACK")
            raise
        else:
            self._depth -= 1
            if self._depth == 0:
                self.conn.execute("COMMIT")

    # ------------------------------------------------------------------ events
    def event(self, type_: str, payload: dict[str, Any] | None = None) -> None:
        self.conn.execute(
            "INSERT INTO events(run_id, ts, type, payload) VALUES (?,?,?,?)",
            (self.run_id, utcnow(), type_, canonical_json(payload or {})),
        )

    def events(self, type_: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT seq, ts, type, payload FROM events WHERE run_id=?"
        args: list[Any] = [self.run_id]
        if type_:
            sql += " AND type=?"
            args.append(type_)
        rows = self.conn.execute(sql + " ORDER BY seq", args).fetchall()
        return [{"seq": s, "ts": ts, "type": t, "payload": json.loads(p)} for s, ts, t, p in rows]

    # ------------------------------------------------------------------ records
    def put(self, record: Record, event: str | None = None, event_payload: dict | None = None) -> tuple[str, bool]:
        """Insert a record. Returns (id, created). Evidence with an existing dedup key is not
        inserted again; the existing id is returned with created=False."""
        body = record.model_dump(mode="json")
        text = canonical_json(body)
        with self.tx():
            if isinstance(record, Evidence):
                row = self.conn.execute(
                    "SELECT evidence_id FROM evidence_keys WHERE run_id=? AND dedup_key=?",
                    (self.run_id, record.dedup_key)).fetchone()
                if row:
                    self.event("evidence_duplicate", {"existing": row[0], "rejected": record.id,
                                                      "dedup_key": record.dedup_key})
                    return row[0], False
            existing = self.conn.execute("SELECT kind FROM records WHERE id=?", (record.id,)).fetchone()
            if existing:
                raise ImmutableRecordError(f"record {record.id} already exists; use update() for mutable kinds")
            now = utcnow()
            self.conn.execute(
                "INSERT INTO records(id, run_id, kind, json, content_hash, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                (record.id, self.run_id, type(record).__name__, text, sha256_text(text), now, now),
            )
            if isinstance(record, Evidence):
                self.conn.execute("INSERT INTO evidence_keys(run_id, dedup_key, evidence_id) VALUES (?,?,?)",
                                  (self.run_id, record.dedup_key, record.id))
            if event:
                self.event(event, {"id": record.id, "kind": type(record).__name__, **(event_payload or {})})
        return record.id, True

    def put_if_absent(self, record: Record, event: str | None = None, event_payload: dict | None = None) -> tuple[str, bool]:
        """For records with deterministic ids that a re-entered phase may produce again."""
        if self.exists(record.id):
            self.event("record_exists_skipped", {"id": record.id, "kind": type(record).__name__})
            return record.id, False
        return self.put(record, event, event_payload)

    def update(self, record: Record, event: str | None = None, event_payload: dict | None = None) -> None:
        if type(record).__name__ not in MUTABLE_KINDS:
            raise ImmutableRecordError(f"{type(record).__name__} is append-only; create a new record instead")
        with self.tx():
            old = self.get(record.id)
            if old is None:
                raise StoreError(f"cannot update missing record {record.id}")
            if isinstance(record, CandidateRevision):
                assert isinstance(old, CandidateRevision)
                if old.key_fields_hash != record.key_fields_hash:
                    raise ImmutableRecordError(
                        "changing hypothesis/scope/mechanism/protocol/claims requires a new CandidateRevision")
            text = canonical_json(record.model_dump(mode="json"))
            self.conn.execute("UPDATE records SET json=?, content_hash=?, updated_at=? WHERE id=?",
                              (text, sha256_text(text), utcnow(), record.id))
            if event:
                self.event(event, {"id": record.id, "kind": type(record).__name__, **(event_payload or {})})

    def get(self, record_id: str) -> Optional[Record]:
        row = self.conn.execute("SELECT kind, json FROM records WHERE id=?", (record_id,)).fetchone()
        if not row:
            return None
        return ALL_RECORD_TYPES[row[0]].model_validate_json(row[1])

    def require(self, record_id: str, kind: type[R]) -> R:
        rec = self.get(record_id)
        if rec is None or not isinstance(rec, kind):
            raise StoreError(f"expected {kind.__name__} {record_id}")
        return rec

    def exists(self, record_id: str) -> bool:
        return self.conn.execute("SELECT 1 FROM records WHERE id=?", (record_id,)).fetchone() is not None

    def kind_of(self, record_id: str) -> Optional[str]:
        row = self.conn.execute("SELECT kind FROM records WHERE id=?", (record_id,)).fetchone()
        return row[0] if row else None

    def list(self, kind: type[R], **filters: Any) -> list[R]:
        rows = self.conn.execute(
            "SELECT json FROM records WHERE run_id=? AND kind=? ORDER BY rowid", (self.run_id, kind.__name__)
        ).fetchall()
        out = [kind.model_validate_json(r[0]) for r in rows]
        for key, value in filters.items():
            out = [o for o in out if getattr(o, key) == value]
        return out

    def count(self, kind: type[Record]) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM records WHERE run_id=? AND kind=?",
                                 (self.run_id, kind.__name__)).fetchone()[0]

    # ------------------------------------------------------------------ action fingerprints
    def action_for_fingerprint(self, fingerprint: str) -> Optional[str]:
        row = self.conn.execute("SELECT action_id FROM action_fingerprints WHERE run_id=? AND fingerprint=?",
                                (self.run_id, fingerprint)).fetchone()
        return row[0] if row else None

    def bind_fingerprint(self, fingerprint: str, action_id: str) -> None:
        self.conn.execute("INSERT INTO action_fingerprints(run_id, fingerprint, action_id) VALUES (?,?,?)",
                          (self.run_id, fingerprint, action_id))

    # ------------------------------------------------------------------ run lock
    def acquire_lock(self) -> None:
        host = socket.gethostname()
        with self.tx():
            row = self.conn.execute("SELECT pid, host FROM run_lock WHERE run_id=?", (self.run_id,)).fetchone()
            if row:
                pid, lock_host = row
                if lock_host == host and pid != os.getpid() and _pid_alive(pid):
                    raise RunLocked(f"run {self.run_id} is locked by live process {pid} on {host}")
                if lock_host != host:
                    raise RunLocked(f"run {self.run_id} is locked by {lock_host}:{pid}; remove the lock only after checking it")
                self.event("stale_lock_taken_over", {"previous_pid": pid})
                self.conn.execute("DELETE FROM run_lock WHERE run_id=?", (self.run_id,))
            self.conn.execute("INSERT INTO run_lock(run_id, pid, host, acquired_at) VALUES (?,?,?,?)",
                              (self.run_id, os.getpid(), host, utcnow()))

    def release_lock(self) -> None:
        with self.tx():
            self.conn.execute("DELETE FROM run_lock WHERE run_id=? AND pid=?", (self.run_id, os.getpid()))
        self.checkpoint()

    def checkpoint(self) -> None:
        """Fold the WAL into the main file so state.sqlite alone is the complete record."""
        self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    # ------------------------------------------------------------------ export
    def export_jsonl(self, out_dir: Path) -> list[Path]:
        out_dir.mkdir(parents=True, exist_ok=True)
        written: list[Path] = []
        kinds = [r[0] for r in self.conn.execute(
            "SELECT DISTINCT kind FROM records WHERE run_id=? ORDER BY kind", (self.run_id,)).fetchall()]
        for kind in kinds:
            path = out_dir / f"{kind}.jsonl"
            rows = self.conn.execute("SELECT json FROM records WHERE run_id=? AND kind=? ORDER BY rowid",
                                     (self.run_id, kind)).fetchall()
            path.write_text("".join(r[0] + "\n" for r in rows), encoding="utf-8")
            written.append(path)
        ev = out_dir / "events.jsonl"
        ev.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in self.events()), encoding="utf-8")
        written.append(ev)
        bud = out_dir / "budget_ledger.jsonl"
        cols = ["id", "action_id", "attempt", "backend_run_id", "dimension", "reserved", "actual", "state",
                "cost_type", "created_at", "settled_at"]
        rows = self.conn.execute(f"SELECT {', '.join(cols)} FROM budget WHERE run_id=? ORDER BY id",
                                 (self.run_id,)).fetchall()
        bud.write_text("".join(json.dumps(dict(zip(cols, r))) + "\n" for r in rows), encoding="utf-8")
        written.append(bud)
        return written


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def new_id(prefix: str) -> str:
    """Time-ordered readable ids; uniqueness within a run is enforced by the PRIMARY KEY."""
    return f"{prefix}_{time.time_ns():x}"
