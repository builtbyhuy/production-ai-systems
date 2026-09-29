# P12 — Qdrant retrieval, consistency and restoration

**Implemented. Real Qdrant client local mode and restore conformance verified with fixture embeddings. Server HNSW/load and semantic quality are unverified.**

## Architecture

packages/pais/vectors.py keeps SQLite documents authoritative and Qdrant indexes derived. Documents carry tenant, version, content hash, metadata and tombstone state. Writes persist materialization work. Queries apply Qdrant tenant filters and recheck current source versions/hashes. Stale vectors can reduce recall until recovery but cannot revive deleted content.

Named vectors combine cosine dense search and hashed term-frequency sparse search through reciprocal-rank fusion. Dense defaults to an explicitly disclosed 64-dimensional feature-hash fixture. A real embedder needs a model/revision/dimension configuration. Embedding caches include tenant, content hash and configuration.

Portable snapshots contain actual vectors/payloads plus authoritative documents. Restore checks checksum, scope, dimensions/configuration, hashes, versions, metadata and completeness in a fresh destination. This is a tenant-scoped portable restore, not native server failover evidence.

## Setup and verification

~~~bash
.venv/bin/python -m pais demo 12 --profile fixture --output artifacts/stateful/p12-fixture.json
.venv/bin/python -m pytest tests/test_vectors.py -q
~~~

Qdrant client 1.19.1 local mode needs no Docker/server. Remote mode accepts a server URL/key and an injected real embedding adapter; it creates a tenant payload index. [Evidence](../../artifacts/stateful/p12-fixture.json).

## Acceptance checklist

- [x] Actual dense/sparse/hybrid queries with tenant/metadata filters.
- [x] Batch ingestion, scoped embedding cache, optimistic versions.
- [x] Update/delete crash windows; stale results suppressed and repaired.
- [x] Fresh-collection reindex without implicit cutover.
- [x] Restore into a fresh instance verifies vectors, documents, metadata and tenant boundary.
- [x] Reproducible 100-document/300-query initial comparison.
- [ ] Real semantic embeddings and server HNSW/configuration/load experiments.
- [ ] 10k/100k datasets, RAM/disk/concurrency comparison and server disaster recovery.

## Case study and limitations

The exploratory exact-identifier fixture achieved recall@1 0.71 for feature-hash dense search and 1.00 for sparse/hybrid. Hybrid p95 was about 5.3 ms in that run; the evidence records the captured rerun. These are small synthetic/client-local measurements, not semantic or production-performance claims. Five conformance tests passed.

Local mode performs exact search and does not exercise server HNSW. Changing m locally is not an HNSW performance comparison. Reindex leaves cutover explicit; concurrent writes after building require rematerialization before switching. Larger generator targets remain unexecuted.

## Interview walkthrough

Reproduce an update with materialize=False, observe suppression, then recover. Explain why correct tenant filtering still needs current-version validation. Corrupt a backup and show rejection. Distinguish sparse exact identifiers, semantic embeddings, portable restore and cluster disaster recovery.

References: [hybrid queries](https://qdrant.tech/documentation/concepts/hybrid-queries/), [snapshots](https://qdrant.tech/documentation/concepts/snapshots/).
