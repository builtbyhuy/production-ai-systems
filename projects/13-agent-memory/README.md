# P13 — Memory that cannot resurrect deleted facts

**Implemented. Actual Redis 8.2.1/Qdrant persistence and conflict tests verified with fixture embeddings. A bounded actual-Qwen comparison measured two synthetic fact lookups with and without memory; broader quality and efficiency benefits remain unverified.**

## Architecture

packages/pais/memory.py separates bounded Redis conversation buffers, P15 workflow checkpoints and long-term facts. SQLite owns text, confidence, provenance, versions, TTL, tombstones, summaries and a change feed. Redis caches facts and executes a real Lua version guard. Qdrant supplies candidates; a durable outbox repairs derived state.

Corrections require the expected current version. Deletion removes content/provenance and increments a persistent tombstone. A deleted ID cannot be reused even with its newest version; a newly reviewed fact needs a new ID. Redis markers survive value TTL and reject stale writes; authoritative SQLite remains protective after cache loss.

Recall validates current version, expiry, confidence and relevance. All content is explicitly untrusted. A development poison rule blocks obvious instruction patterns but is not the authorization boundary. Lossy summaries preserve IDs/versions and are invalidated by correction/deletion/expiry.

## Setup and commands

~~~bash
.venv/bin/python -m pais demo 13 --profile fixture --output artifacts/stateful/p13-fixture.json
.venv/bin/python -m pytest tests/test_memory.py -q
.venv/bin/python -m pytest projects/13-agent-memory/test_comparison.py -q
timeout --signal=TERM --kill-after=3s 115s .venv/bin/python scripts/with_local_models.py -- env PYTHONPATH=packages .venv/bin/python projects/13-agent-memory/compare_local.py --output artifacts/stateful/p13-local-comparison.json
~~~

Install redis-server on PATH or use .tools/redis-8.2.1/src/redis-server. The demo starts fresh loopback Redis with AOF/appendfsync always, writes/recalls/deletes a memory, kills/restarts Redis and rechecks its tombstone. Unix sockets were denied on the development host; TCP was actually exercised. [Evidence](../../artifacts/stateful/p13-fixture.json). The comparison additionally requires the already provisioned qwen2.5:1.5b model and native Ollama; it performs no downloads or paid calls. Its wrapper starts all services and clients in the same network namespace, then stops its owned model server.

## Acceptance checklist

- [x] Actual Redis Lua guard, TTL values/bounded buffers and Qdrant recall.
- [x] Redis AOF SIGKILL/restart; durable deletion survives.
- [x] Concurrent correction has one winner; stale synchronization cannot resurrect.
- [x] Expiry, capacity eviction, low-confidence and irrelevant exclusion.
- [x] Provenance-preserving summaries and correction/deletion invalidation.
- [x] Poison rule, tenant denial and session ownership.
- [x] Bounded actual-model task comparison with/without memory on two fixed synthetic questions.
- [x] Actual prompt/output token counts and supplied context characters for both conditions.
- [ ] Broader task-success, semantic retrieval and context-efficiency evaluation.
- [ ] Cross-host deployment load/failover.

## Case study and limitations

Five tests passed with real Redis/Qdrant. The demo recalled one supported fact, blocked stale synchronization, invalidated its summary, and preserved deletion after Redis restart. No productivity percentage is inferred.

### Actual-local comparison

The comparison driver declares its source set, questions, exact answers and scoring rule before any inference. The questions are “Cedar release phrase?” (expected amber-seven) and “Lumen service window?” (expected 06:15 UTC). Both conditions use the same questions, system instructions and qwen2.5:1.5b settings: temperature 0, seed 7, context limit 1024 and output limit 24. Calls are stateless; condition order is disabled/enabled for Cedar and enabled/disabled for Lumen. Only leading/trailing whitespace is ignored when scoring.

The memory-enabled condition uses MemoryService.recall with its actual Redis/Qdrant layers and confidence floor 0.8. It injects exactly the relevant current fact. Two conflicting facts at confidence 0.2 and an unrelated cat-care fact must be excluded before inference; a separate integration test checks this requirement. Embeddings remain deterministic feature hashes, so this does not assess learned semantic retrieval.

| Measured across two questions | Memory disabled | Memory enabled |
|---|---:|---:|
| Exact answers correct | 0/2 | 2/2 |
| Actual model responses | 2 | 2 |
| Prompt tokens reported by Ollama | 121 | 136 |
| Output tokens reported by Ollama | 4 | 10 |
| Supplied memory characters | 0 | 66 |

The disabled condition answered UNKNOWN twice; this follows its instruction to abstain without evidence. The enabled condition returned amber-seven and 06:15 UTC. All four calls completed; measured driver time was 4.43 seconds. The [comparison report](../../artifacts/stateful/p13-local-comparison.json) preserves full prompts and responses, per-call usage, source/question hash, model settings, model inventory and source manifest. It is written incrementally so partial failures remain visible.

This demonstrates exact lookup of two deliberately supplied synthetic facts. The baseline has no access to those facts. Memory added 15 prompt tokens and six output tokens in total; no token savings or general success improvement is established. The small sample, simple lexical retrieval and fixed private facts do not estimate performance on unseen tasks. Prompt-cache/load effects also prevent interpreting this one run as a latency benchmark.

Eviction orders low confidence before least recent access. Tombstone metadata is retained indefinitely; scale requires an epoch/fence-aware compaction design. Reads enforce expiry even before maintenance. Derived outages may delay recall but source-version checks preserve correctness. Summary compression is deterministic truncation, not a guarantee of semantic fidelity; follow retained references before acting.

## Interview walkthrough

Trace put → source/outbox transaction → Redis Lua/Qdrant → guarded recall. Explain why deleting only a cache key is unsafe. Race two corrections, inspect the winner, and propose compaction that does not let offline sessions revive deleted facts. Distinguish buffers, checkpoints and long-term facts.

References: [Redis transactions](https://redis.io/docs/latest/develop/interact/transactions/), [Qdrant retrieval](https://qdrant.tech/documentation/concepts/hybrid-queries/).
