# P17 acceptance and remaining prerequisites

| Requirement | State and evidence |
|---|---|
| Narrow Python/API maintenance domain and explicit binary task rubric | IMPLEMENTED: README and data card |
| At least 100 licensed, versioned, meaningful tasks | PASS: 100 unique reference ASTs, 10 categories, 325 checks |
| Source provenance, splits and contamination statement | PASS: per-task metadata, pinned corpus hash and data card |
| Trusted reference passes and every seeded defect is detected | PASS: `artifacts/p17-fixture/fixture-validation.json` |
| Invalid submission rejected before execution | PASS: fixture demo and `tests/test_benchmark.py` |
| Candidate shape/size checks and P06 limits | IMPLEMENTED; default-disabled denial verified |
| Actual available baseline implementations | IMPLEMENTED: no-op and twelve-rule mechanical repair |
| Actual baseline scoring in a secure boundary | BLOCKED: no verified rootless Docker runtime; bwrap network setup denied |
| Reproducible real scores and leaderboard/raw-result agreement | NOT RUN: controller validation tested, real score files absent |
| Model/version/config/compute/cost/uncertainty metadata | IMPLEMENTED in score/leaderboard schema; real model metadata absent |
| Publication package and contribution instructions | PREPARED; no publication target/action authorized here |
| Public publication and independent community use | NOT RUN / NO EVIDENCE |

## Verification commands

```bash
PYTHONPATH=packages .venv/bin/python -m pais.benchmark fixture --output artifacts/p17-fixture
.venv/bin/pytest -q tests/test_benchmark.py
```

Tests explicitly distinguish controller fixtures from real results. Temporary controller-fixture JSON is used to exercise recount/tamper detection; it never becomes retained leaderboard evidence. Trusted authoring QA is rejected by the leaderboard loader.

The next real acceptance action is to provision and audit P06's rootless Docker boundary plus a pinned Python image, then run both baselines on the same declared split, repeat the runs and build the leaderboard from their raw results. README contains the exact commands. If the environment cannot enforce the boundary, leave scoring blocked. No subprocess fallback is acceptable.
