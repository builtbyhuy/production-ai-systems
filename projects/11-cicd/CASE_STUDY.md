# P11 case study — release controls with distinct evidence boundaries

## Decision

Use durable application state for the emergency control, independently validate the evaluator's
release report, and prepare an immutable candidate bundle before any GitOps promotion. Keep
cluster acceptance separate from local code checks.

## Why these boundaries matter

An API process can accept a flag change while an existing worker still holds an enabled value
in memory. That behavior would undermine an emergency stop. `CapabilityFlags` therefore reads
the database at every new action admission. Worker code can use `require_tx()` inside its
existing immediate transaction so the admission and control change have an explicit ordering.

The control does not claim to reverse a side effect that was already admitted. A queued action
or later external-effect attempt must check again. This is a precise operational guarantee
that can be tested without claiming cancellation of completed work.

The release report is also an input that needs validation. Counting 100 array entries would
allow duplicate or fixture cases to masquerade as a complete actual-model evaluation. The
validator checks distinct case identities, per-case results and profiles, summary consistency,
complete-suite coverage, provenance, and clean source identity. The final image/bundle step
then ties that report to concrete component hashes.

## Alternatives considered

| Alternative | Reason it was not selected |
| --- | --- |
| Process-local flags with a time-to-live cache | Creates a stale-admission window during an emergency |
| Only checking the flag in the API | Does not protect already queued work or direct worker paths |
| Treating fixture evaluation as a release fallback | Would hide missing model/evaluator dependencies |
| Deploying mutable image tags | Makes it harder to identify exactly what was tested and rolled back |
| Allowing no-data Prometheus results to pass | Could promote a candidate with no measured quality |
| Spreading SQLite pods across arbitrary nodes | Does not match the current application's storage assumptions |

## What was measured

The last combined operations/inference contract run passed 17 tests in 0.75 seconds. The
operations tests covered tenant flag isolation, role restrictions, competing updates,
cross-process stop visibility, restart behavior, unavailable state, release-report rejection,
bundle validation, and missing/degraded canary observations. The competing-update test admitted
one of four updates at the same expected version and rejected the other three.

The flags demo separately observed default denial, explicit enablement, emergency denial,
and persistence of the latch across an adapter restart. These measurements establish local
control behavior. They establish no Kubernetes rollout result.

The final `deployment_eligible` check was added after that run; final verification remains due.

## What remains uncertain

The container has not been built, the GitHub workflows have not run, and the Argo templates
have not been applied or validated against an actual cluster. The selected canary observation
minimums and latency threshold need to be evaluated against a declared workload. A low-traffic
candidate will correctly remain unable to promote until it has enough observations.

Application and checkpoint compatibility are still an initial version declaration. An actual
migration needs a test that writes state using the old release, reads it using the candidate,
and confirms the previous release can safely resume after rollback where that is promised.

## Next evidence that would change the status

Produce a clean-commit complete release report, build and smoke the exact API image with its
isolated validator, then run the passing/degraded/no-data drills in the rollout runbook. Attach
those outputs before changing any cluster acceptance status to PASS.
