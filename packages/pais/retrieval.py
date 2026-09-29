"""Tenant-filtered, interchangeable real sqlite-vec and LanceDB vector adapters.

SQLite is application authority. LanceDB is a derived local index. RAGService serializes
its replacement/checkpoint protocol with SQLite's write lock; direct LanceDB bulk
replacement alone is not a cross-store transaction.
"""
from __future__ import annotations

import math
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from pais.contracts import Principal
from pais.db import Database
from pais.models import MissingPrerequisite, validate_vectors


def require_read(principal: Principal) -> None:
    if not principal.subject or not principal.tenant_id:
        raise PermissionError("Trusted subject and tenant identity are required")
    if not {"reader", "editor", "admin"}.intersection(principal.roles):
        raise PermissionError("Reader role required")


def require_write(principal: Principal) -> None:
    require_read(principal)
    if not {"editor", "admin"}.intersection(principal.roles):
        raise PermissionError("Editor role required")


@dataclass(frozen=True)
class VectorRecord:
    chunk_id: str
    tenant_id: str
    vector: list[float]


@dataclass(frozen=True)
class VectorMatch:
    chunk_id: str
    distance: float


class VectorAdapter(Protocol):
    name: str
    dimension: int

    def upsert(self, principal: Principal, records: list[VectorRecord], *,
               connection: sqlite3.Connection | None = None) -> None: ...
    def replace(self, principal: Principal, records: list[VectorRecord], *,
                connection: sqlite3.Connection | None = None) -> None: ...
    def delete(self, principal: Principal, chunk_ids: list[str] | None = None, *,
               connection: sqlite3.Connection | None = None) -> None: ...
    def search(self, principal: Principal, vector: list[float], limit: int = 5, *,
               connection: sqlite3.Connection | None = None) -> list[VectorMatch]: ...
    def count(self, principal: Principal, *,
              connection: sqlite3.Connection | None = None) -> int: ...


def _validated(principal: Principal, records: list[VectorRecord], dimension: int) -> list[VectorRecord]:
    require_write(principal)
    if any(record.tenant_id != principal.tenant_id for record in records):
        raise PermissionError("Cannot index another tenant's vectors")
    if any(not record.chunk_id for record in records):
        raise ValueError("Vector IDs cannot be empty")
    if len({record.chunk_id for record in records}) != len(records):
        raise ValueError("Duplicate vector IDs in one batch")
    vectors = validate_vectors([record.vector for record in records], len(records), dimension)
    return [VectorRecord(r.chunk_id, r.tenant_id, vector) for r, vector in zip(records, vectors)]


