# Verification report

The repository is entering its final source freeze. The complete scope and criterion-level
status are recorded in [PROJECT_LEDGER.md](PROJECT_LEDGER.md). All 18 implementation tracks
exist. Outstanding connected, sandbox, model-quality and deployment obligations remain
incomplete; implementation counts are not production-readiness claims.

## Evidence identity

The final integrated runs will be captured against a clean source commit under
`artifacts/final/` and `artifacts/evals/`. Earlier project reports retain their actual source
snapshots, commands, timestamps and dirty/unborn Git state. No historical result is rewritten
to claim it ran against a later commit. A later documentation-only evidence commit may
describe the tested source commit; it is not a separately exercised deployment candidate.

## Current measured results

- A newly created locked core environment passed 257 tests. The final suite will include
  the later research endpoint, memory comparison and inference supervisor regressions.
- Actual RAG lifecycle checks passed 13/13 in both SQLite and LanceDB offline profiles.
- The first full actual-model release passed 132/144; twelve summary omissions were retained.
  A disclosed page-balanced source-excerpt route addresses explicit summaries. The same
  frozen 144-case gate must pass after the source freeze; no threshold was relaxed.
- Actual local browser smoke passed 1/1; desktop/mobile fixture browser checks passed14/14.
- Native Prometheus/Grafana/Tempo/Alertmanager observed two alert firing/resolution cycles,
  a producer/worker trace and simulated ledger40 micro-USD equal to the metric total.
- Real Redis/Celery recovery retained one visible effect across worker death/recovery.
- Genuine tiny SFT and DPO ran and adapters reloaded exactly; all held-out exact matches
  were zero, and retention acceptance rejected the result.
- The vLLM CPU server failed before readiness because this host denies AF_UNIX sockets.
  Zero model generation requests ran; subsequent attempts fail closed at preflight.
- The upstream SQLite defect has a baseline with three failing regression checks; the
  patch passes thirteen focused/upstream checks. No upstream submission was made.

## Dependency audit scope

The fresh core environment's 164 noneditable packages and the UI production dependency
audit reported no known advisories at scan time. This is a scanner observation, not a
security guarantee. The isolated evaluation, Guardrails, CrewAI and training environments
have reported advisories. See [the dependency audit](dependencies/AUDIT.md) and raw reports.
They are not suppressed, and a whole-repository production supply-chain gate is not passed.

No public deployment, container/cluster rollout, connected Supabase/Stripe/LangSmith run,
untrusted benchmark score, paid-provider savings or upstream maintainer acceptance is claimed.

## Final verification commands

```bash
UV_PROJECT_ENVIRONMENT=.venv-verified uv sync --frozen --group dev --extra local --extra vectors --extra router --extra workflows
.venv-verified/bin/python -m pais evidence --profile fixture --output artifacts/final/core-tests.json -- .venv-verified/bin/python -m pytest tests projects/13-agent-memory/test_comparison.py projects/14-inference-server/test_supervisor.py -q
.venv-verified/bin/python scripts/with_local_models.py -- .venv-verified/bin/python -m pais eval --profile local --suite release --output artifacts/evals/release-local-final.json
.venv-verified/bin/python scripts/with_local_models.py -- .venv-verified/bin/python -m pais eval --profile local --suite release --degraded --output artifacts/evals/degraded-local-final.json
.venv-verified/bin/python scripts/with_local_models.py -- .venv-verified/bin/python -m pais eval --profile local --suite audit --output artifacts/evals/audit-local-final.json
```

The degraded command is expected to exit1. Missing prerequisites exit2 and do not establish
a correctly rejected quality candidate. The eight audit cases are synthetic, same-build and
small; exposure is appended to `artifacts/evals/audit-exposures.jsonl` and never used to tune.
