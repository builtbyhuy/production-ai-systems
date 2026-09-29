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
- [x] Actual 1k/10k local datasets with worker RSS and live-store disk measurements.
- [ ] 100k dataset, concurrent server load and server disaster recovery.

## Case study and limitations

The exploratory exact-identifier fixture achieved recall@1 0.71 for feature-hash dense search and 1.00 for sparse/hybrid. Hybrid p95 was about 5.3 ms in that run; the evidence records the captured rerun. These are small synthetic/client-local measurements, not semantic or production-performance claims. Five conformance tests passed.

Local mode performs exact search and does not exercise server HNSW. Changing m locally is not an HNSW performance comparison. Reindex leaves cutover explicit; concurrent writes after building require rematerialization before switching. The 100k generator target and server/concurrent profiles remain unexecuted.

## Measured local scale limit

An evidence-only driver reused the frozen benchmark at clean commit
`c7b8a793f34795f3d2de148c1c5c211845e8b222`. Each size ran 100 identical identifier queries
in each of three modes, for 300 actual query invocations. The larger results exposed a
quality limitation rather than establishing readiness for deployment.

| Measurement | 1,000 documents | 10,000 documents |
|---|---:|---:|
| Dense recall@1 | 0.12 | 0.01 |
| Sparse recall@1 | 1.00 | 1.00 |
| Hybrid recall@1 | 1.00 | 0.21 |
| Hybrid p95 | 31.45 ms | 317.93 ms |
| Worker elapsed time | 7.13 s | 57.73 s |
| Worker peak RSS | 99,213,312 bytes | 143,163,392 bytes |
| Logical disk, store open | 2,646,697 bytes | 25,207,465 bytes |

These are Qdrant client local exact-search measurements with 64-dimensional feature hashes.
Sparse retrieval fits the identifier workload; dense collisions and the fixed candidate/fusion
settings limit the observed hybrid result. Semantic embeddings and HNSW were not exercised.
The parent controller could not see child `/proc/PID/status`, so its live RSS/thread guard
was unavailable. Worker kernel high-water RSS is valid. A separate short reopened-store
probe observed one thread; it is not a full benchmark thread time series. No process exceeded
the declared memory threshold in the recorded worker measurements.

The complete [scale report](../../artifacts/p12-scale/scale-report.json) contains provenance,
configuration, exact document counts and caveats. The old static
`larger_profiles_executed=False` field inside the frozen helper is superseded for these two
sizes by the independently counted store contents. Predeclare a target before comparing
larger candidate pools, different fusion weights or a semantic embedder on this same corpus.

## Interview walkthrough

Reproduce an update with materialize=False, observe suppression, then recover. Explain why correct tenant filtering still needs current-version validation. Corrupt a backup and show rejection. Distinguish sparse exact identifiers, semantic embeddings, portable restore and cluster disaster recovery.

References: [hybrid queries](https://qdrant.tech/documentation/concepts/hybrid-queries/), [snapshots](https://qdrant.tech/documentation/concepts/snapshots/).
