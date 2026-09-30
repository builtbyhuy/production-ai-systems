"""Qdrant hybrid retrieval with authoritative SQLite versions and scoped backups."""
from __future__ import annotations

import hashlib
import json
import math
import re
import statistics
import time
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from pais.contracts import Principal, StrictModel, utcnow
from pais.db import Database
from pais.retrieval import require_read


class VectorConflict(ValueError):
    pass


class EmbeddingConfig(StrictModel):
    model: str = "fixture-feature-hash"
    revision: str = "v1"
    dimensions: int = 64
    sparse: str = "hashed-term-frequency-v1"
    metric: str = "cosine"

    def fingerprint(self) -> str:
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()


def tokens(text: str) -> list[str]:
    return re.findall(r"\w+", text.casefold())


def fixture_embedding(text: str, dimensions: int = 64) -> list[float]:
    vector = [0.0] * dimensions
    for token, count in Counter(tokens(text)).items():
        digest = hashlib.sha256(token.encode()).digest()
        index = int.from_bytes(digest[:4], "big") % dimensions
        vector[index] += (1 if digest[4] & 1 else -1) * (1 + math.log(count))
    norm = math.sqrt(sum(x * x for x in vector))
    return [x / norm for x in vector] if norm else vector


class VectorHit(StrictModel):
    document_id: str
    tenant_id: str
    version: int
    text: str
    metadata: dict[str, Any]
    score: float


