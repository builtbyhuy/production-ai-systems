# Evidence inventory and acceptance boundaries

This directory contains generated measurements, historical failures and final verified
runs. Raw output is ignored by Git except small reviewed reports. The delivery archive
includes selected evidence alongside the source; runtimes, caches, service state stores
and large downloaded model weights are excluded. The archive manifest records file hashes.

## Authoritative final records

| Evidence | Source identity | Accepted meaning |
|---|---|---|
| `final/core-tests.json`, `final/lint.json`, `final/typecheck-python.json`, `final/ui-build.json` | Clean c7b8 | 262 core tests; Ruff; selected-module mypy; frontend type/build checks |
| `final/crewai-tests.json`, `final/guardrails-tests.json` | Clean c7b8 | Real isolated libraries; 5 and 3 controlled tests; upstream warnings retained |
| `final/demos/index.json` and per-project JSON/logs | Clean c7b8 | All 18 fixture command entrypoints ran successfully; not 18 accepted production systems |
| `evals/release-local-final.json` | Clean c7b8 | Full local synthetic regression, 144/144; scope excludes the whole production gate |
| `evals/degraded-local-final.json` | Clean c7b8 | Full deliberately degraded run, 96 pass / 48 fail, exit 1 |
| `evals/audit-local-final.json`, `evals/audit-exposures.jsonl` | Clean c7b8 | Eight actual model responses; first actual audit execution, disclosed prior source/exclusion exposure |
| `final/release-binding.json`, `final/degraded-binding.json` | Clean c7b8 target | Positive report accepted and negative report rejected by independent release binding |
| `ui/browser-evidence.json`, `ui/local/browser-evidence.json` | Clean c7b8 | 14 fixture browser cases and one actual local desktop case; actual screenshots |
| `ui/local/local-smoke-measurements.json` | Same actual local browser run | First checked display 14,785 ms; provider TTFT null; synthetic test identity |
| `p12-scale/scale-report.json` and worker/resource records | Clean c7b8 | Actual 1k/10k Qdrant-local stores with feature hashes; hybrid quality degradation and monitor limitations disclosed |
| `final/p16-native.json` | Clean c7b8 | Actual Redis/Celery worker/AOF crash/recovery with a durable local downstream |
| `final/p14-local-blocked.json` | Clean c7b8 | Required IPC unavailable, exit 2 and zero inference calls; not a serving pass |
| `final/p09-cli/run.json`, `final/p09-cli-command.json` | Clean 9f8e | Actual isolated common CLI SFT/DPO after declared dependency fix; retention remains rejected |
| `pip-audit-verified.json`, `pip-audit-eval-final.json`, `pip-audit-training-final.json` | Named installed locked environments | Findings plus skip/query coverage, not a security guarantee |

Full commit identifiers are in each manifest and `docs/VERIFICATION.md`. The final
`final/verification-index.json` records key evidence file hashes and the delivery source identity.
Model-lock/inventory copies in `provisioning/` preserve observed identities and original
machine-specific paths. Recreate those paths for a new host; weights are not bundled.

## Historical and nonaccepted output

- The accepted P05 monitoring run is **`p05-native-first-pass/report.json`**, SHA-256
  `7ee4e5bdf01420327bdd93977280c3e1c2d265b7f5e278fadf55581c5aca8133`.
  `reports/p05-native-accepted.json` is its reviewed source-controlled copy.
  The convenient `p05-native/` path was later overwritten by an interrupted visual attempt;
  it is not accepted evidence. The first-pass screenshot rendered eight of twelve panels.
- `evals/release-local-first.json` preserves 132/144 and twelve summary omissions.
  Earlier fixture failures and diagnostic subsets are retained. Subsets cannot pass release.
- `ui-pre-freeze/` preserves earlier browser measurements with their original dirty/unborn
  source identity. The final `ui/` records supersede these for clean-commit UI claims.
- `final/p09-local.log` preserves the missing-Pydantic import failure before training.
  The original `p09-smoke/` contains genuine earlier tiny training; final reproduction lives
  under `final/p09-cli/`. Neither is a useful-model quality release.
- `p14-cpu-functional-first/report.json` records actual startup failure before readiness.
  Its literal historical `HEAD` was recorded before the first Git commit; the project
  evidence note corrects that provenance limit. No vLLM generation is claimed.
- `eval-upgrade/previous-worker/` and `pip-audit-eval.json` retain the old evaluator baseline.
  The new worker's 432 exact metric matches and remaining two affected packages are separate.
- `pip-audit-core.json` records an experimental environment with extra distributions.
  Use the fresh `pip-audit-verified.json` query coverage for the final core observation.
- The earlier `pip-audit-training.json` lists 45 entries; after the Pydantic declaration,
  `pip-audit-training-final.json` lists 49 with 48 queried, CPU Torch unmatched and three
  affected package names. Inference has five unmatched CPU wheel versions.

Historical errors are preserved to explain decisions. No raw file marked failed, blocked,
running, partial or unexecuted is silently converted into a success by its presence here.
