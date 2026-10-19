"""SQLite document store (WAL) with transactions and a hash-chained, append-only audit log.

SQLite is the single-node default. The ``DocStore`` port is deliberately small (insert/put/get/find/count/delete +
audit) so a PostgreSQL adapter can replace this module without touching the app layer.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from ...domain.utils.domain_errors import Conflict, Unavailable
from ...domain.utils.domain_helpers import canonical_digest, canonical_json, iso, new_id, utcnow

__all__ = ["SqliteDocStore"]

_FIELD = re.compile(r"^[a-z_][a-z0-9_]*(\.[a-z_][a-z0-9_]*){0,3}$")
_COLL = re.compile(r"^[a-z_][a-z0-9_]{0,40}$")
_OPS = {"<": "<", "<=": "<=", ">": ">", ">=": ">=", "!=": "!="}
GENESIS = "0" * 64

_SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
CREATE TABLE IF NOT EXISTS docs (
  coll TEXT NOT NULL, id TEXT NOT NULL, tenant_id TEXT NOT NULL DEFAULT '', ukey TEXT,
  created_at TEXT NOT NULL, data TEXT NOT NULL, PRIMARY KEY (coll, id));
CREATE UNIQUE INDEX IF NOT EXISTS docs_ukey ON docs(coll, ukey) WHERE ukey IS NOT NULL;
CREATE INDEX IF NOT EXISTS docs_tenant ON docs(coll, tenant_id, created_at);
CREATE INDEX IF NOT EXISTS docs_project ON docs(coll, tenant_id, json_extract(data, '$.project_id'));
CREATE INDEX IF NOT EXISTS docs_run ON docs(coll, json_extract(data, '$.run_id'));
CREATE INDEX IF NOT EXISTS docs_state ON docs(coll, tenant_id, json_extract(data, '$.state'));
CREATE TABLE IF NOT EXISTS audit (
  seq INTEGER PRIMARY KEY AUTOINCREMENT, tenant_id TEXT NOT NULL, id TEXT NOT NULL UNIQUE, at TEXT NOT NULL,
  data TEXT NOT NULL, prev_hash TEXT NOT NULL, hash TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS audit_tenant ON audit(tenant_id, seq);
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit
  BEGIN SELECT RAISE(ABORT, 'audit log is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit
  BEGIN SELECT RAISE(ABORT, 'audit log is append-only'); END;
"""


def _scalar(v: Any) -> Any:
    return int(v) if isinstance(v, bool) else v


