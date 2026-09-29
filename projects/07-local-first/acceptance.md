# P07 acceptance

| Criterion | Status | Evidence or executable gate |
|---|---|---|
| Default SQLite and selectable, separately implemented LanceDB | Implemented | `packages/pais/retrieval.py`; shared adapter tests use real dependencies |
| CRUD, persistence, prefilter authorization, unsafe-filter strings | Pass, both real stores with fixture embeddings | `tests/test_retrieval_adapters.py` |
| PDF version lifecycle and interrupted derived-index recovery | Pass, both real stores with fixture models | `tests/test_rag_service.py` |
| Actual local generation, embeddings, CrossEncoder, SQLite | Pass | [P01 local13/13 report](../01-rag-citations/evidence/local-sqlite-selection-v2.json) |
| Actual local generation with LanceDB | Pass, 13/13 | [offline local LanceDB](evidence/offline-local-lancedb.json) |
| Verified external-IP-disabled, proxy-free local stack | Pass, declared trusted application profile with both stores | [SQLite](evidence/offline-local-sqlite.json), [LanceDB](evidence/offline-local-lancedb.json); kernel boundary checked before and after |
| Model/runtime and index disk consumption | Measured native local SQLite stack and both selected stores | [Corrected resource run](evidence/offline-local-sqlite-resources.json); 1,865,792 KiB aggregate app/Ollama RSS, 623,516 KiB application high-water RSS |
| Native health/seed/teardown | Implemented, exercised by root model wrapper | `scripts/with_local_models.py`, `create_demo_pdf`, model-lock checks |
| Docker Compose clean setup, volumes, limits and internal-network execution | Prepared; container execution not run here | `compose.yaml`, `compose.offline.yaml`, root API Dockerfile; Docker runtime unavailable |

Both storage implementations run in the shared tests without silent optional skips.
The core RAG/model/adapter command passed **74 tests**. The final focused command passed
**81 tests in 2.66 seconds**, including seven additional checks for the container launcher's
trusted credentials and offline-boundary revocation; its recorded result is
[contract-tests.json](evidence/contract-tests.json). Dependency absence
should fail the selected adapter profile visibly rather than removing it from the matrix.

## Evidence interpretation

`fixture-lancedb-demo.json` proves that real LanceDB storage and the application contract work
together; its embeddings/reranking/generation are deliberately fixtures. The two offline
reports separately prove actual local inference with each store under the declared boundary.

The offline runner records only environment-variable names when removing proxies, never
their values. It captures the Linux network namespace ID, interfaces/routes, two direct
external-connection failures and a second boundary check after execution. It samples the
native process tree's resident memory; shared pages can be counted twice, so the metric is
explicitly aggregate RSS rather than a claim of unique physical memory.

The initial watcher incorrectly treated a namespace PID as a host `/proc` PID. Its tiny
aggregate RSS values were invalid. Those observations remain recorded with a correction;
`native_stack_peak_rss_kib` is null in the initial reports. The valid application self-RSS
and all offline/model/lifecycle checks remain intact. A fixed watcher maps direct child
`PPid` plus `NSpid`; it was verified against a real child/grandchild allocation before rerunning.

The [corrected SQLite resource run](evidence/offline-local-sqlite-resources.json) passed
13/13 checks in **25.579 seconds**. Its 100 ms process-tree samples reached **1,865,792 KiB
(1.78 GiB)** across the app, Ollama server and their children. The application self-reported
**623,516 KiB** high-water RSS. This is one CPU-machine observation, not a load test, minimum
memory specification or measurement of unique physical memory.

The entire provisioned `models/` directory occupied **4,132,420,551 bytes (3.85 GiB)**;
other projects' models are included. After the small lifecycle demo, selected application
and index storage occupied **1,769,472 bytes** for SQLite and **143,293 bytes** for LanceDB.
Those figures include schema/allocation overhead and different storage formats, so they do
not establish a general space-efficiency ranking. Teardown removed the temporary demo stores.
