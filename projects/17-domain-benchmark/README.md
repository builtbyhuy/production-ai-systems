# P17 — Python/API maintenance benchmark

**Status: corpus and controller implemented; trusted corpus QA verified; untrusted scoring, baseline comparison and leaderboard reproduction remain blocked by the missing execution boundary.** No model or repair-baseline score has been published. The leaderboard contains no real rows yet.

## Problem, domain and stack

A useful code benchmark needs more than a list of coding prompts. Each task must define observable behavior, distinguish a seeded bug from its reference, preserve provenance/splits, and execute untrusted candidate programs behind a real isolation boundary. This project targets narrow Python/API maintenance because deterministic return values, wire encodings, error handling and state-machine transitions provide executable correctness contracts without subjective LLM judging.

The stack is custom Python plus pytest, integrated with P06 `SandboxRunner`. [benchmark.py](../../packages/pais/benchmark.py) owns loading, validation, baselines, controller-side comparison and leaderboard generation. [build_corpus.py](build_corpus.py) authors a versioned set of **100 structurally distinct tasks**, each with at least three checks: **325 checks** total. No external service is required for trusted corpus QA.

## Setup and working demo

From the repository root:

```bash
uv sync --group dev
PYTHONPATH=packages .venv/bin/python -m pais.benchmark fixture --output artifacts/p17-fixture
.venv/bin/pytest -q tests/test_benchmark.py
PYTHONPATH=packages .venv/bin/python -m pais.benchmark baseline no-op --output artifacts/p17-submissions/no-op.json
PYTHONPATH=packages .venv/bin/python -m pais.benchmark baseline mechanical-repair --output artifacts/p17-submissions/mechanical-repair.json
```

The fixture demo validates all reference contracts, reproduces every seeded defect, rejects a malformed submission and demonstrates denial by a disabled sandbox. It does **not** run untrusted code or score a baseline. Baseline export writes only candidate source and metadata. [EVIDENCE.json](EVIDENCE.json) retains the small reviewed authoring-QA result and source-record digest; raw local artifacts remain outside Git.

## Actual scoring when P06 prerequisites are available

The runner requires a verified local rootless Docker daemon, Linux cgroup v2 CPU/memory/process limits, seccomp and a preprovisioned digest-pinned Python image. It disables network access, host mounts and inherited credentials, uses an unprivileged container user/read-only root, and caps wall time/output. The digest below must come from the image the operator actually reviewed and provisioned:

```bash
export PAIS_SANDBOX_IMAGE='python@sha256:REPLACE_WITH_ACTUAL_AUDITED_IMAGE_DIGEST'
PYTHONPATH=packages .venv/bin/python -m pais.benchmark score artifacts/p17-submissions/no-op.json --split test --sandbox-image "$PAIS_SANDBOX_IMAGE" --enable-sandbox --output artifacts/p17-runs/no-op-test
PYTHONPATH=packages .venv/bin/python -m pais.benchmark score artifacts/p17-submissions/mechanical-repair.json --split test --sandbox-image "$PAIS_SANDBOX_IMAGE" --enable-sandbox --output artifacts/p17-runs/mechanical-test
PYTHONPATH=packages .venv/bin/python -m pais.benchmark leaderboard artifacts/p17-runs/no-op-test/raw-results.json artifacts/p17-runs/mechanical-test/raw-results.json --output artifacts/p17-runs/leaderboard.json
```

Repeat both score commands into fresh directories and compare task outcomes and dataset/submission hashes. `train`, `dev`, `test` and `all` scoring modes are explicit. The supplied host has no Docker daemon; an actual bwrap network-namespace probe also failed with `Operation not permitted`. Default or unsupported execution therefore raises `SandboxUnavailable`, exit 2. A host Python subprocess is never substituted for the boundary.

## Scoring and data flow

Submission validation accepts bounded Python source defining one synchronous top-level `solve` function for known task ids. Parsing syntax does not establish that a program is safe. Validated candidates still require P06.

Each task gets a fresh sandbox and a batch of JSON case arguments. The expected outputs stay in the controller. A candidate returns one bounded JSON array containing return values or exception classes. Additional output, wrong shape, timeouts, output overflow and nonzero exit codes fail the task. The controller checks structured values, exact strings and exception types; numeric comparisons use `1e-9` tolerance, and booleans do not count as integers. A task earns **1 only when every check passes**. Missing solutions score 0. There is one candidate per task, so the aggregate is pass@1, reported separately by split/category/difficulty.

The leaderboard recounts raw case outcomes, verifies the complete declared split and result digests, and rejects corpus-QA records. Its Wilson task intervals describe sample uncertainty under a task-sampling interpretation; they do not measure model randomness or prove the synthetic tasks are representative. Generation cost is explicitly self-reported submission metadata; local infrastructure cost is unknown. Hashes detect accidental corruption, not forged provenance or malicious editing by an operator.

## Baselines and limitations

- **no-op 1.0.0:** returns each original defective starter unchanged. This is an executable negative control, not an AI model.
- **mechanical-repair 1.0.0:** applies twelve fixed string repair rules written for train-split idioms. It never reads the reference/expected-output fields while producing a submission and is openly labeled a hand-authored rule engine. It is not a general repair system or model-quality baseline.

All task text, references and checks are public. Prior exposure, task-specific memorization and familiarity with common bug patterns cannot be excluded. The current corpus comprises small synthetic seeded regressions, not real repository issues, broad software engineering tasks or production customer failures. The checksum-pinned reference validator deliberately executes only the repository's authored reference/starter code on the host; its results have a separate non-leaderboard evidence type.

For dataset details, measured authoring QA, contribution/publication procedure and interview material, see [DATA_CARD.md](DATA_CARD.md), [ACCEPTANCE.md](ACCEPTANCE.md), [CASE_STUDY.md](CASE_STUDY.md), [CONTRIBUTING.md](CONTRIBUTING.md), and [INTERVIEW.md](INTERVIEW.md).
