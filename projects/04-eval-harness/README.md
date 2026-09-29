# P04 — Automated evaluation harness

## Problem and scope

A plausible answer, an imported evaluation package, or a green fixture run does not prove a
release works. This harness runs 144 versioned scenarios against the declared RAG profile,
retains raw observations, and blocks incomplete or degraded candidates.

Stack: pytest, a real DeepEval custom metric, real RAGAS string/reference metrics, local
JSON evidence and an explicitly configured LangSmith dataset/run upload adapter.

## Architecture

The application environment executes ingestion, retrieval, generation and source checks.
An isolated subprocess executes the pinned DeepEval/RAGAS metrics over saved observations.
This keeps incompatible LangChain dependency generations separate. The subprocess handles
trusted metric code only; it is not an untrusted-submission sandbox.

Source inputs come only from `evals/corpus.json`. Expected answers remain in the evaluation
runner. The versioned thresholds are in `evals/thresholds.json`; expected categories and case
counts are checked before any deployment eligibility is returned.

## Setup and demo

```bash
uv sync --frozen --group dev --extra vectors --extra router --extra workflows
uv sync --frozen --project projects/04-eval-harness
uv run --no-sync pais eval --profile fixture --suite release --output artifacts/evals/release-fixture.json
```

For actual local models, provision P07 and run all services in the same environment:

```bash
uv run --no-sync python scripts/with_local_models.py -- \
  .venv/bin/python -m pais eval --profile local --suite release \
  --output artifacts/evals/release-local.json
```

The verified runtime is Linux/POSIX. The wrapper's `.venv/bin/python` commands are
Unix-specific. Windows execution, including POSIX resource and file-lock compatibility,
has not been verified and needs its own portability work and acceptance run.

## Meaningful failure demonstration

```bash
uv run --no-sync pais eval --profile fixture --suite release --degraded \
  --output artifacts/evals/degraded-fixture.json
```

The deliberately unsupported answer loses all citations, fails expected content checks,
and must return exit1. A missing worker/model or metric crash returns2. A partial `--limit`
run produces useful diagnostics but cannot pass the release gate. An exit0 fixture report
still sets `deployment_eligible=false`.

## Verification and acceptance

```bash
uv run --no-sync pytest tests/test_evaluation.py -q
```

| Requirement | Evidence |
|---|---|
| 120+ distinct golden cases and coverage | 144 cases, nine categories, manifest hashes |
| Development/training/release/audit separation | Source-group checks; P09 exclusion fingerprints |
| Real DeepEval and RAGAS paths | Isolated `worker.py`, exact locked versions, per-case metric output |
| Degraded candidate blocked | Actual degraded run required; no patched success flags |
| Full local-model release | Status and output under artifacts/evals; fixture cannot substitute |
| LangSmith dataset/run integration | Implemented in `pais.evaluation.langsmith_upload`; real account execution unverified |
| Trends and provenance | Per-run manifest and append-only trends.jsonl |

## Final integrated measurements

Clean commit `c7b8a793f34795f3d2de148c1c5c211845e8b222` passed **144/144** local-profile cases,
with zero errors/skips and p95 **6,366.34 ms**. The unchanged full degraded suite passed
96 and failed 48, exited 1, and was independently rejected by P11 release binding. The
positive binding was accepted. This checks source provenance and the local synthetic
workload; it does not authorize cluster deployment or clear dependency findings.

The positive release contains **56 actual Qwen responses, 16 deterministic page-balanced
excerpt summaries and 72 contract/abstention cases**. It is not 144 generated answers.
The first actual audit run passed **8/8**, p95 **6,508.33 ms**, and appended its exposure.
All three reports, exact metric outputs and exposure records are under `artifacts/evals/`.
The audit remains small, same-build and previously accessed for exclusion/test checks.

## Case study

The first full fixture run passed120/144 and failed all24 summary/conflict scenarios. The
gate correctly rejected it. Those observations prompted general development reproductions,
not changed answers or relaxed thresholds. The first real Qwen run also exposed a quote
schema mismatch: valid retrieved paragraphs became invalid multi-sentence citations.
P01 retained strict source validation and changed the model output contract to sentence IDs.

An initial RAGAS0.3.9 import failed with modern LangChain community; upgrading to0.4.3 did
not fix it. A separate older-family runtime first restored metric execution, but the final
dependency audit found known advisories in its LangChain family. The adopted lock now uses
DeepEval4.2.6, RAGAS0.4.3, LangChain1.4.3/Core1.6.5/OpenAI1.6.6 and Community0.3.31. That
Community version retains the legacy VertexAI module still imported by RAGAS.

The unchanged worker reproduced all432 numerical metric values across144 preserved release
observations exactly in a fresh environment. The experiment and adoption evidence are in
`artifacts/eval-upgrade/`. Remaining RAGAS/DiskCache advisories still block production
dependency clearance; see [AUDIT.md](../../docs/dependencies/AUDIT.md). This is why dependency
resolution, actual metric execution and security status are recorded independently.

The current managed checkout used a new isolated `.venv-final` after an in-place upgrade
retained conflicting old distributions. `PAIS_EVAL_PYTHON` selects an explicit worker
interpreter; a new checkout defaults to `projects/04-eval-harness/.venv/bin/python`.

Metrics intentionally use exact extractive support and expected decisions. There is no LLM
judge, so these results do not claim a calibrated semantic oracle. The eight audit cases
are small, synthetic and authored during this build; they are not independently curated
blind evaluation. Hash/overlap inspection for P09 is disclosed, and future executions append
to the audit-exposure log. Single-seed local runs do not measure stochastic stability.

## Interview walkthrough

Start at `pais.evaluation.run_suite`, follow a case through `run_case`, and show where oracle
fields stop at the evaluator boundary. Explain the difference between a test failure, a
metric/infrastructure error, an incomplete suite and an actual deployment-eligible report.
Then introduce a wrong page and demonstrate why deterministic source checks outrank a
plausible answer. You should be able to add a new failure category, write its expected
outcome, update the versioned coverage contract, and reproduce a blocked candidate yourself.