class SQLiteVecAdapter:
    name = "sqlite"

    def __init__(self, db: Database | str | Path, dimension: int):
        self.db = db if isinstance(db, Database) else Database(db)
        if not 1 <= dimension <= 8192:
            raise ValueError("Invalid embedding dimension")
        self.dimension = dimension
        try:
            import sqlite_vec
        except ImportError as exc:
            raise MissingPrerequisite("sqlite-vec is required; run uv sync --group dev") from exc
        self.extension = sqlite_vec
        with self._connection(write=True) as connection:
            connection.execute(
                f"CREATE VIRTUAL TABLE IF NOT EXISTS rag_vectors_v1 USING vec0("
                f"chunk_id TEXT PRIMARY KEY, tenant_id TEXT, "
                f"embedding FLOAT[{dimension}] distance_metric=cosine)"
            )
            # An incompatible existing table must fail at construction, not mid-query.
            definition = connection.execute(
                "SELECT sql FROM sqlite_master WHERE name='rag_vectors_v1'"
            ).fetchone()[0]
            if f"FLOAT[{dimension}]" not in definition:
                raise ValueError("sqlite-vec schema dimension differs; rebuild a new index database")

    def _load(self, connection: sqlite3.Connection) -> None:
        try:
            connection.enable_load_extension(True)
            self.extension.load(connection)
        except (AttributeError, sqlite3.Error) as exc:
            raise MissingPrerequisite(f"SQLite extension loading is unavailable: {exc}") from exc
        finally:
            if hasattr(connection, "enable_load_extension"):
                connection.enable_load_extension(False)

    @contextmanager
    def _connection(self, connection: sqlite3.Connection | None = None, *,
                    write: bool = False) -> Iterator[sqlite3.Connection]:
        if connection is not None:
            self._load(connection)
            yield connection
        else:
            with self.db.transaction(immediate=write) as own:
                self._load(own)
                yield own

    def upsert(self, principal: Principal, records: list[VectorRecord], *,
               connection: sqlite3.Connection | None = None) -> None:
        records = _validated(principal, records, self.dimension)
        with self._connection(connection, write=True) as conn:
            for record in records:
                owner = conn.execute(
                    "SELECT tenant_id FROM rag_vectors_v1 WHERE chunk_id=?", (record.chunk_id,)
                ).fetchone()
                if owner and owner[0] != principal.tenant_id:
                    raise PermissionError("Vector ID is unavailable")
                conn.execute("DELETE FROM rag_vectors_v1 WHERE chunk_id=? AND tenant_id=?",
                             (record.chunk_id, principal.tenant_id))
                conn.execute("INSERT INTO rag_vectors_v1(chunk_id,tenant_id,embedding) VALUES(?,?,?)",
                             (record.chunk_id, principal.tenant_id,
                              self.extension.serialize_float32(record.vector)))

    def replace(self, principal: Principal, records: list[VectorRecord], *,
                connection: sqlite3.Connection | None = None) -> None:
        records = _validated(principal, records, self.dimension)
        with self._connection(connection, write=True) as conn:
            self.delete(principal, connection=conn)
            self.upsert(principal, records, connection=conn)

    def delete(self, principal: Principal, chunk_ids: list[str] | None = None, *,
               connection: sqlite3.Connection | None = None) -> None:
        require_write(principal)
        with self._connection(connection, write=True) as conn:
            if chunk_ids is None:
                conn.execute("DELETE FROM rag_vectors_v1 WHERE tenant_id=?", (principal.tenant_id,))
            else:
                conn.executemany("DELETE FROM rag_vectors_v1 WHERE tenant_id=? AND chunk_id=?",
                                 [(principal.tenant_id, key) for key in chunk_ids])

    def search(self, principal: Principal, vector: list[float], limit: int = 5, *,
               connection: sqlite3.Connection | None = None) -> list[VectorMatch]:
        require_read(principal)
        if not 1 <= limit <= 200:
            raise ValueError("Retrieval limit must be between 1 and 200")
        query = validate_vectors([vector], 1, self.dimension)[0]
        with self._connection(connection) as conn:
            rows = conn.execute(
                "SELECT chunk_id,distance FROM rag_vectors_v1 "
                "WHERE embedding MATCH ? AND k=? AND tenant_id=? ORDER BY distance",
                (self.extension.serialize_float32(query), limit, principal.tenant_id),
            ).fetchall()
        return [VectorMatch(row["chunk_id"], float(row["distance"])) for row in rows]

    def count(self, principal: Principal, *, connection: sqlite3.Connection | None = None) -> int:
        require_read(principal)
        with self._connection(connection) as conn:
            return conn.execute("SELECT count(*) FROM rag_vectors_v1 WHERE tenant_id=?",
                                (principal.tenant_id,)).fetchone()[0]


def _literal(value: str) -> str:
    """Lance filter SQL has no bind parameters; quote data as a string literal only."""
    if "\x00" in value:
        raise ValueError("NUL is not permitted in a filter value")
    return "'" + value.replace("'", "''") + "'"


