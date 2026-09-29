# P11 interview walkthrough

## Explain the critical code path

Start at `CapabilityFlags.set()` and `emergency_stop()` in `packages/pais/operations.py`. Explain
who is authorized, what database row changes, how the expected version prevents lost updates,
and when the change commits. Then follow `require_tx()` into the worker's action-admission
transaction. Explain why a check in the API alone is insufficient for queued work.

Next follow `validate_release_evaluation()`. Identify why it checks individual cases as well
as the summary, why a fixture or dirty-tree report is rejected, and how the report hash enters
`create_bundle.py`. Show how `render_manifests.py` verifies the bundle/report relationship.

Finally trace the workflow and Argo configuration: trusted runner, frozen dependencies, actual
release evaluation, expected degraded failure, OCI build, candidate bundle, GitOps revision,
10% traffic, analysis, 50% traffic, analysis, human promotion pause.

## Be able to answer these questions

1. What can still happen after an emergency stop commits? Explain already admitted work and
   why later external-effect attempts require a fresh check.
2. What happens if the database is unavailable? Explain denial, not a cached enabled fallback.
3. Who can flip a tenant flag, and who can operate the global stop? A tenant administrator's
   role is not authority over all tenants.
4. How do two administrators avoid silently overwriting one another's decision? Show the
   expected-version check and the competing-update test.
5. Why is `uv run --no-sync` used after synchronization? Explain the selected extras and
   separately provisioned evaluator/validator environments.
6. What does an image digest prove, and what does it not prove? It identifies content; it does
   not prove the contained model configuration or application behavior unless evidence binds them.
7. How does candidate quality avoid being diluted by stable traffic? Point to the rollout hash
   used as the metrics release label and the analysis argument.
8. What happens when Prometheus has no matching data, too few samples, or a nonfinite value?
   Explain why that cannot produce successful promotion.
9. What is the rollback owner's responsibility after Argo aborts? Explain verification of
   recovered stable traffic and correction of failed desired state in Git.
10. Why is the SQLite test deployment pinned to one node? Describe the current storage boundary
    and what would be needed before claiming multi-node availability.

## Changes you should be able to make yourself

- Add a new named capability with a default-denied tenant state and a tested global latch.
- Add a required release-report invariant and a rejection test for a malformed report.
- Change a canary threshold consistently in the offline policy, analysis YAML, and documentation.
- Extend a release bundle to include another versioned component without weakening image or
  report identity checks.
- Write a cross-version checkpoint compatibility test for a concrete schema change.

## Describe the evidence accurately

Say that the local controls were tested and the deployment templates were prepared. Do not say
that this project has demonstrated a Kubernetes rollout or rollback. The container, workflows,
cluster routing, model-quality rollout analysis, and rollback drills remain unexecuted.
