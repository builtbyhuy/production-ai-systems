# Current state

The integrated local PDF copilot and all 18 related implementation tracks exist.
This is an engineering lab portfolio; complete production acceptance remains unfinished.
Read docs/REDTEAM.md for the 30 September source review and docs/PROJECT_LEDGER.md for
criterion-level historical results.

## Redteam revision

- Hardened release-report binding against subsets, unknown IDs, modified metrics,
  missing model evidence and mismatched committed source/datasets.
- Unified writer authorization; guarded memory and standalone vector reads.
- Offloaded cached reply validation without releasing admission on cancelled delivery.
- CI now runs complete positive/degraded fixture evaluations with the isolated worker.
- Public-facing README leads with one integrated app and honest module/evidence scope.
- Selected historical evidence is tracked through artifacts/PUBLIC_EVIDENCE_MANIFEST.json;
  runtime binaries, model weights, databases and installed dependencies remain excluded.

Baseline reproduction: 262 Python checks, fixture release 144/144 and degraded 96/48,
SQLite/LanceDB fixture lifecycle 13/13, 14/14 fixture browser checks, UI build and scoped
lint/types. Focused repaired checks: security/API 87, release/evaluation 25, Qdrant 59.
Final committed-revision checks are recorded in docs/REDTEAM.md when completed.

## Historical source identities

- c7b8a793f34795f3d2de148c1c5c211845e8b222: actual-model release144/144,
  degraded96/48, core262, local/browser/stateful checks; source hashes match Git objects.
- 9f8e0fdf41f3a170004c297c24b18ab01da7f25b: isolated training CLI dependency
  correction and actual tiny SFT/DPO reproduction, quality still rejected.
- a1e0a0c2068f3e86c90257c6c246ac2fc4afad34: original documentation handoff.

Historical reports retain their commits, timestamps and dirty flags. They do not attest
the repaired revision. No new actual-model or production-deployment claim is made.

## Remaining gates

Production dependency advisories/scan gaps, hostile-code sandbox and real inference
serving remain unresolved. External SaaS, registry/cluster rollout/rollback, downstream
receipt reconciliation and upstream submission still require independently verified targets.
Router savings, 10k-vector quality and tiny training quality are unproven or failed.
The eight audit cases reuse development templates; direct source access was reviewed here.

## Continue locally

Use Python3.12/uv; Node24 for the UI; redis-server on PATH for full native tests.

```bash
uv sync --frozen --group dev --extra vectors --extra router --extra workflows
uv sync --frozen --project projects/04-eval-harness
uv run --no-sync pais doctor
uv run --no-sync pytest tests projects/13-agent-memory/test_comparison.py projects/14-inference-server/test_supervisor.py -q
uv run --no-sync pais eval --profile fixture --suite release
```

A new actual-model candidate needs a clean committed tree and its own complete local gate.
Do not infer external publication from local commits; inspect the configured remote and
publication record before describing GitHub, LinkedIn, deployment or upstream status.