class SqliteDocStore:
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._write_lock = threading.RLock()
        self._memory_conn: sqlite3.Connection | None = None
        conn = self._conn()
        conn.executescript(_SCHEMA)

    # ------------------------------------------------------------------ connections / transactions
    def _conn(self) -> sqlite3.Connection:
        if self.path == ":memory:":
            if self._memory_conn is None:
                self._memory_conn = sqlite3.connect(":memory:", check_same_thread=False, isolation_level=None)
                self._memory_conn.row_factory = sqlite3.Row
            return self._memory_conn
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.path, timeout=30, isolation_level=None)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=30000")
            self._local.conn = conn
            self._local.depth = 0
        return conn

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        conn = self._conn()
        depth = getattr(self._local, "depth", 0)
        if self.path == ":memory:":
            self._write_lock.acquire()
        try:
            if depth == 0:
                conn.execute("BEGIN IMMEDIATE")
            self._local.depth = depth + 1
            try:
                yield conn
            except BaseException:
                self._local.depth -= 1
                if self._local.depth == 0:
                    conn.execute("ROLLBACK")
                raise
            else:
                self._local.depth -= 1
                if self._local.depth == 0:
                    conn.execute("COMMIT")
        finally:
            if self.path == ":memory:":
                self._write_lock.release()

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        with self.transaction() as conn:
            yield conn

    @staticmethod
    def _check_coll(coll: str) -> None:
        if not _COLL.match(coll):
            raise ValueError(f"bad collection name: {coll!r}")

    # ------------------------------------------------------------------ writes
    def insert(self, coll: str, doc: dict[str, Any], *, tenant_id: str = "", ukey: str | None = None) -> bool:
        self._check_coll(coll)
        if "id" not in doc:
            raise ValueError("document needs an id")
        with self._write() as conn:
            try:
                conn.execute("INSERT INTO docs(coll,id,tenant_id,ukey,created_at,data) VALUES (?,?,?,?,?,?)",
                             (coll, doc["id"], tenant_id, ukey, str(doc.get("created_at") or iso(utcnow())),
                              json.dumps(doc, default=str, ensure_ascii=False)))
            except sqlite3.IntegrityError:
                return False
        return True

    def put(self, coll: str, doc: dict[str, Any], *, tenant_id: str = "", ukey: str | None = None) -> None:
        self._check_coll(coll)
        with self._write() as conn:
            try:
                conn.execute(
                    "INSERT INTO docs(coll,id,tenant_id,ukey,created_at,data) VALUES (?,?,?,?,?,?) "
                    "ON CONFLICT(coll,id) DO UPDATE SET data=excluded.data, "
                    "ukey=COALESCE(excluded.ukey, docs.ukey)",
                    (coll, doc["id"], tenant_id, ukey, str(doc.get("created_at") or iso(utcnow())),
                     json.dumps(doc, default=str, ensure_ascii=False)))
            except sqlite3.IntegrityError as exc:
                raise Conflict("a record with the same unique key already exists", code="duplicate") from exc

    def delete(self, coll: str, doc_id: str, *, tenant_id: str | None = None) -> bool:
        self._check_coll(coll)
        sql, args = "DELETE FROM docs WHERE coll=? AND id=?", [coll, doc_id]
        if tenant_id is not None:
            sql += " AND tenant_id=?"
            args.append(tenant_id)
        with self._write() as conn:
            return conn.execute(sql, args).rowcount > 0

    # ------------------------------------------------------------------ reads
    def get(self, coll: str, doc_id: str, *, tenant_id: str | None = None) -> dict[str, Any] | None:
        self._check_coll(coll)
        sql, args = "SELECT data FROM docs WHERE coll=? AND id=?", [coll, doc_id]
        if tenant_id is not None:
            sql += " AND tenant_id=?"
            args.append(tenant_id)
        row = self._conn().execute(sql, args).fetchone()
        return json.loads(row["data"]) if row else None

    def get_by_ukey(self, coll: str, ukey: str) -> dict[str, Any] | None:
        self._check_coll(coll)
        row = self._conn().execute("SELECT data FROM docs WHERE coll=? AND ukey=?", (coll, ukey)).fetchone()
        return json.loads(row["data"]) if row else None

    @staticmethod
    def _where(tenant_id: str | None, where: dict[str, Any] | None) -> tuple[str, list[Any]]:
        clauses, args = [], []
        if tenant_id is not None:
            clauses.append("tenant_id=?")
            args.append(tenant_id)
        for key, cond in (where or {}).items():
            if not _FIELD.match(key):
                raise ValueError(f"bad field: {key!r}")
            col = f"json_extract(data,'$.{key}')"
            if cond is None:
                clauses.append(f"{col} IS NULL")
            elif isinstance(cond, (list, set, frozenset)):
                vals = [_scalar(v) for v in cond]
                if not vals:
                    clauses.append("0")
                else:
                    clauses.append(f"{col} IN ({','.join('?' * len(vals))})")
                    args.extend(vals)
            elif isinstance(cond, tuple) and len(cond) == 2 and cond[0] in _OPS:
                clauses.append(f"{col} {_OPS[cond[0]]} ?")
                args.append(_scalar(cond[1]))
            else:
                clauses.append(f"{col} = ?")
                args.append(_scalar(cond))
        return (" AND " + " AND ".join(clauses)) if clauses else "", args

    def find(self, coll: str, *, tenant_id: str | None = None, where: dict[str, Any] | None = None,
             order_by: str = "created_at", desc: bool = True, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        self._check_coll(coll)
        clause, args = self._where(tenant_id, where)
        if order_by in ("created_at", "id"):
            order = order_by
        elif _FIELD.match(order_by):
            order = f"json_extract(data,'$.{order_by}')"
        else:
            raise ValueError("bad order field")
        sql = (f"SELECT data FROM docs WHERE coll=?{clause} ORDER BY {order} {'DESC' if desc else 'ASC'}, id "
               f"{'DESC' if desc else 'ASC'} LIMIT ? OFFSET ?")
        rows = self._conn().execute(sql, [coll, *args, max(1, min(int(limit), 5000)), max(0, int(offset))]).fetchall()
        return [json.loads(r["data"]) for r in rows]

    def count(self, coll: str, *, tenant_id: str | None = None, where: dict[str, Any] | None = None) -> int:
        self._check_coll(coll)
        clause, args = self._where(tenant_id, where)
        return int(self._conn().execute(f"SELECT COUNT(*) FROM docs WHERE coll=?{clause}", [coll, *args]).fetchone()[0])

    # ------------------------------------------------------------------ audit chain
    @staticmethod
    def _event_hash(event: dict[str, Any], prev_hash: str) -> str:
        body = {k: v for k, v in event.items() if k not in ("hash", "prev_hash")}
        return canonical_digest({"prev": prev_hash, "event": body})

    def append_audit(self, tenant_id: str, event: dict[str, Any]) -> dict[str, Any]:
        with self._write() as conn:
            row = conn.execute("SELECT hash FROM audit WHERE tenant_id=? ORDER BY seq DESC LIMIT 1",
                               (tenant_id,)).fetchone()
            prev = row["hash"] if row else GENESIS
            event = dict(event)
            event.setdefault("id", new_id("aud"))
            event.setdefault("at", iso(utcnow()))
            event["tenant_id"] = tenant_id
            event["prev_hash"] = prev
            event["hash"] = self._event_hash(event, prev)
            conn.execute("INSERT INTO audit(tenant_id,id,at,data,prev_hash,hash) VALUES (?,?,?,?,?,?)",
                         (tenant_id, event["id"], str(event["at"]), json.dumps(event, default=str, ensure_ascii=False),
                          prev, event["hash"]))
        return event

    def audit_events(self, tenant_id: str, *, limit: int = 100, offset: int = 0, desc: bool = True,
                     action_prefix: str = "") -> list[dict[str, Any]]:
        sql = "SELECT data FROM audit WHERE tenant_id=?"
        args: list[Any] = [tenant_id]
        if action_prefix:
            sql += " AND json_extract(data,'$.action') LIKE ?"
            args.append(action_prefix.replace("%", "") + "%")
        sql += f" ORDER BY seq {'DESC' if desc else 'ASC'} LIMIT ? OFFSET ?"
        args += [max(1, min(limit, 10000)), max(0, offset)]
        return [json.loads(r["data"]) for r in self._conn().execute(sql, args).fetchall()]

    def verify_audit(self, tenant_id: str) -> dict[str, Any]:
        prev, n = GENESIS, 0
        for row in self._conn().execute("SELECT data, prev_hash, hash FROM audit WHERE tenant_id=? ORDER BY seq",
                                        (tenant_id,)):
            ev = json.loads(row["data"])
            n += 1
            if row["prev_hash"] != prev or ev.get("prev_hash") != prev or self._event_hash(ev, prev) != row["hash"] \
                    or ev.get("hash") != row["hash"]:
                return {"ok": False, "events": n, "broken_at": ev.get("id"), "head": prev}
            prev = row["hash"]
        return {"ok": True, "events": n, "broken_at": None, "head": prev}

    # ------------------------------------------------------------------ health / maintenance
    def health(self) -> dict[str, Any]:
        try:
            self._conn().execute("SELECT 1").fetchone()
            return {"ok": True, "engine": "sqlite", "path": self.path}
        except sqlite3.Error as exc:                                    # pragma: no cover
            raise Unavailable(f"database unavailable: {exc}") from exc

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None