class QdrantIndex:
    def __init__(
        self, db_path: str | Path, index_path: str | Path | None = None,
        *, url: str | None = None, api_key: str | None = None,
        config: EmbeddingConfig | None = None,
        embedder: Callable[[str], list[float]] | None = None,
        collection: str = "pais_v1", cache: bool = True, hnsw_m: int = 16,
    ):
        from qdrant_client import QdrantClient, models
        self.db = Database(db_path)
        self.config = config or EmbeddingConfig()
        if self.config.dimensions < 2 or self.config.dimensions > 65536:
            raise ValueError("Embedding dimensions out of range")
        if embedder is None and self.config.model != "fixture-feature-hash":
            raise RuntimeError("The configured embedding model needs an explicit provisioned embedder")
        self.embedder = embedder or (lambda text: fixture_embedding(text, self.config.dimensions))
        self.collection, self.cache_enabled, self.hnsw_m = collection, cache, hnsw_m
        self.cache_hits = self.cache_misses = 0
        self.remote = url is not None
        self.client = QdrantClient(url=url, api_key=api_key, timeout=10) if url else QdrantClient(
            path=str(index_path or str(db_path) + ".qdrant"), force_disable_check_same_thread=True)
        self.db.initialize("""
            CREATE TABLE IF NOT EXISTS vec_documents (
              tenant_id TEXT NOT NULL, document_id TEXT NOT NULL, version INTEGER NOT NULL,
              text TEXT NOT NULL, metadata TEXT NOT NULL, content_hash TEXT NOT NULL,
              deleted INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL,
              PRIMARY KEY(tenant_id,document_id));
            CREATE TABLE IF NOT EXISTS vec_embedding_cache (
              tenant_id TEXT NOT NULL, content_hash TEXT NOT NULL, config_hash TEXT NOT NULL,
              vector TEXT NOT NULL, PRIMARY KEY(tenant_id,content_hash,config_hash));
            CREATE TABLE IF NOT EXISTS vec_pending (
              tenant_id TEXT NOT NULL, document_id TEXT NOT NULL, version INTEGER NOT NULL,
              PRIMARY KEY(tenant_id,document_id));
            CREATE TABLE IF NOT EXISTS vec_index_versions (
              collection TEXT PRIMARY KEY, config_hash TEXT NOT NULL, config TEXT NOT NULL,
              status TEXT NOT NULL, created_at TEXT NOT NULL);
        """)
        with self.db.transaction() as conn:
            prior = conn.execute("SELECT config_hash FROM vec_index_versions WHERE collection=?", (collection,)).fetchone()
            if prior and prior["config_hash"] != self.config.fingerprint():
                self.client.close()
                raise VectorConflict("Embedding configuration changed; select a new collection for reindexing")
            conn.execute("INSERT OR IGNORE INTO vec_index_versions VALUES(?,?,?,'active',?)",
                         (collection, self.config.fingerprint(), self.config.model_dump_json(), utcnow()))
        if not self.client.collection_exists(collection):
            self.client.create_collection(collection,
                vectors_config={"dense": models.VectorParams(size=self.config.dimensions, distance=models.Distance.COSINE)},
                sparse_vectors_config={"sparse": models.SparseVectorParams(index=models.SparseIndexParams(on_disk=False))},
                hnsw_config=models.HnswConfigDiff(m=hnsw_m, ef_construct=100))
        if self.remote:
            self.client.create_payload_index(collection, "tenant_id", models.PayloadSchemaType.KEYWORD, wait=True)

    def close(self) -> None:
        self.client.close()

    @staticmethod
    def _point_id(tenant: str, document: str) -> str:
        return str(uuid5(NAMESPACE_URL, json.dumps([tenant, document])))

    def _dense(self, principal: Principal, text: str) -> list[float]:
        require_read(principal)
        content_hash = hashlib.sha256(text.encode()).hexdigest()
        fingerprint = self.config.fingerprint()
        if self.cache_enabled:
            with self.db.transaction(False) as conn:
                hit = conn.execute("SELECT vector FROM vec_embedding_cache WHERE tenant_id=? AND content_hash=? AND config_hash=?",
                                   (principal.tenant_id, content_hash, fingerprint)).fetchone()
            if hit:
                self.cache_hits += 1
                return json.loads(hit["vector"])
        result = [float(x) for x in self.embedder(text)]
        if len(result) != self.config.dimensions or any(not math.isfinite(x) for x in result):
            raise ValueError("Embedding output dimensions or numeric values are invalid")
        self.cache_misses += 1
        if self.cache_enabled:
            with self.db.transaction() as conn:
                conn.execute("INSERT OR IGNORE INTO vec_embedding_cache VALUES(?,?,?,?)",
                             (principal.tenant_id, content_hash, fingerprint, json.dumps(result)))
        return result

    @staticmethod
    def _sparse(text: str) -> Any:
        from qdrant_client import models
        counts: dict[int, float] = {}
        for token, count in Counter(tokens(text)).items():
            index = int.from_bytes(hashlib.sha256(token.encode()).digest()[:4], "big")
            counts[index] = counts.get(index, 0.0) + 1 + math.log(count)
        keys = sorted(counts)
        return models.SparseVector(indices=keys, values=[counts[x] for x in keys])

    @staticmethod
    def _filter(principal: Principal, metadata: dict[str, Any] | None = None) -> Any:
        require_read(principal)
        from qdrant_client import models
        clauses = [models.FieldCondition(key="tenant_id", match=models.MatchValue(value=principal.tenant_id))]
        for key, value in (metadata or {}).items():
            if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", key) or key in {"tenant_id", "document_id", "version"}:
                raise ValueError("Metadata filter key is invalid or reserved")
            if not isinstance(value, (str, int, bool)):
                raise TypeError("Metadata equality filters require scalar values")
            clauses.append(models.FieldCondition(key=f"metadata.{key}", match=models.MatchValue(value=value)))
        return models.Filter(must=clauses)

    def upsert(self, principal: Principal, document_id: str, text: str, metadata: dict[str, Any] | None = None,
               expected_version: int = 0, *, materialize: bool = True) -> int:
        principal.require("writer")
        if not document_id or not text.strip() or len(text) > 1_000_000:
            raise ValueError("Document identifier/text is missing or too large")
        metadata_json = json.dumps(metadata or {}, sort_keys=True, allow_nan=False)
        with self.db.transaction() as conn:
            prior = conn.execute("SELECT version FROM vec_documents WHERE tenant_id=? AND document_id=?",
                                 (principal.tenant_id, document_id)).fetchone()
            version = int(prior["version"]) if prior else 0
            if expected_version != version:
                raise VectorConflict("Stale document version; refresh before updating")
            version += 1
            conn.execute("INSERT INTO vec_documents VALUES(?,?,?,?,?,?,0,?) ON CONFLICT(tenant_id,document_id) "
                         "DO UPDATE SET version=excluded.version,text=excluded.text,metadata=excluded.metadata,"
                         "content_hash=excluded.content_hash,deleted=0,updated_at=excluded.updated_at",
                         (principal.tenant_id, document_id, version, text, metadata_json,
                          hashlib.sha256(text.encode()).hexdigest(), utcnow()))
            conn.execute("INSERT INTO vec_pending VALUES(?,?,?) ON CONFLICT(tenant_id,document_id) DO UPDATE SET version=excluded.version",
                         (principal.tenant_id, document_id, version))
        if materialize:
            self.materialize(principal)
        return version

    def batch_ingest(self, principal: Principal, records: list[dict[str, Any]], batch_size: int = 64) -> int:
        if not 1 <= batch_size <= 1000:
            raise ValueError("Batch size out of bounds")
        for offset in range(0, len(records), batch_size):
            for record in records[offset:offset + batch_size]:
                self.upsert(principal, record["document_id"], record["text"], record.get("metadata"),
                            record.get("expected_version", 0), materialize=False)
            self.materialize(principal, limit=batch_size)
        return len(records)

    def materialize(self, principal: Principal, limit: int = 1000) -> int:
        from qdrant_client import models
        principal.require("writer")
        with self.db.transaction(False) as conn:
            pending = conn.execute("SELECT d.* FROM vec_pending p JOIN vec_documents d USING(tenant_id,document_id) "
                                   "WHERE p.tenant_id=? ORDER BY d.document_id LIMIT ?",
                                   (principal.tenant_id, limit)).fetchall()
        done = 0
        for row in pending:
            vector = self._dense(principal, row["text"]) if not row["deleted"] else None
            with self.db.transaction() as conn:
                current = conn.execute("SELECT * FROM vec_documents WHERE tenant_id=? AND document_id=?",
                                       (principal.tenant_id, row["document_id"])).fetchone()
                if current["version"] != row["version"]:
                    continue
                point_id = self._point_id(principal.tenant_id, row["document_id"])
                if row["deleted"]:
                    self.client.delete(self.collection, models.PointIdsList(points=[point_id]), wait=True)
                else:
                    self.client.upsert(self.collection, [models.PointStruct(id=point_id,
                        vector={"dense": vector, "sparse": self._sparse(row["text"])},
                        payload={"tenant_id": principal.tenant_id, "document_id": row["document_id"],
                                 "version": row["version"], "content_hash": row["content_hash"],
                                 "metadata": json.loads(row["metadata"])} )], wait=True)
                conn.execute("DELETE FROM vec_pending WHERE tenant_id=? AND document_id=? AND version=?",
                             (principal.tenant_id, row["document_id"], row["version"]))
                done += 1
        return done

    def search(self, principal: Principal, query: str, limit: int = 5, *, metadata: dict[str, Any] | None = None,
               mode: str = "hybrid") -> list[VectorHit]:
        require_read(principal)
        from qdrant_client import models
        if not 1 <= limit <= 100 or not query.strip():
            raise ValueError("Search query and 1..100 limit are required")
        filters = self._filter(principal, metadata)
        candidate_limit = min(1000, max(20, limit * 5))
        dense = self._dense(principal, query) if mode in {"hybrid", "dense"} else None
        if mode == "hybrid":
            points = self.client.query_points(self.collection, prefetch=[
                models.Prefetch(query=dense, using="dense", filter=filters, limit=candidate_limit),
                models.Prefetch(query=self._sparse(query), using="sparse", filter=filters, limit=candidate_limit),
            ], query=models.FusionQuery(fusion=models.Fusion.RRF), query_filter=filters,
                limit=candidate_limit, with_payload=True).points
        elif mode in {"dense", "sparse"}:
            points = self.client.query_points(self.collection, query=dense if mode == "dense" else self._sparse(query),
                        using=mode, query_filter=filters, limit=candidate_limit, with_payload=True).points
        else:
            raise ValueError("Retrieval mode must be hybrid/dense/sparse")
        results = []
        with self.db.transaction(False) as conn:
            for point in points:
                payload = point.payload or {}
                if payload.get("tenant_id") != principal.tenant_id:
                    continue
                row = conn.execute("SELECT * FROM vec_documents WHERE tenant_id=? AND document_id=? AND deleted=0",
                                   (principal.tenant_id, payload.get("document_id"))).fetchone()
                if row is None or row["version"] != payload.get("version") or row["content_hash"] != payload.get("content_hash"):
                    continue  # derived indexes cannot resurrect stale/deleted source content
                current_metadata = json.loads(row["metadata"])
                if any(current_metadata.get(k) != v for k, v in (metadata or {}).items()):
                    continue
                results.append(VectorHit(document_id=row["document_id"], tenant_id=principal.tenant_id,
                    version=row["version"], text=row["text"], metadata=current_metadata, score=point.score))
                if len(results) == limit:
                    break
        return results

    def delete(self, principal: Principal, document_id: str, expected_version: int, *, materialize: bool = True) -> int:
        principal.require("writer")
        with self.db.transaction() as conn:
            row = conn.execute("SELECT * FROM vec_documents WHERE tenant_id=? AND document_id=?",
                               (principal.tenant_id, document_id)).fetchone()
            if row is None:
                raise LookupError("Document not found")
            if row["version"] != expected_version:
                raise VectorConflict("Stale document version")
            version = expected_version + 1
            conn.execute("UPDATE vec_documents SET version=?,text='',metadata='{}',content_hash='',deleted=1,updated_at=? "
                         "WHERE tenant_id=? AND document_id=?", (version, utcnow(), principal.tenant_id, document_id))
            conn.execute("DELETE FROM vec_embedding_cache WHERE tenant_id=? AND content_hash=?",
                         (principal.tenant_id, row["content_hash"]))
            conn.execute("INSERT INTO vec_pending VALUES(?,?,?) ON CONFLICT(tenant_id,document_id) DO UPDATE SET version=excluded.version",
                         (principal.tenant_id, document_id, version))
        if materialize:
            self.materialize(principal)
        return version

    def backup(self, principal: Principal) -> bytes:
        principal.require("admin")
        self.materialize(principal)
        with self.db.transaction() as conn:
            if conn.execute("SELECT count(*) FROM vec_pending WHERE tenant_id=?", (principal.tenant_id,)).fetchone()[0]:
                raise VectorConflict("Pending source changes must be materialized before backup")
            points, cursor = [], None
            while True:
                batch, cursor = self.client.scroll(self.collection, scroll_filter=self._filter(principal),
                    limit=100, offset=cursor, with_payload=True, with_vectors=True)
                points.extend(point.model_dump(mode="json") for point in batch)
                if cursor is None:
                    break
            documents = [dict(row) for row in conn.execute("SELECT * FROM vec_documents WHERE tenant_id=? ORDER BY document_id",
                                                         (principal.tenant_id,)).fetchall()]
        body = {"format": "pais-qdrant-portable-v1", "tenant_id": principal.tenant_id,
                "config": self.config.model_dump(), "documents": documents, "points": points}
        serialized = json.dumps(body, sort_keys=True, allow_nan=False)
        return json.dumps({"sha256": hashlib.sha256(serialized.encode()).hexdigest(), "body": body}, sort_keys=True).encode()

    def restore(self, principal: Principal, snapshot: bytes) -> dict[str, int]:
        from qdrant_client import models
        principal.require("admin")
        if len(snapshot) > 100_000_000:
            raise ValueError("Snapshot exceeds portable restore limit")
        envelope = json.loads(snapshot)
        body = envelope["body"]
        if hashlib.sha256(json.dumps(body, sort_keys=True, allow_nan=False).encode()).hexdigest() != envelope["sha256"]:
            raise ValueError("Snapshot checksum mismatch")
        if body["format"] != "pais-qdrant-portable-v1" or body["tenant_id"] != principal.tenant_id:
            raise PermissionError("Snapshot format/tenant is not authorized")
        if EmbeddingConfig.model_validate(body["config"]) != self.config:
            raise VectorConflict("Snapshot embedding configuration mismatch")
        documents = {row["document_id"]: row for row in body["documents"]}
        if any(row["tenant_id"] != principal.tenant_id for row in documents.values()):
            raise PermissionError("Snapshot contains another tenant")
        for point in body["points"]:
            payload = point["payload"]
            document = documents.get(payload["document_id"])
            if payload["tenant_id"] != principal.tenant_id or point["id"] != self._point_id(principal.tenant_id, payload["document_id"]):
                raise PermissionError("Snapshot point identity mismatch")
            if document is None or document["deleted"] or payload["version"] != document["version"] or payload["content_hash"] != hashlib.sha256(document["text"].encode()).hexdigest() or payload["content_hash"] != document["content_hash"] or payload["metadata"] != json.loads(document["metadata"]):
                raise ValueError("Snapshot vectors do not match authoritative documents")
        live = {key for key, row in documents.items() if not row["deleted"]}
        if live != {point["payload"]["document_id"] for point in body["points"]}:
            raise ValueError("Snapshot is missing active vectors")
        with self.db.transaction() as conn:
            count = conn.execute("SELECT count(*) FROM vec_documents WHERE tenant_id=?", (principal.tenant_id,)).fetchone()[0]
            if count:
                raise VectorConflict("Restore requires a fresh destination tenant")
            for row in documents.values():
                conn.execute("INSERT INTO vec_documents VALUES(?,?,?,?,?,?,?,?)", tuple(row[key] for key in
                    ("tenant_id", "document_id", "version", "text", "metadata", "content_hash", "deleted", "updated_at")))
            if body["points"]:
                self.client.upsert(self.collection, [models.PointStruct(id=p["id"], vector=p["vector"], payload=p["payload"]) for p in body["points"]], wait=True)
        return {"documents": len(documents), "vectors": len(body["points"])}

    def reindex(self, principal: Principal, collection: str) -> dict[str, Any]:
        """Versioned derived-index rebuild. Caller switches only after conformance checks."""
        from qdrant_client import models
        principal.require("admin")
        if collection == self.collection or self.client.collection_exists(collection):
            raise VectorConflict("A fresh collection name is required")
        self.client.create_collection(collection,
            vectors_config={"dense": models.VectorParams(size=self.config.dimensions, distance=models.Distance.COSINE)},
            sparse_vectors_config={"sparse": models.SparseVectorParams()},
            hnsw_config=models.HnswConfigDiff(m=self.hnsw_m, ef_construct=100))
        with self.db.transaction() as conn:
            conn.execute("INSERT INTO vec_index_versions VALUES(?,?,?,'building',?)",
                         (collection, self.config.fingerprint(), self.config.model_dump_json(), utcnow()))
        old = self.collection
        self.collection = collection
        try:
            with self.db.transaction() as conn:
                conn.execute("INSERT OR REPLACE INTO vec_pending SELECT tenant_id,document_id,version FROM vec_documents WHERE tenant_id=?",
                             (principal.tenant_id,))
            count = 0
            while True:
                batch = self.materialize(principal)
                count += batch
                if batch == 0:
                    break
            with self.db.transaction() as conn:
                conn.execute("UPDATE vec_index_versions SET status='ready' WHERE collection=?", (collection,))
            return {"source_collection": old, "new_collection": collection, "documents": count,
                    "automatic_cutover": False}
        finally:
            self.collection = old


