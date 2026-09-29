# P11 test-cluster rollout runbook

**Runbook status: prepared; no steps in this cluster drill have been executed.** These
instructions describe a future authorized test deployment. They do not authorize publication,
registry writes, Git changes, or cluster mutations by themselves.

## Ownership

| Responsibility | Owner to assign before the drill |
| --- | --- |
| Candidate/source review and release-report approval | Repository release owner |
| Test-cluster provisioning and access | Cluster operator |
| Staging quality workload and evaluation evidence | Evaluation owner |
| Traffic promotion, abort, and recovery decision | Deployment owner |
| Global agent emergency stop | Principal with explicit operator role |
| Corrective GitOps change after a failed candidate | Repository release owner |

Do not begin the drill while any responsibility is unassigned.

## 1. Prepare the bounded test environment

Confirm an actual test cluster with Argo CD, Argo Rollouts CRDs/controller, an Nginx ingress
controller, and Prometheus collecting the application metrics. Record their versions.

Provide the declared `pais-test` services, TLS/authentication configuration, preprovisioned model
volume, model lock, and Ollama service. Configure the application OTLP exporter. Test that
Prometheus can distinguish stable and candidate `release` labels.

The current application uses SQLite. The prepared profile requires all stable/canary pods to
share the same node-local POSIX state arrangement; the node label `pais-state-node=true` must
identify the intended node. Verify the storage class and volume actually satisfy this boundary.
Do not use this drill as evidence of multi-node database availability.

Before introducing a candidate, preserve the stable image digest, release bundle, desired-state
Git commit, database/checkpoint schema declarations, and a recoverable test-state backup.

## 2. Produce a candidate with complete evidence

Use a reviewed clean source commit and the frozen application, evaluator, and Guardrails
environments. Provision the locked local models before offline evaluation. The release workflow
already contains the complete sequence; verify that its required runner and environment are
configured before dispatching it.

The existing validation interface is:

```bash
uv run --no-sync python -m pais.operations check-release artifacts/evals/release.json --commit <candidate-commit>
uv run --no-sync python projects/11-cicd/create_bundle.py --help
```

Do not substitute a fixture report, a partial suite, a dirty source tree, or a missing evaluator.
The deliberately degraded evaluation must fail with the evaluator's quality-failure exit code.
A missing prerequisite is a different failure and does not satisfy that check.

Build the digest-pinned API image and verify it inside the container, including `/api/ready` and
a protected real-model response using the isolated Guardrails interpreter. Publish the exact
approved artifact only after a registry target and that write are authorized. Record the actual
pullable image digest; the current workflow itself does not publish the OCI archive.

## 3. Prepare reviewable desired state

Use the existing renderer with the matching bundle and evaluation report. Supply the actual
staging hostname, node-local storage class, authorized GitOps URL, and reviewed GitOps commit.

```bash
uv run --no-sync python projects/11-cicd/render_manifests.py --help
```

Review every generated document. Confirm all placeholders are resolved and the image uses a
digest. Put deployable desired-state files in the GitOps path configured by the Argo application,
`infra/deploy/pais-test`, through the repository's authorized review process. The Argo application
object belongs in the operator-controlled bootstrap path; do not accidentally make the
application recursively manage its own bootstrap.

Run target-cluster schema/server validation before applying anything. A YAML parser or local
render only establishes a narrower property than acceptance by the installed Kubernetes/Argo
versions. Save the validation output. Review the diff against the stable desired state.

## 4. Passing-candidate drill

Synchronize the reviewed GitOps revision using the authorized cluster workflow. Confirm the
stable instance remains ready while the candidate starts and becomes ready. The candidate's
`/api/ready` must succeed before it receives application traffic.

Generate a declared staging workload with known grounded answers and sufficient observations.
Verify that Nginx sends the intended fraction to the candidate. The prepared rollout has:

| Stage | Required behavior |
| --- | --- |
| 10% candidate traffic | Five-minute observation pause, then analysis |
| First analysis | Three measurements five minutes apart; all required metrics must pass |
| 50% candidate traffic | Another five-minute pause, then the same analysis |
| Promotion pause | Deployment owner reviews evidence and explicitly decides whether to promote |
| 100% candidate traffic | Verify readiness, responses, and resulting stable state |

Each analysis requires at least 100 candidate request observations and 100 candidate grounding
observations in its five-minute window, grounding success at least 0.95, request success at
least 0.98, and p95 response latency no greater than 10 seconds. Empty, nonfinite, or insufficient
results cannot pass. These are initial declared thresholds; record the actual workload and
observations rather than assuming ordinary traffic will satisfy them.

Save the AnalysisRun objects, measurements, controller events, routing observations, and
post-promotion smoke results. Only an executed successful drill changes this criterion to PASS.

## 5. Degraded-candidate and no-data drills

Use a deliberately degraded candidate in the test environment whose quality degradation is
known from the declared workload. Preserve the stable artifact. Introduce that candidate through
the same reviewed path and observe the actual analysis failure and traffic returning to stable.

Separately test the absence of candidate quality measurements. Verify the analysis does not
promote on an empty vector, zero observations, a query error, or a nonfinite ratio. Preserve the
actual measurement values and decision; a locally evaluated dictionary is insufficient evidence.

Do not count a candidate that never starts because of a broken dependency as a demonstrated
quality rollback. That is a startup failure and should be recorded separately.

## 6. Emergency control and recovery verification

For an affected agent capability, the operator can use the application's integrated emergency
control to stop new action admissions. Verify both API-originated and worker-originated new
actions are denied. Continue observing previously admitted work; a flag change does not undo an
already completed or admitted external effect.

After an abort or emergency intervention, verify stable traffic, readiness, representative
grounded responses, approval/job state, and usage accounting. Check that replay does not repeat
side effects and that durable state still matches the promised compatibility boundary.

## 7. Correct failed desired state in Git

An aborted rollout is not the same as correcting the desired image in Git. Record the failed
candidate and its evidence, prepare a reviewed change restoring the known-good image/bundle or
introducing a corrected candidate, and update the reviewed GitOps revision through the normal
authorization path. Synchronize it and verify Argo CD and Argo Rollouts agree on the recovered
state. Avoid an unrecorded manual image change that the next reconciliation could reverse.

Close the drill only when recovered service behavior and corrected desired state are both
documented. Preserve the failed candidate's evidence for diagnosis.

## Evidence to attach

Attach candidate/stable hashes, source commits, model/config/dataset identities, cluster and
controller versions, command history with sensitive values redacted, exact time windows,
traffic distribution, quality/request counts, latency/error results, AnalysisRun decisions,
pod/controller events, recovery checks, and the corrective desired-state commit. Until these
exist, promotion, rollback, and recovery acceptance remain **NOT RUN**.
