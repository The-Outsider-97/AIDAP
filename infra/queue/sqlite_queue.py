"""Durable job queue on the same SQLite database: leases, retry with backoff, dead-lettering, deduplication."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from ...app.ports import Job
from ...domain.utils.domain_helpers import iso, new_id, utcnow
from ..persistence.sqlite_store import SqliteDocStore

__all__ = ["SqliteJobQueue"]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY, kind TEXT NOT NULL, payload TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'queued',
  dedupe_key TEXT, run_after TEXT NOT NULL, lease_until TEXT, worker TEXT, attempts INTEGER NOT NULL DEFAULT 0,
  max_attempts INTEGER NOT NULL DEFAULT 3, last_error TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,
  finished_at TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS jobs_dedupe ON jobs(dedupe_key) WHERE dedupe_key IS NOT NULL AND dedupe_key != ''
  AND state IN ('queued','leased');
CREATE INDEX IF NOT EXISTS jobs_ready ON jobs(state, run_after);
"""


class SqliteJobQueue:
    def __init__(self, store: SqliteDocStore) -> None:
        self.store = store
        with store.transaction() as c:
            for stmt in [s for s in _SCHEMA.split(";") if s.strip()]:
                c.execute(stmt)

    def enqueue(self, kind: str, payload: dict[str, Any], *, dedupe_key: str = "", run_after: datetime | None = None,
                max_attempts: int = 3) -> str:
        now = utcnow()
        with self.store.transaction() as c:
            if dedupe_key:
                row = c.execute("SELECT id FROM jobs WHERE dedupe_key=? AND state IN ('queued','leased')",
                                (dedupe_key,)).fetchone()
                if row:
                    return row["id"]
            jid = new_id("job")
            c.execute("INSERT INTO jobs(id,kind,payload,dedupe_key,run_after,max_attempts,created_at) "
                      "VALUES (?,?,?,?,?,?,?)",
                      (jid, kind, json.dumps(payload, default=str), dedupe_key or None, iso(run_after or now),
                       max_attempts, iso(now)))
        return jid

    def lease(self, kinds: list[str], worker: str, lease_seconds: int = 300) -> Job | None:
        now = utcnow()
        marks = ",".join("?" * len(kinds))
        with self.store.transaction() as c:
            # expired leases come back; a crashed worker never strands a job
            c.execute("UPDATE jobs SET state='queued', worker=NULL WHERE state='leased' AND lease_until < ?", (iso(now),))
            row = c.execute(f"SELECT * FROM jobs WHERE state='queued' AND run_after <= ? AND kind IN ({marks}) "
                            "ORDER BY run_after, created_at LIMIT 1", (iso(now), *kinds)).fetchone()
            if not row:
                return None
            attempts = row["attempts"] + 1
            c.execute("UPDATE jobs SET state='leased', worker=?, lease_until=?, attempts=? WHERE id=?",
                      (worker, iso(now + timedelta(seconds=lease_seconds)), attempts, row["id"]))
            return Job(row["id"], row["kind"], json.loads(row["payload"]), attempts, row["dedupe_key"] or "",
                       row["max_attempts"])

    def heartbeat(self, job_id: str, lease_seconds: int = 300) -> None:
        with self.store.transaction() as c:
            c.execute("UPDATE jobs SET lease_until=? WHERE id=? AND state='leased'",
                      (iso(utcnow() + timedelta(seconds=lease_seconds)), job_id))

    def complete(self, job_id: str) -> None:
        with self.store.transaction() as c:
            c.execute("UPDATE jobs SET state='done', finished_at=?, lease_until=NULL WHERE id=?", (iso(utcnow()), job_id))

    def fail(self, job_id: str, error: str, *, retry_in_seconds: float | None = None) -> str:
        with self.store.transaction() as c:
            row = c.execute("SELECT attempts, max_attempts FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row:
                return "dead"
            if row["attempts"] >= row["max_attempts"]:
                c.execute("UPDATE jobs SET state='dead', last_error=?, finished_at=?, lease_until=NULL WHERE id=?",
                          (error[:2000], iso(utcnow()), job_id))
                return "dead"
            delay = retry_in_seconds if retry_in_seconds is not None else min(300.0, 2.0 ** row["attempts"] * 5)
            c.execute("UPDATE jobs SET state='queued', last_error=?, run_after=?, lease_until=NULL, worker=NULL WHERE id=?",
                      (error[:2000], iso(utcnow() + timedelta(seconds=delay)), job_id))
            return "queued"

    def cancel(self, dedupe_key: str) -> int:
        with self.store.transaction() as c:
            return c.execute("UPDATE jobs SET state='cancelled', finished_at=? WHERE dedupe_key=? AND state='queued'",
                             (iso(utcnow()), dedupe_key)).rowcount

    def stats(self) -> dict[str, int]:
        rows = self.store._conn().execute("SELECT state, COUNT(*) n FROM jobs GROUP BY state").fetchall()
        return {r["state"]: r["n"] for r in rows}