def corpus(size: int, tenant_marker: str = "a") -> list[dict[str, Any]]:
    return [{"document_id": f"doc-{i}", "text": f"Procedure {tenant_marker}_code_{i} concerns {'approval' if i % 2 else 'backup'} recovery. Exact procedure identifier is {tenant_marker}_code_{i}.",
             "metadata": {"category": "approval" if i % 2 else "backup", "ordinal": i}}
            for i in range(size)]


def benchmark(index: QdrantIndex, principal: Principal, size: int = 200) -> dict[str, Any]:
    if not 10 <= size <= 100000:
        raise ValueError("Benchmark size must be 10..100000")
    records = corpus(size)
    started = time.perf_counter()
    index.batch_ingest(principal, records)
    ingest = time.perf_counter() - started
    result: dict[str, Any] = {"size": size, "ingest_seconds": ingest, "documents_per_second": size / ingest,
        "embedding_model": index.config.model, "qdrant_runtime": "remote-server" if index.remote else "client-local-exact-search",
        "hnsw_performance_verified": False, "remote_server_exercised": index.remote,
        "corpus_sha256": hashlib.sha256(json.dumps(records, sort_keys=True).encode()).hexdigest(),
        "larger_profiles_executed": False, "modes": {}}
    for mode in ("dense", "sparse", "hybrid"):
        times, correct = [], 0
        for i in range(min(size, 100)):
            began = time.perf_counter()
            hits = index.search(principal, f"a_code_{i}", mode=mode, limit=1)
            times.append((time.perf_counter() - began) * 1000)
            correct += bool(hits and hits[0].document_id == f"doc-{i}")
        ordered = sorted(times)
        result["modes"][mode] = {"recall_at_1": correct / len(times), "queries": len(times),
            "p50_ms": statistics.median(times), "p95_ms": ordered[int((len(times)-1)*0.95)],
            "p99_ms": ordered[int((len(times)-1)*0.99)]}
    result["cache_hits"], result["cache_misses"] = index.cache_hits, index.cache_misses
    return result


def demo(db_path: str | Path, profile: str = "fixture") -> dict[str, Any]:
    if profile != "fixture":
        raise RuntimeError("Local semantic benchmark needs an explicit local embedding adapter; deployment requires a Qdrant server")
    principal = Principal(subject="operator", tenant_id="demo", roles=["admin"])
    index = QdrantIndex(db_path)
    try:
        result = benchmark(index, principal, size=100)
        snapshot = index.backup(principal)
    finally:
        index.close()
    restored = QdrantIndex(str(db_path) + ".restored")
    try:
        result["restored"] = restored.restore(principal, snapshot)
        result["restore_query"] = restored.search(principal, "a_code_42", limit=1)[0].document_id
    finally:
        restored.close()
    return {"profile": profile, "real_qdrant_client": True, "fixture_embeddings": True, **result}
