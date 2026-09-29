# P02 — Persistent model routing and spend admission

**Implementation:** policy, LiteLLM adapter, persistent usage ledger, scoped cache, bounded retries,
timeouts and circuit breaker are implemented. **Evidence:** fixture failure/concurrency tests and
an actual two-model local comparison are verified; connected invoice reconciliation remains unverified.
No fixture result establishes model quality or actual dollar savings.

## Problem and architecture

An inexpensive model is useful only when it can satisfy the request. Retrying a timed-out call
can also spend money even if the first call returned no usage. `ModelRouter` makes an explicit
policy decision and reserves budget before each provider dispatch. The SQLite ledger serializes
competing reservations, persists holds across restarts, and makes missing usage visible.

The critical path is `route → start_request → reserve → dispatch → provider → settle → finish`.
Every retry/fallback receives its own attempt ID, rate-card version and usage events. A request
is owned by its server-resolved principal. Response caches include tenant, owner, model/policy
configuration, input messages, quality and capability requirements. Request-ID replay returns
the durable result without dispatching another provider call.

The router chooses a cheap default, escalates high-quality/research/code/large-context work,
preserves required capabilities and context limits, and bounds total attempts. A SQLite circuit
breaker admits one half-open probe after cooldown. Model output never chooses its own budget,
credentials, transport endpoint or retry count.

Code: [reliability.py](../../packages/pais/reliability.py),
[failure tests](../../tests/test_reliability.py). Metrics are emitted through
[observability.py](../../packages/pais/observability.py).

## Setup and commands

Use the repository's core setup first. A clean router-only environment additionally needs
`uv sync --frozen --extra router`. When maintaining an environment with other selected extras,
include those extras in subsequent `uv sync` commands so they remain installed.

```bash
.venv/bin/pais demo 02 --profile fixture --output artifacts/p02-fixture.json
.venv/bin/python -m pytest tests/test_reliability.py -q
```

For real local inference, provision two different Ollama models using P07, then select their
explicit LiteLLM model identifiers. This command does not download models or enable paid calls.
The adapter uses LiteLLM's bundled model metadata in local mode to avoid a hidden remote price-map
fetch. The explicit `Price` configuration remains the accounting authority; bundled metadata is
not presented as a current provider rate card.

```bash
PAIS_ROUTER_CHEAP_MODEL=ollama_chat/qwen2.5:0.5b \
PAIS_ROUTER_EXPENSIVE_MODEL=ollama_chat/qwen2.5:1.5b \
.venv/bin/pais demo 02 --profile local --output artifacts/p02-local.json
```

The comparison uses the same twelve original operations/debugging tasks for always-cheap,
always-expensive and routed policies. Expected strings stay in the scorer and are never sent
to the provider. Exact-match scoring is deliberately narrow; inspect raw outputs in the
evidence directory before attributing a miss to reasoning. The public corpus is not an unseen
general benchmark. Costs for fixture outputs use a clearly marked simulation rate card. The
local comparison uses zero API rates, so it cannot report savings versus a paid baseline.

## Measured local comparison

The captured run in `artifacts/p02-router-local.json` used actual local Ollama inference through
LiteLLM with `qwen2.5:0.5b` and `qwen2.5:1.5b`. Each policy made twelve provider calls with zero
provider errors, on the same twelve tasks and with response caching disabled.

| Policy | Exact matches | Mean request latency | p95 latency | Mean routing overhead |
|---|---:|---:|---:|---:|
| Always cheap, 0.5B | 4 / 12 (33.3%) | 0.801 s | 2.036 s | 0.636 ms |
| Always expensive, 1.5B | 6 / 12 (50.0%) | 2.084 s | 5.800 s | 0.640 ms |
| Routed | 4 / 12 (33.3%) | 1.054 s | 2.608 s | 2.746 ms |

The configured router did not improve exact-match accuracy over the cheap baseline in this run.
The larger model passed two additional cases and took longer. These observations describe a
single small, public synthetic workload with strict output-format scoring; they do not establish
general capability or statistically reliable superiority. Inspect the captured raw responses
when distinguishing formatting failures from incorrect answers. All rates were explicitly
`local-zero`: API charges were zero, while hardware, energy and operational costs were unmeasured.
There is no measured paid-provider savings claim.

## Accounting contract

| State | Meaning | Admission consequence |
|---|---|---|
| Reserved | Server-calculated upper-bound estimate held before dispatch | Counts toward tenant and request caps |
| Estimated | Versioned pre-call estimate, retained in append-only history | Does not add a second charge |
| Reported | Provider token counts priced by the declared rate card | Replaces the hold with priced usage |
| Unknown | Final usage absent, including ambiguous timeout/cancellation | Keeps the full hold until reconciliation |
| Reconciled | Authorized operator applied authoritative evidence | Appends correction and final cost events |
| Cache | Authorized response reuse with no provider dispatch | Records a zero-cost cache event |

The admission guarantee applies to the declared cost bounds. Actual providers may bill special
tokens, tools or other units beyond a naive token estimate. Validate the tokenizer and billing
contract before treating a configured bound as an invoice cap. If reported usage exceeds the
reservation, the ledger records the overrun and further admission is blocked; it never hides
the real charge. Unknown usage is never silently converted to zero.

## Acceptance checklist

- [x] Concurrent admission near a cap: 24 contenders, 3 admitted, commitment equals the cap.
- [x] Distinct attempt accounting, fallback after fixture provider failure, cancellation hold.
- [x] Durable half-open probe, append-only event enforcement, cross-tenant attempt denial.
- [x] Same-workload comparison runner, routing overhead and raw output capture.
- [x] Actual LiteLLM/Ollama comparison: 12 calls per policy, zero errors; scores and latency above.
- [ ] Connected, comparable provider runs with a verified rate-card snapshot and invoice reconciliation.
- [ ] Actual paid-model savings claim: unavailable until the preceding evidence exists.

See [case study](case-study.md) and [interview walkthrough](interview.md).
Official API references: [LiteLLM completion parameters](https://docs.litellm.ai/docs/completion/input),
[retry semantics](https://docs.litellm.ai/docs/routing),
[exceptions](https://docs.litellm.ai/docs/exception_mapping), consulted 2026-09-29.
