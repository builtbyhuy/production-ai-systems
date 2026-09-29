# Current state

All 18 workstreams exist; final integration is ongoing. Specification: docs/BUILD_SPEC.md.
Linux x86_64, Python 3.12.14, Node 24.19; 8 GiB RAM and 8 CPU quota.
Git is local only; no commits yet while owners finish. GitHub builtbyhuy/production-ai-systems
returned 404 and the plugin has no repository-create operation. Final delivery is pending.

Verified vertical slice: local PDF → Guardrails → Ollama/CrossEncoder → SSE/Next/AI SDK →
original page citation browser 1/1. Fixture desktop/mobile 14/14, API 20/20, API demo 15/15.
P01 real local 13/13; 16-query retrieval recall: lexical .9375, dense/hybrid/rerank 1.0.
Reranking did not improve ranking quality on this corpus and added latency.
P07 offline SQLite/Lance 13/13 in loopback-only namespace with proxies removed and negative
IPv4/IPv6 probes. Corrected sampled app+Ollama sum-RSS 1,865,792 KiB; app 623,516 KiB.

P04 frozen fixture 144/144; baselines 120/144 and 143/144 are preserved.
First actual local release is 132/144 (12 summary completeness failures), no errors/skips.
Fix: explicit summaries now use disclosed page-balanced extractive assembly; ordinary QA
still uses actual Qwen selection. Final clean-commit 144-case rerun is required.
Degraded fixture returned 1. Required DeepEval/RAGAS metrics execute in an isolated environment.

P02 actual LiteLLM 12 cases/policy: cheap 4/12, expensive 6/12, routed 4/12; local-zero prices,
no measured dollar savings. Concurrent budget admits 3/24; unknown cancellation holds persist.
P06 actual Guardrails 3 tests; injection TP5/FN2/FP1/TN4; HTTP 24 concurrent → 3 admit/21 real429.
P05 native binaries SHA-verified; actual alerts, worker trace, dashboard and ledger observed.
The 1 GiB cap failed during Chromium at 1.075 GiB; explicit 1536 MiB rerun is in progress.
P15 approval/replay tests pass. P16 Redis AOF/Celery crash recovery passes with one visible effect.
P13 Redis/Qdrant restart, corrections, tombstones and stale-session rejection pass.
P03 actual CrewAI fixture passes; local Qwen attempt failed after70.02s, one response, zero tools.
P10 local/SDK tests pass; real Supabase/Stripe accounts unavailable. P12 real Qdrant local
100 docs/300 queries/fresh restore; HNSW/server-scale profiles remain unexecuted.
P09 genuine tiny 3-step SFT and DPO; exact reloads; all held-out exact matches 0%, retention rejected.
P17 original 100 tasks/325 checks/reference QA; no untrusted scores or leaderboard rows.
P18 patch prepared: baseline 3 fail/1 pass, patched 13 pass; no upstream submission or approval.
P11 flags/manifests/CI exist; no container/cluster/deployment drill. P14 actual CLI passed, but
server failed before readiness on AF_UNIX/ZeroMQ denial; zero generation calls, clean shutdown.

All project owners frozen; read-only document audit completed with all18 guides and no broken
relative links at its snapshot. Evaluator upgrade adopted: DeepEval4.2.6/RAGAS0.4.3 with
Community0.3.31 and modern LangChain;432/432 metrics equal in fresh .venv-final. Use
PAIS_EVAL_PYTHON=$PWD/projects/04-eval-harness/.venv-final/bin/python in this checkout.
Root owns final integration, ledger and commits. Fresh .venv-verified from frozen lock:
262 integrated tests passed,2upstream warnings. Core164packages and npm production report0
advisories. Isolated eval/security/research/training/inference runtimes have reported advisories;
whole-repo production supply-chain acceptance remains blocked (docs/dependencies/AUDIT.md).
P05 accepted native drill PASS155.37s,RSS1,448,546,304bytes<1536MiB;8/12panels captured.
Accepted immutable evidence is artifacts/p05-native-first-pass/report.json (canonical output
was overwritten by interrupted visual work); reviewed copy artifacts/reports/p05-native-accepted.json. P13 two-fact real-model comparison0/2without vs2/2with
memory; prompttokens121/136,output4/10,4.43s. No general uplift/token savings claim.

CPU slot free for root final release/degraded/audit suites.
No GPU, Docker, Kubernetes, connected keys or established untrusted-code sandbox; execution disabled.
Next: commit; capture tests against clean commit;
package source and selected evidence, persist final ZIP/report, deliver the 18-project matrix.
