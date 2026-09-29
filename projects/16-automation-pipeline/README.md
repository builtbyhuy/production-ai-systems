# P16 — Durable webhook automation

**Implemented. Actual FastAPI, Celery 5.6.3 and Redis 8.2.1 AOF/worker recovery verified. External provider and deployed HA behavior are unverified.**

## Problem and architecture

HTTP acceptance must survive process failure. packages/pais/jobs.py authenticates a trusted principal, verifies HMAC over raw body plus timestamp, validates the schema, and inserts a job and outbox in one transaction. The webhook_router factory supplies a real FastAPI endpoint with server-owned token/signing-secret resolvers.

The publisher leases outbox records. Workers persist attempts, leases, next retry time, cancellation requests and transition history. Retryable, permanent and uncertain outcomes differ. Arbitrary custom handlers require an explicit downstream idempotency contract before unknown failures can be automatically retried. The actual local downstream keeps a separate durable effect receipt.

## Setup and commands

Use the root workflow dependencies. Install redis-server on PATH or use the prepared official Redis source binary at .tools/redis-8.2.1/src/redis-server. Native mode starts a fresh loopback broker with AOF and appendfsync always.

~~~bash
.venv/bin/python -m pais demo 16 --profile fixture
.venv/bin/python -m pais demo 16 --profile local --output artifacts/stateful/p16-local.json
.venv/bin/python -m pytest tests/test_jobs.py tests/test_jobs_http.py tests/test_jobs_native.py -q
~~~

Fixture mode executes real Celery eager tasks, without a broker durability claim. Local mode uses separate worker processes. [Native evidence](../../artifacts/stateful/p16-local.json).

## Acceptance checklist

- [x] FastAPI durable 202, authentication, signature and duplicate payload binding.
- [x] Outbox publish crash, lease recovery and duplicate delivery.
- [x] Redis SIGKILL/restart preserves a queued task.
- [x] Actual worker dies after downstream commit; replacement produces no duplicate effect.
- [x] Retry/backoff, poison isolation, dead-letter inspection and reviewed replay.
- [x] Cancellation, fresh worker membership, cross-tenant denial, trace propagation.
- [ ] Broker HA/failover deployment and real external provider reconciliation.

## Case study and limitations

The native drill passed in approximately seven seconds. One queued job survived Redis restart. The first worker exited 71 after committing its effect; a replacement completed attempt two with the effect count still one. A poison job did not halt healthy work. A transient failure retried, and a reviewed dead-letter replay succeeded. Four intended jobs produced four local effects.

Celery task IDs alone do not deduplicate. A stale worker may finish after lease recovery, so downstream idempotency remains necessary. Cancellation after effect admission cannot undo that effect. Non-idempotent uncertain outcomes cannot be automatically replayed. Redis persistence alone proves neither provider atomicity nor cross-host failover.

## Interview walkthrough

Trace accept_webhook, dispatch, execute and recover_expired. Draw the database-to-broker and provider-to-local-commit gaps. Change max_attempts, break the publisher, inspect history and recover without deleting state. Explain late acknowledgments and the limits of cancellation.

References: [Celery tasks](https://docs.celeryq.dev/en/stable/userguide/tasks.html), [Redis broker](https://docs.celeryq.dev/en/stable/getting-started/backends-and-brokers/redis.html).
