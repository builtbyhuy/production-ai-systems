"""Versioned tenant memory: authoritative SQLite, actual Redis, derived Qdrant."""
from __future__ import annotations

import contextlib
import hashlib
import json
import re
import shutil
import socket
import subprocess
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from pydantic import Field

from pais.contracts import Principal, StrictModel, new_id, utcnow
from pais.db import Database
from pais.retrieval import require_read
from pais.vectors import QdrantIndex


class MemoryConflict(ValueError):
    pass


class MemoryRecord(StrictModel):
    memory_id: str
    tenant_id: str
    version: int
    text: str
    confidence: float = Field(ge=0, le=1)
    provenance: list[dict[str, str]]
    expires_at: float
    deleted: bool = False


class RedisMemoryCache:
    _SYNC = """
    local current=redis.call('HGET',KEYS[1],'version')
    local deleted=redis.call('HGET',KEYS[1],'deleted')
    local digest=redis.call('HGET',KEYS[1],'digest')
    if current and tonumber(current)>tonumber(ARGV[1]) then return 0 end
    if current and tonumber(current)==tonumber(ARGV[1]) then
      if deleted=='1' and ARGV[2]=='0' then return 0 end
      if digest and digest~=ARGV[3] then return 0 end
    end
    redis.call('HSET',KEYS[1],'version',ARGV[1],'deleted',ARGV[2],'digest',ARGV[3])
    if ARGV[2]=='1' then redis.call('DEL',KEYS[2])
    else redis.call('SET',KEYS[2],ARGV[4],'EX',ARGV[5]) end
    return 1
    """

    def __init__(self, url: str):
        import redis
        self.client = redis.Redis.from_url(url, decode_responses=True, socket_timeout=3)
        self.client.ping()

    @staticmethod
    def _key(tenant: str, identifier: str, kind: str) -> str:
        digest = hashlib.sha256(json.dumps([tenant, identifier]).encode()).hexdigest()
        return f"pais:{kind}:{digest}"

    def sync(self, record: MemoryRecord, ttl: int) -> bool:
        data = record.model_dump_json()
        result = self.client.eval(self._SYNC, 2,
            self._key(record.tenant_id, record.memory_id, "memory-marker"),
            self._key(record.tenant_id, record.memory_id, "memory"),
            record.version, int(record.deleted), hashlib.sha256(data.encode()).hexdigest(), data, max(1, ttl))
        return bool(result)

    def get(self, principal: Principal, memory_id: str) -> MemoryRecord | None:
        raw = self.client.get(self._key(principal.tenant_id, memory_id, "memory"))
        return MemoryRecord.model_validate_json(raw) if raw else None

    def append_message(self, principal: Principal, session_id: str, text: str, capacity: int = 20) -> None:
        key = self._key(principal.tenant_id, session_id, "buffer")
        with self.client.pipeline(transaction=True) as pipe:
            pipe.rpush(key, text)
            pipe.ltrim(key, -capacity, -1)
            pipe.expire(key, 3600)
            pipe.execute()

    def messages(self, principal: Principal, session_id: str) -> list[str]:
        return self.client.lrange(self._key(principal.tenant_id, session_id, "buffer"), 0, -1)


