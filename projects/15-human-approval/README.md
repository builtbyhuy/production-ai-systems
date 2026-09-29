# P15 — Exact-action human approval

**Implemented. Real LangGraph checkpoints and local downstream recovery verified. Full acceptance remains incomplete: uncertainty calibration and external effects are unverified.**

## Problem and architecture

A resumed graph can replay a node. A decision must remain bound to its tenant, designated reviewer, exact action/arguments, source version, expiry, and idempotency key. The implementation in packages/pais/workflows.py uses LangGraph 1.2.12 and SQLite checkpointer 3.1.1.

The sequence is request → persistent interrupt → transactional decision → revalidation → effect → durable receipt. Every approval lookup is authorized before its checkpoint is read. A separate downstream database stores immutable idempotency receipts. Tools record_note and publish_report only create local records; they do not deliver anything outside this application.

## Setup, demo and verification

Use the root locked environment. Enable agent.execute explicitly through the admin UI or controlled fixture setup; authentication alone never enables effects.

~~~bash
.venv/bin/python -m pais demo 15 --profile fixture --output artifacts/stateful/p15-fixture.json
.venv/bin/python -m pytest tests/test_workflows.py -q
~~~

The demo pauses, constructs a new service, approves, and resumes twice. [Evidence](../../artifacts/stateful/p15-fixture.json).

## Acceptance checklist

- [x] Actual persistent LangGraph interrupt and restart/resume.
- [x] Wrong tenant, reviewer, revoked role, expired approval, changed action and stale context rejected.
- [x] Approve/reject/cancel; edit creates a new pending review with a new key.
- [x] Concurrent opposed decisions have one winner.
- [x] Crash after separate downstream commit recovers with one effect.
- [x] Default-disabled capability checked inside effect admission.
- [ ] Calibrated uncertainty threshold on reviewed development examples.
- [ ] Remote idempotency/receipt and context-precondition integration.

## Case study and limitations

Twelve focused tests passed. The design rejects thread-ID authorization and an in-memory approved boolean. Local context changes and effect admission serialize in an immediate transaction. Existing receipts can be reconciled after expiry or emergency disable because reconciliation authorizes no new effect.

The one-effect claim is limited to the actual durable local downstream. Remote services need their own durable idempotency retention and receipt lookup. An external context resolver is not an atomic lock over another system. The grounding threshold 0.85 is an explicit development rule, not calibrated uncertainty. Unix file locking serializes graph threads on one host; distributed deployments need a cross-host strategy.

## Interview walkthrough

Trace decide, _drive, _execute and DurableEffectStore.apply. Explain interrupted-node replay and the two databases. Add an argument to an action and show hash invalidation. Reproduce an after-effect failure. Explain precisely why a local receipt cannot prove a remote exactly-once guarantee.

References: [interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts), [persistence](https://docs.langchain.com/oss/python/langgraph/persistence).
