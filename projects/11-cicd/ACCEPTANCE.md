# P11 acceptance and evidence ledger

Implementation and verification are separate. An unchecked criterion is not a passing gate.
The latest owner checks were run on an uncommitted working tree; final evidence must record the
tested commit and source snapshot.

| Criterion | Implementation | Verification state | Evidence / next requirement |
| --- | --- | --- | --- |
| Tenant capability defaults disabled | Implemented | PASS, local test | `tests/test_operations.py` |
| Tenant administrator cannot control another tenant through a client tenant ID | Principal-scoped flag methods | PASS for flag storage | Application authentication/isolation verification remains with API/workflow owners |
| Global emergency control requires explicit operator role | Implemented | PASS, local test | Tenant admin is rejected |
| Concurrent changes use compare-and-set versions | Implemented | PASS, local test | Four updates at version zero produced one winner and three conflicts |
| Another process observes the emergency stop | Implemented | PASS, local two-process test | No process-local cache |
| Stop survives adapter restart | Implemented | PASS, local test/demo | Bootstrap preserves existing latch |
| Missing emergency state or database error denies admission | Implemented | PASS, local tests | No fallback to previously enabled state |
| API and worker stop all new affected actions | Integration boundary provided | NOT VERIFIED by ops owner | Final API/worker integration and replay checks required |
| Release gate rejects fixtures, duplicates, incomplete results, and inconsistent summaries | Implemented | PASS, contract tests | No model inference performed by these contract fixtures |
| Final `deployment_eligible` condition | Implemented | NOT RERUN | Rerun against final source and actual clean-commit report |
| Required lint and selected type checks | Configured | Partial local verification | Type check covered `contracts.py` and `operations.py` only |
| Dependency and secret scanning in CI | Workflow prepared | NOT RUN | Actual GitHub Actions run required |
| Full actual-model release evaluation | Workflow invokes root evaluator | NOT RUN by P11 owner | Attach root's actual complete release report |
| Deliberately degraded release fails | Workflow prepared | NOT RUN by P11 owner | Execute the same actual-model suite with `--degraded`; expected exit 1 |
| Digest-bound OCI image and release bundle | Dockerfile/scripts prepared | NOT RUN | Container runtime and passing candidate evidence required |
| API image contains working isolated Guardrails validator | Dockerfile configured | NOT RUN | Build image and execute protected-output smoke inside it |
| Kubernetes templates render from valid evidence | Renderer implemented | NOT RUN with real candidate | Use complete matching bundle/report |
| Kubernetes/Argo schema validity | Templates prepared | NOT RUN | Actual target-cluster dry run and CRDs required |
| Candidate gets the declared traffic fractions | Rollout/Nginx configuration prepared | NOT RUN | Observe actual test-cluster traffic |
| Missing quality measurements block promotion | Expression and offline policy implemented | Offline policy PASS; cluster NOT RUN | Exercise an actual no-data analysis |
| Passing candidate promotes | Prepared rollout | NOT RUN | Authorized cluster and sufficient measured traffic |
| Degraded candidate aborts and stable traffic recovers | Prepared analysis | NOT RUN | Executed rollback drill required |
| Failed desired state corrected in Git | Runbook only | NOT RUN | Reviewed corrective GitOps change and subsequent sync |
| Backward-compatible database/checkpoint migration | Initial declaration only | NOT RUN | Cross-version persisted-state and rollback checks |

## Required evidence for each future run

Record the exact command, UTC timestamp, full Git commit, dirty-tree status, source snapshot
hash, selected profile, package/model versions, dataset and configuration hashes, exit status,
and measured outputs. Redact sensitive values. Preserve raw analysis results and Kubernetes
events alongside a concise human-readable report.

For the cluster acceptance, additionally record the cluster/runtime versions, ingress routing
configuration, stable and candidate image digests, pod-template hashes, analysis sample counts,
traffic/error/quality measurements, promotion or abort decision, and post-recovery verification.

## Completion rule

P11 deployment acceptance remains **NOT RUN** until both passing-candidate promotion and
degraded-candidate rollback have been demonstrated on an actual test cluster. Local policy
tests and rendered YAML cannot satisfy that requirement.