class MemoryService:
    suspicious = re.compile(r"ignore\s+(?:all|previous)|system\s+prompt|run\s+(?:shell|bash)|upload\s+credentials|you\s+are\s+now", re.IGNORECASE)

    def __init__(self, db_path: str | Path, redis_url: str, *, capacity: int = 100,
                 clock: Callable[[], float] = time.time, vector_index: QdrantIndex | None = None):
        if not 1 <= capacity <= 100000:
            raise ValueError("Memory capacity out of range")
        self.db, self.capacity, self.clock = Database(db_path), capacity, clock
        self.cache = RedisMemoryCache(redis_url)
        self.vectors = vector_index or QdrantIndex(str(db_path) + ".vectors")
        self.owns_vectors = vector_index is None
        self.db.initialize("""
            CREATE TABLE IF NOT EXISTS mem_records (
              tenant_id TEXT NOT NULL, memory_id TEXT NOT NULL, version INTEGER NOT NULL,
              text TEXT NOT NULL, confidence REAL NOT NULL, provenance TEXT NOT NULL,
              expires_at REAL NOT NULL, deleted INTEGER NOT NULL DEFAULT 0,
              last_access REAL NOT NULL, updated_at TEXT NOT NULL,
              PRIMARY KEY(tenant_id,memory_id));
            CREATE TABLE IF NOT EXISTS mem_pending (
              tenant_id TEXT NOT NULL,memory_id TEXT NOT NULL,version INTEGER NOT NULL,
              PRIMARY KEY(tenant_id,memory_id));
            CREATE TABLE IF NOT EXISTS mem_sessions (
              tenant_id TEXT NOT NULL,session_id TEXT NOT NULL,subject TEXT NOT NULL,
              created_at TEXT NOT NULL,PRIMARY KEY(tenant_id,session_id));
            CREATE TABLE IF NOT EXISTS mem_summaries (
              tenant_id TEXT NOT NULL,session_id TEXT NOT NULL,summary TEXT NOT NULL,refs TEXT NOT NULL,
              PRIMARY KEY(tenant_id,session_id));
            CREATE TABLE IF NOT EXISTS mem_changes (
              sequence INTEGER PRIMARY KEY AUTOINCREMENT,tenant_id TEXT NOT NULL,memory_id TEXT NOT NULL,
              version INTEGER NOT NULL,kind TEXT NOT NULL,timestamp TEXT NOT NULL);
        """)

    def close(self) -> None:
        self.cache.client.close()
        if self.owns_vectors:
            self.vectors.close()

    @staticmethod
    def _record(row: Any) -> MemoryRecord:
        return MemoryRecord(memory_id=row["memory_id"], tenant_id=row["tenant_id"], version=row["version"],
            text=row["text"], confidence=row["confidence"], provenance=json.loads(row["provenance"]),
            expires_at=row["expires_at"], deleted=bool(row["deleted"]))

    @staticmethod
    def _change(conn: Any, tenant: str, key: str, version: int, kind: str) -> None:
        conn.execute("INSERT INTO mem_changes(tenant_id,memory_id,version,kind,timestamp) VALUES(?,?,?,?,?)",
                     (tenant, key, version, kind, utcnow()))
        conn.execute("INSERT INTO mem_pending VALUES(?,?,?) ON CONFLICT(tenant_id,memory_id) DO UPDATE SET version=excluded.version",
                     (tenant, key, version))
        summaries = conn.execute("SELECT session_id,refs FROM mem_summaries WHERE tenant_id=?", (tenant,)).fetchall()
        for summary in summaries:
            if key in json.loads(summary["refs"]):
                conn.execute("DELETE FROM mem_summaries WHERE tenant_id=? AND session_id=?", (tenant, summary["session_id"]))

    def put(self, principal: Principal, memory_id: str, text: str, *, expected_version: int = 0,
            confidence: float = 1.0, provenance: list[dict[str, str]], ttl_seconds: int = 3600) -> MemoryRecord:
        require_read(principal)
        principal.require("writer")
        if not memory_id or not text.strip() or len(text) > 20000:
            raise ValueError("Memory identifier and bounded content are required")
        if self.suspicious.search(text):
            raise PermissionError("Instruction-like memory rejected by the development poison rule")
        if not provenance or any(not p.get("source_id") or not p.get("version") for p in provenance):
            raise ValueError("Memory requires source identity and source version")
        if not 0 <= confidence <= 1 or not 1 <= ttl_seconds <= 30 * 86400:
            raise ValueError("Confidence or TTL is out of bounds")
        with self.db.transaction() as conn:
            row = conn.execute("SELECT * FROM mem_records WHERE tenant_id=? AND memory_id=?",
                               (principal.tenant_id, memory_id)).fetchone()
            version = row["version"] if row else 0
            if expected_version != version:
                raise MemoryConflict("Stale memory version; correction/deletion wins over session synchronization")
            if row and row["deleted"]:
                raise MemoryConflict("Deleted memory IDs cannot be resurrected; create a reviewed new ID")
            if row and row["expires_at"] <= self.clock():
                raise MemoryConflict("Expired memory cannot be revived by a stale session; create a new ID")
            version += 1
            conn.execute("INSERT INTO mem_records VALUES(?,?,?,?,?,?,?,0,?,?) ON CONFLICT(tenant_id,memory_id) "
                         "DO UPDATE SET version=excluded.version,text=excluded.text,confidence=excluded.confidence,"
                         "provenance=excluded.provenance,expires_at=excluded.expires_at,last_access=excluded.last_access,updated_at=excluded.updated_at",
                         (principal.tenant_id, memory_id, version, text, confidence, json.dumps(provenance),
                          self.clock() + ttl_seconds, self.clock(), utcnow()))
            self._change(conn, principal.tenant_id, memory_id, version, "created" if version == 1 else "corrected")
            rows = conn.execute("SELECT memory_id,version FROM mem_records WHERE tenant_id=? AND deleted=0 "
                                "ORDER BY confidence ASC,last_access ASC,memory_id ASC", (principal.tenant_id,)).fetchall()
            for evicted in rows[:max(0, len(rows) - self.capacity)]:
                self._tombstone(conn, principal, evicted["memory_id"], evicted["version"], "evicted")
        self.flush(principal)
        return self.get(principal, memory_id, include_deleted=True)

    def _tombstone(self, conn: Any, principal: Principal, memory_id: str, version: int, kind: str) -> None:
        conn.execute("UPDATE mem_records SET version=?,deleted=1,text='',provenance='[]',confidence=0,updated_at=? "
                     "WHERE tenant_id=? AND memory_id=? AND version=?",
                     (version + 1, utcnow(), principal.tenant_id, memory_id, version))
        self._change(conn, principal.tenant_id, memory_id, version + 1, kind)

    def delete(self, principal: Principal, memory_id: str, expected_version: int) -> MemoryRecord:
        require_read(principal)
        principal.require("writer")
        with self.db.transaction() as conn:
            row = conn.execute("SELECT * FROM mem_records WHERE tenant_id=? AND memory_id=?",
                               (principal.tenant_id, memory_id)).fetchone()
            if row is None:
                raise LookupError("Memory not found")
            if row["version"] != expected_version:
                raise MemoryConflict("Stale deletion version")
            self._tombstone(conn, principal, memory_id, expected_version, "deleted")
        self.flush(principal)
        return self.get(principal, memory_id, include_deleted=True)

    def expire(self, principal: Principal) -> int:
        require_read(principal)
        with self.db.transaction() as conn:
            rows = conn.execute("SELECT memory_id,version FROM mem_records WHERE tenant_id=? AND deleted=0 AND expires_at<=?",
                                (principal.tenant_id, self.clock())).fetchall()
            for row in rows:
                self._tombstone(conn, principal, row["memory_id"], row["version"], "expired")
        if rows:
            self.flush(principal)
        return len(rows)

    def get(self, principal: Principal, memory_id: str, *, include_deleted: bool = False) -> MemoryRecord:
        require_read(principal)
        with self.db.transaction(False) as conn:
            row = conn.execute("SELECT * FROM mem_records WHERE tenant_id=? AND memory_id=?",
                               (principal.tenant_id, memory_id)).fetchone()
        if row is None:
            raise LookupError("Memory not found")
        item = self._record(row)
        if not include_deleted and (item.deleted or item.expires_at <= self.clock()):
            raise LookupError("Memory is deleted or expired")
        cached = self.cache.get(principal, memory_id)
        if cached and cached.version == item.version and cached == item:
            return cached
        self.cache.sync(item, max(1, int(item.expires_at - self.clock())))
        return item

    def flush(self, principal: Principal) -> int:
        """Reconcile derived Redis/Qdrant state after a crash between durable writes."""
        require_read(principal)
        with self.db.transaction(False) as conn:
            rows = conn.execute("SELECT r.* FROM mem_pending p JOIN mem_records r USING(tenant_id,memory_id) WHERE p.tenant_id=?",
                                (principal.tenant_id,)).fetchall()
        # Maintenance only copies authoritative rows in the previously authenticated tenant.
        maintenance = Principal(subject=principal.subject, tenant_id=principal.tenant_id, roles=["writer"])
        for row in rows:
            item = self._record(row)
            with self.db.transaction() as conn:
                current = conn.execute("SELECT version FROM mem_records WHERE tenant_id=? AND memory_id=?",
                                       (principal.tenant_id, item.memory_id)).fetchone()
                if current["version"] != item.version:
                    continue
                with self.vectors.db.transaction(False) as vector_conn:
                    indexed = vector_conn.execute("SELECT version,deleted FROM vec_documents WHERE tenant_id=? AND document_id=?",
                                                  (principal.tenant_id, item.memory_id)).fetchone()
                if item.deleted:
                    if indexed:
                        self.vectors.delete(maintenance, item.memory_id, indexed["version"])
                else:
                    self.vectors.upsert(maintenance, item.memory_id, item.text,
                        {"memory_version": item.version, "confidence": item.confidence},
                        expected_version=indexed["version"] if indexed else 0)
                self.cache.sync(item, max(1, int(item.expires_at - self.clock())))
                conn.execute("DELETE FROM mem_pending WHERE tenant_id=? AND memory_id=? AND version=?",
                             (principal.tenant_id, item.memory_id, item.version))
        return len(rows)

    def recall(self, principal: Principal, query: str, limit: int = 5, confidence_floor: float = 0.8) -> list[MemoryRecord]:
        require_read(principal)
        if not 0 <= confidence_floor <= 1 or not 1 <= limit <= 100:
            raise ValueError("Confidence floor or result limit out of range")
        self.expire(principal)
        candidates = self.vectors.search(principal, query, limit=min(100, max(10, limit * 5)))
        query_words = set(re.findall(r"\w+", query.casefold()))
        result = []
        for hit in candidates:
            try:
                item = self.get(principal, hit.document_id)
            except LookupError:
                continue
            if item.version != hit.metadata.get("memory_version") or item.confidence < confidence_floor:
                continue
            if not query_words.intersection(re.findall(r"\w+", item.text.casefold())):
                continue
            result.append(item)
            if len(result) >= limit:
                break
        with self.db.transaction() as conn:
            conn.executemany("UPDATE mem_records SET last_access=? WHERE tenant_id=? AND memory_id=?",
                             [(self.clock(), principal.tenant_id, item.memory_id) for item in result])
        return result

    def start_session(self, principal: Principal, session_id: str | None = None) -> str:
        require_read(principal)
        identifier = session_id or new_id()
        with self.db.transaction() as conn:
            conn.execute("INSERT INTO mem_sessions VALUES(?,?,?,?)", (principal.tenant_id, identifier, principal.subject, utcnow()))
        return identifier

    def _session(self, principal: Principal, session_id: str) -> None:
        require_read(principal)
        with self.db.transaction(False) as conn:
            row = conn.execute("SELECT subject FROM mem_sessions WHERE tenant_id=? AND session_id=?",
                               (principal.tenant_id, session_id)).fetchone()
        if row is None or row["subject"] != principal.subject:
            raise PermissionError("Session is not owned by the current principal")

    def append_message(self, principal: Principal, session_id: str, text: str) -> None:
        self._session(principal, session_id)
        if not text or len(text) > 4000:
            raise ValueError("Conversation message length out of bounds")
        self.cache.append_message(principal, session_id, text)

    def buffer(self, principal: Principal, session_id: str) -> list[str]:
        self._session(principal, session_id)
        return self.cache.messages(principal, session_id)

    def summarize(self, principal: Principal, session_id: str, memory_ids: list[str], max_chars: int = 300) -> dict[str, Any]:
        self._session(principal, session_id)
        if not 50 <= max_chars <= 4000:
            raise ValueError("Summary character limit out of bounds")
        records = [self.get(principal, key) for key in memory_ids]
        refs = {item.memory_id: item.version for item in records}
        text = " ".join(item.text for item in records)
        summary = text if len(text) <= max_chars else text[:max_chars - 1] + "…"
        with self.db.transaction() as conn:
            for item in records:
                current = conn.execute("SELECT version,deleted,expires_at FROM mem_records WHERE tenant_id=? AND memory_id=?",
                                       (principal.tenant_id, item.memory_id)).fetchone()
                if current is None or current["version"] != item.version or current["deleted"] or current["expires_at"] <= self.clock():
                    raise MemoryConflict("Summary source changed before it could be stored")
            conn.execute("INSERT INTO mem_summaries VALUES(?,?,?,?) ON CONFLICT(tenant_id,session_id) "
                         "DO UPDATE SET summary=excluded.summary,refs=excluded.refs",
                         (principal.tenant_id, session_id, summary, json.dumps(refs)))
        return {"summary": summary, "references": refs, "lossy": len(text) > max_chars,
                "authority": "untrusted_memory", "original_characters": len(text), "summary_characters": len(summary)}

    def summary(self, principal: Principal, session_id: str) -> dict[str, Any] | None:
        self._session(principal, session_id)
        with self.db.transaction(False) as conn:
            row = conn.execute("SELECT * FROM mem_summaries WHERE tenant_id=? AND session_id=?",
                               (principal.tenant_id, session_id)).fetchone()
        if row is None:
            return None
        refs = json.loads(row["refs"])
        for key, version in refs.items():
            try:
                item = self.get(principal, key)
            except LookupError:
                return None
            if item.version != version:
                return None
        return {"summary": row["summary"], "references": refs, "authority": "untrusted_memory"}

    def changes(self, principal: Principal, after: int = 0) -> list[dict[str, Any]]:
        require_read(principal)
        with self.db.transaction(False) as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM mem_changes WHERE tenant_id=? AND sequence>? ORDER BY sequence LIMIT 1000",
                                                     (principal.tenant_id, after)).fetchall()]


