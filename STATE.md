# Current state

All 18 implementation tracks and individual fixture entrypoints exist. Available-host
verification is complete; the full portfolio remains incomplete for production acceptance.
Specification: docs/BUILD_SPEC.md. Detailed status: docs/PROJECT_LEDGER.md and VERIFICATION.md.

## Source and evidence identity

- Full application tests/gates: clean c7b8a793f34795f3d2de148c1c5c211845e8b222.
- P09 isolated CLI dependency fix/smoke: clean9f8e0fdf41f3a170004c297c24b18ab01da7f25b.
- Later changes are documentation/evidence only. Read git log for the delivery head;
  do not relabel historical results or promote a new commit using an older report.
- No external Git remote, GitHub publication, hosting or upstream submission was performed.
  Connector lookup for builtbyhuy/production-ai-systems returned404; it has no create operation.

## Final measured results

- 262 core tests;5 CrewAI library tests;3 Guardrails library tests;18 fixture demo entrypoints.
- P04 positive144/144, degraded96pass/48fail, zero errors/skips, audit8/8. Positive P11
  report binding accepted; degraded rejected. Scope is synthetic local regression only.
- P08 fixture browser14/14 and actual desktop1/1. First checked display14785ms; providerTTFT null.
- P01/P07 actual local lifecycle13/13, both SQLite/Lance offline adapters; reranking added
  latency without ranking benefit in the16-query comparison.
- P05 accepted native drill155.37s,RSS1,448,546,304bytes; two alert pairs, distributed trace,
  ledger/metric40 simulated microUSD;8 of12 Grafana panels rendered in the screenshot.
  Authoritative artifacts/p05-native-first-pass/report.json; canonical p05-native is unaccepted.
- P02 actual cheap/expensive/routed4/12,6/12,4/12; no paid savings. P03 local attempt timed out.
- P12 actual1k/10k Qdrant-local stores; hybrid recall1.0/.21,p9531.45/317.93ms. Parent RSS
  sampler unavailable; valid worker kernel peaks and a separate resource probe are recorded.
- P09 genuine3-step SFT+3-step DPO and exact reloads; all held-out exact matches0%, gate rejected.
- P13 two-fact memory comparison0/2 vs2/2 with higher tokens. P15/P16 durable local replay
  preserves one visible effect; actual Redis/Celery death/restart verified atc7b8.
- P17 corpus100 tasks/325 checks; zero actual untrusted baseline scores or leaderboard rows.
- P18 baseline3fail/1pass; patched13pass. No full upstream suite/PR/maintainer acceptance.

## Remaining prerequisites and limits

Linux x86_64, Python3.12.14, Node24.19,8GiB RAM/8CPU quota, noGPU/Docker/Kubernetes.
P06/P17 hostile execution remains disabled. P14AF_UNIX creation is denied,0inference requests.
P10 Supabase/Stripe and P04 LangSmith need named authorized test accounts. P11 needs a reviewed
cluster/image/CI target, supply-chain remediation, real promotion/rollback and recovery drills.
P15 review threshold0.85 is uncalibrated; remote downstream idempotency remains unverified.
Audit core162/164 queried,0findings; eval120/120 with2affected; security4,research1,training3,
inference1 affected packages; CPU wheels have explicit query gaps. See dependencies/AUDIT.md.

## Next executable action

Fresh checkout: follow locked setup in README.md and each specialized project guide.
This managed checkout uses .venv-verified and projects/04-eval-harness/.venv-final because
old experimental environments retained stale metadata. No runtimes/models are bundled.

```bash
.venv-verified/bin/python -m pais status
PAIS_EVAL_PYTHON="$PWD/projects/04-eval-harness/.venv-final/bin/python" \
  .venv-verified/bin/python -m pais doctor
```

Select one remaining criterion, establish its actual prerequisite, preserve this baseline,
and run its documented acceptance command. A new deployment candidate needs its own full gate.
