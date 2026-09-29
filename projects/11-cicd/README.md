# P11 — CI/CD for AI systems

This project connects application release evidence, immutable artifacts, progressive delivery,
and an emergency control for agent actions. The local operational controls have been exercised.
The GitHub workflows, container build, and Kubernetes rollout have not been executed.

| Component | Implementation | Evidence available |
| --- | --- | --- |
| Capability flags and global emergency stop | Implemented in `pais.operations` | Local SQLite tests and a two-process check passed |
| Independent release-report validator | Implemented | Contract tests passed; final eligibility-field change awaits rerun |
| Immutable release bundle and manifest renderer | Implemented | Source reviewed; real candidate rendering not run |
| GitHub Actions CI/release workflows | Prepared | Workflow execution not run |
| API container | Dockerfile prepared | Build and container smoke not run |
| Argo CD / Argo Rollouts | Templates prepared | Cluster validation, promotion, and rollback not run |

See [acceptance](ACCEPTANCE.md), [case study](CASE_STUDY.md),
[interview walkthrough](INTERVIEW.md), and [rollout runbook](ROLLOUT_RUNBOOK.md).

## Problem and scope

A passing application test suite does not establish that a model still answers correctly, that
an artifact contains the tested configuration, or that a deployed candidate can recover safely.
This project makes those checks explicit and keeps their evidence separate. A fixture result is
useful for testing the controls; it cannot authorize a model release.

The runtime control currently covers the single named capability `agent.execute`. Tenant
administrators may change their tenant's flag. A trusted principal with the explicit `operator`
role controls the global emergency latch. Both states must permit an action.

## Architecture

The API and workers share authoritative SQLite state through `Database`. Workers call
`CapabilityFlags.require_tx()` inside the same `BEGIN IMMEDIATE` transaction that admits an
action. The flag check has no process-local cache. A disable operation therefore orders against
new admissions through the database transaction boundary. An already admitted action is not
undone by changing a flag; later external-effect attempts must recheck at their own boundary.

CI runs code checks and explicitly selected contract tests. The manually triggered release
workflow uses a separately provisioned local-model runner, executes the entire release suite,
and independently checks its report against the candidate commit. It also requires the
deliberately degraded evaluation to fail. Only then does it prepare an OCI archive and bundle.

`create_bundle.py` binds the application image digest, Git commit, prompt implementation,
model/embedding lock, flag implementation, evaluation report, and compatibility declarations.
`render_manifests.py` rejects a bundle whose evaluation hash differs from the supplied report.
Rendering writes files for review; it does not apply them to a cluster.

Argo CD reads a reviewed GitOps commit. Argo Rollouts controls a 10% then 50% candidate, runs
candidate-specific Prometheus analysis at each stage, and pauses before final promotion. The
application's `PAIS_RELEASE` comes from the rollout pod-template hash so candidate observations
can be separated from stable observations.

### State and compatibility boundary

The prepared application rollout has one desired replica plus one canary surge. Both use the
same POSIX state volume on a single node selected by `pais-state-node=true`. This is a bounded
test profile for the current SQLite application, not a multi-node database architecture. A
shared network filesystem is not an accepted substitute for that POSIX state arrangement.

`infra/release-compatibility.json` declares schema versions and an `expand-only` migration
policy. Its initial values are declarations, not executed compatibility evidence. Review it
whenever a database schema, graph state, serializer, or checkpoint format changes. A candidate
must keep the prior release's persisted data readable throughout the canary and rollback window.

## Setup

Run these existing commands from the repository root when provisioning is authorized. They
are instructions; their presence does not imply that this project executed CI or a deployment.

```bash
uv sync --frozen --group dev --extra local --extra router --extra workflows --extra vectors
uv sync --frozen --project projects/04-eval-harness
uv sync --frozen --project projects/06-security-guardrails
```

The isolated Guardrails interpreter must be configured through `PAIS_GUARDRAILS_PYTHON` for
protected real-model outputs. `infra/Dockerfile.api` creates that environment and sets the path
inside the image. Model files and the model lock must be provisioned independently; the API
image does not prove model availability. The release runner additionally needs the declared
Ollama endpoint, Docker/Buildx, and an operator-reviewed Python base image digest.

The release workflow requires a protected `ai-release` environment and a trusted runner with
labels `self-hosted`, `linux`, and `pais-local-models`. It is restricted to the main branch and
must not be repurposed to execute untrusted pull-request code on that runner.

## Existing demo and verification commands

P07 also provides prepared local-container alternatives in
[`compose.yaml`](../07-local-first/compose.yaml) and
[`compose.offline.yaml`](../07-local-first/compose.offline.yaml), both reusing the API Dockerfile.
Their build/start and offline-container behavior remain unexecuted. See P07 for their
configuration and storage requirements; these files do not establish P11 cluster acceptance.

```bash
uv run --no-sync python -m pais.operations flags-demo
uv run --no-sync pytest tests/test_operations.py tests/test_operations_inference.py -q
uv run --no-sync mypy packages/pais/contracts.py packages/pais/operations.py
uv run --no-sync python -m pais.operations --help
uv run --no-sync python projects/11-cicd/create_bundle.py --help
uv run --no-sync python projects/11-cicd/render_manifests.py --help
```

For a provisioned actual-model candidate:

```bash
uv run --no-sync pais eval --profile local --suite release --output artifacts/evals/release.json
uv run --no-sync python -m pais.operations check-release artifacts/evals/release.json --commit <candidate-commit>
```

The independent check requires at least 100 distinct passing local-profile cases, the complete
required suite, no skips/errors, actual model and evaluator provenance, dataset and source
hashes, a timestamp, a clean full Git commit, and `summary.deployment_eligible=true`. The
repository's evaluation suite can impose additional requirements beyond this minimum.

Use `uv run --no-sync` after a controlled synchronization so a later command does not silently
change the chosen optional dependencies. The workflow separately provisions the evaluator and
Guardrails environments because their dependency ranges differ from the application runtime.

## Evidence and limitations

The last owner verification reported 17 combined operations/inference contract tests passing
in 0.75 seconds and a successful type check of `contracts.py` plus `operations.py`. These are
local checks, and that type-check scope does not cover the whole application. The final addition
of the `deployment_eligible` assertion and its test fixture update happened after that run and
still needs verification against the final source commit.

The local flag demo observed default denial, an admitted action after explicit enablement,
denial after an emergency stop, and preservation of that stop across adapter restart. It did
not run an actual cluster drill. No CI execution, built image digest, deployed candidate,
promotion, rollback, or staging recovery result is claimed here.

## Sources checked

- [GitHub Actions secure use](https://docs.github.com/en/actions/reference/security/secure-use)
- [Argo Rollouts analysis](https://argoproj.github.io/argo-rollouts/features/analysis/)
- [Argo Prometheus analysis](https://argoproj.github.io/argo-rollouts/analysis/prometheus/)

The prepared action versions were resolved to full upstream commit SHAs during implementation.
Recheck their release support and runner requirements when adopting these workflows.