class NativeRedis:
    """Trusted Redis process with AOF; this is not an execution sandbox."""
    def __init__(self, directory: str | Path, binary: str | Path | None = None):
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        bundled = Path(__file__).resolve().parents[2] / ".tools/redis-8.2.1/src/redis-server"
        executable = str(binary) if binary else (shutil.which("redis-server") or str(bundled))
        if not Path(executable).is_file():
            raise RuntimeError("Redis server missing; install Redis or supply a redis-server binary")
        self.binary = executable
        self.process: subprocess.Popen[bytes] | None = None
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 0))
            self.port = probe.getsockname()[1]
        self.url = f"redis://127.0.0.1:{self.port}/0"

    def start(self) -> None:
        import redis
        self.process = subprocess.Popen([self.binary, "--port", str(self.port), "--bind", "127.0.0.1",
            "--protected-mode", "yes", "--dir", str(self.directory), "--appendonly", "yes",
            "--appendfsync", "always", "--save", "", "--logfile", str(self.directory / "redis.log")],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.monotonic() + 10
        client = redis.Redis.from_url(self.url, socket_timeout=1)
        while time.monotonic() < deadline:
            try:
                if client.ping():
                    client.close()
                    return
            except redis.RedisError:
                if self.process.poll() is not None:
                    raise RuntimeError("Redis failed to start; inspect redis.log") from None
            time.sleep(0.03)
        raise RuntimeError("Redis did not become ready in ten seconds")

    def stop(self, kill: bool = False) -> None:
        if self.process and self.process.poll() is None:
            if kill:
                self.process.kill()
            else:
                self.process.terminate()
            self.process.wait(timeout=10)

    def close(self) -> None:
        self.stop()


@contextlib.contextmanager
def local_redis(directory: str | Path) -> Iterator[NativeRedis]:
    server = NativeRedis(directory)
    server.start()
    try:
        yield server
    finally:
        server.close()


def demo(db_path: str | Path, profile: str = "fixture") -> dict[str, Any]:
    if profile != "fixture":
        raise RuntimeError("Local model memory benefit evaluation needs a provisioned generator and embedder")
    principal = Principal(subject="operator", tenant_id="demo", roles=["admin"])
    with local_redis(str(db_path) + ".redis") as server:
        service = MemoryService(db_path, server.url)
        first = service.put(principal, "timeout", "Approval timeout is 15 minutes.",
            provenance=[{"source_id": "runbook", "version": "v1"}])
        session = service.start_session(principal)
        service.append_message(principal, session, "Remember the approval timeout")
        recalled = service.recall(principal, "approval timeout")
        summary = service.summarize(principal, session, [first.memory_id])
        service.delete(principal, first.memory_id, first.version)
        stale_blocked = False
        try:
            service.put(principal, first.memory_id, first.text, expected_version=first.version,
                        provenance=first.provenance)
        except MemoryConflict:
            stale_blocked = True
        invalidated = service.summary(principal, session) is None
        service.close()
        server.stop(kill=True)
        server.start()
        restarted = MemoryService(db_path, server.url)
        tombstone = restarted.get(principal, first.memory_id, include_deleted=True)
        restarted.close()
    return {"profile": profile, "real_redis": True, "real_qdrant": True, "redis_aof_restart": True,
            "recalled": len(recalled), "stale_session_blocked": stale_blocked, "summary_invalidated": invalidated,
            "deleted_after_restart": tombstone.deleted, "summary": summary,
            "model_task_success_comparison": "unverified", "embedding_profile": "fixture-feature-hash"}