class LanceDBAdapter:
    name = "lancedb"

    def __init__(self, path: str | Path, dimension: int):
        if not 1 <= dimension <= 8192:
            raise ValueError("Invalid embedding dimension")
        if "://" in str(path):
            raise ValueError("LanceDB local profile requires a filesystem path")
        self.dimension = dimension
        try:
            import lancedb
            import pyarrow as pa
        except ImportError as exc:
            raise MissingPrerequisite("LanceDB adapter requires lancedb and pyarrow") from exc
        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=True)
        self.db = lancedb.connect(str(self.path))
        self.table_name = f"rag_vectors_v1_d{dimension}"
        schema = pa.schema([
            pa.field("chunk_id", pa.string()), pa.field("tenant_id", pa.string()),
            pa.field("vector", pa.list_(pa.float32(), dimension)),
        ])
        self.table = self.db.create_table(self.table_name, schema=schema, exist_ok=True)
        if not self.table.schema.equals(schema):
            raise ValueError("Incompatible LanceDB schema; rebuild the derived index")

    def upsert(self, principal: Principal, records: list[VectorRecord], *,
               connection: sqlite3.Connection | None = None) -> None:
        records = _validated(principal, records, self.dimension)
        if not records:
            return
        for record in records:
            owners = self.table.search().where(
                f"chunk_id = {_literal(record.chunk_id)}"
            ).select(["tenant_id"]).limit(2).to_list()
            if any(owner["tenant_id"] != principal.tenant_id for owner in owners):
                raise PermissionError("Vector ID is unavailable")
        self.delete(principal, [record.chunk_id for record in records])
        self.table.add([{"chunk_id": record.chunk_id, "tenant_id": record.tenant_id,
                         "vector": record.vector} for record in records])

    def replace(self, principal: Principal, records: list[VectorRecord], *,
                connection: sqlite3.Connection | None = None) -> None:
        records = _validated(principal, records, self.dimension)
        self.delete(principal)
        self.upsert(principal, records)

    def delete(self, principal: Principal, chunk_ids: list[str] | None = None, *,
               connection: sqlite3.Connection | None = None) -> None:
        require_write(principal)
        predicate = f"tenant_id = {_literal(principal.tenant_id)}"
        if chunk_ids is not None:
            if not chunk_ids:
                return
            predicate += " AND chunk_id IN (" + ",".join(_literal(key) for key in chunk_ids) + ")"
        self.table.delete(predicate)

    def search(self, principal: Principal, vector: list[float], limit: int = 5, *,
               connection: sqlite3.Connection | None = None) -> list[VectorMatch]:
        require_read(principal)
        if not 1 <= limit <= 200:
            raise ValueError("Retrieval limit must be between 1 and 200")
        query = validate_vectors([vector], 1, self.dimension)[0]
        if not self.count(principal):
            return []
        rows = (self.table.search(query).distance_type("cosine")
                .where(f"tenant_id = {_literal(principal.tenant_id)}", prefilter=True)
                .select(["chunk_id", "tenant_id"]).limit(limit).to_list())
        if any(row["tenant_id"] != principal.tenant_id for row in rows):
            raise PermissionError("Vector adapter returned an unauthorized tenant")
        matches = [VectorMatch(row["chunk_id"], float(row["_distance"])) for row in rows]
        if any(not math.isfinite(match.distance) for match in matches):
            raise ValueError("LanceDB returned a non-finite distance")
        return matches

    def count(self, principal: Principal, *, connection: sqlite3.Connection | None = None) -> int:
        require_read(principal)
        return self.table.count_rows(f"tenant_id = {_literal(principal.tenant_id)}")


def get_adapter(backend: str, db: Database, dimension: int) -> VectorAdapter:
    if backend == "sqlite":
        return SQLiteVecAdapter(db, dimension)
    if backend == "lancedb":
        return LanceDBAdapter(db.path + ".lancedb", dimension)
    raise ValueError("Unknown retrieval backend; choose sqlite or lancedb")


def reciprocal_rank_fusion(rankings: list[list[str]], *, k: int = 60) -> list[tuple[str, float]]:
    """Unweighted RRF: sum 1/(k + one-based rank); sort ties by stable chunk ID."""
    if k < 1:
        raise ValueError("RRF k must be positive")
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, key in enumerate(dict.fromkeys(ranking), start=1):
            scores[key] = scores.get(key, 0.0) + 1 / (k + rank)
    return sorted(scores.items(), key=lambda pair: (-pair[1], pair[0]))


def demo(profile: str = "fixture", backend: str = "sqlite") -> dict:
    """P07 end-to-end demo; local requires real locked model dependencies."""
    from pais.rag import demo as rag_demo

    started = time.perf_counter()
    result = rag_demo(profile=profile, backend=backend)
    result["project"] = "P07"
    result["elapsed_ms"] = (time.perf_counter() - started) * 1000
    result["offline_network_isolation_verified"] = False
    result["offline_verification_note"] = (
        "A local endpoint and disabled model downloads do not prove network isolation. "
        "Use the P07 externally blocked network acceptance runner."
    )
    return result
