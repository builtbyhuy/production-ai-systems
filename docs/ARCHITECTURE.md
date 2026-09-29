# Architecture and ownership

The showcase is a technical-operations copilot: uploaded versioned PDFs support an extractive
answer with verifiable page citations; ambiguous or sensitive work goes to an explicitly
authorized reviewer before a durable idempotent internal action is recorded.

## Boundaries

| State | Owner | Durability and access |
|---|---|---|
| Identity/memberships | API credential resolver; Supabase adapter in connected profile | Server-resolved Principal, explicit tenant membership; headers never authorize |
| Documents/pages/chunks | RAG SQLite authoritative store | Version hashes, physical pages, immutable spans; tombstones/deletion enforced before source access |
| Retrieval indexes | SQLite-vec/FTS5, selectable LanceDB, Qdrant scale adapter | Derived from authoritative content; tenant filter applied before candidate ranking |
| Model artifacts | Explicit local provisioning | Revision/digest/file manifests, outside Git, local-only generation URLs |
| Approvals/checkpoints | ApprovalService + LangGraph SqliteSaver | Exact action/context/reviewer/expiry binding; database decision transaction, durable downstream idempotency |
| Jobs/outbox | JobService + Celery/Redis | Committed acceptance and outbox, leased attempts, bounded retries, dead-letter/replay |
| Usage/budgets | Router ledger and billable-usage ledger | Integer microdollars, append-only corrections, atomic reservation, unknown usage held visibly |
| Memory | Versioned memory service, Redis and vector adapter | Provenance/confidence/TTL/capacity, deterministic version conflict rules, tombstones against stale resurrection |
| Telemetry | OTel spans + Prometheus; optional native/Compose stack | PII redaction before export, bounded metric labels, request IDs only in traces/logs |
| Release evidence | Evaluator + manifest recorder | Frozen inputs and thresholds, commit/dirty/source digest, actual exits and outputs, explicit profile eligibility |

## Request path

1. Resolve the bearer credential into a trusted principal; check role and shared limits.
2. Validate input outside the model, then retrieve only authorized active document versions.
3. Fuse lexical/dense ranks and run the local cross-encoder on candidates.
4. Quarantine instruction-like source content. The local model selects complete source
   sentences using constrained short IDs; the server binds exact source spans. Explicit
   document summaries instead assemble page-balanced source excerpts, at most eight
   complete assertions, and report `real_inference=false` for that generation route.
5. Validate source existence, page/span and complete extractive support. Preserve detected
   contradictions; abstain when required evidence is missing or invalid.
6. Filter protected output before SSE delivery. The UI gets stable message IDs and explicit
   data/citation events. Cancellation stops delivery; adapter limits determine provider cancellation.
7. A proposed action becomes a durable approval record. Decision and execution revalidate
   tenant/reviewer/action/context, runtime kill switches and downstream idempotency.

## Deliberate tradeoffs

SQLite is appropriate for this small functional showcase and serializes contested writes.
It is not presented as a high-write multi-region database. The default vector store uses
SQLite-vec; LanceDB is a separately tested alternative, not another always-on copy of state.
Qdrant and Redis have explicit profile boundaries and separate persistence behavior.

The answer policy is deliberately extractive. It proves grounding/provenance engineering;
it does not establish arbitrary paraphrase entailment or broad-domain natural-language quality.
An initial free-form quote schema produced invalid multi-sentence citations in a real Qwen
run; the report is retained. Constrained source selection keeps the same strict validator.
An actual 144-case run then exposed omissions in all twelve document summaries. The
separate summary route now discloses its retrieved-excerpt scope instead of claiming
model-generated synthesis. Frozen expected answers and release thresholds were unchanged.

SSE output is buffered until complete protected output passes validation. This means the UI
streams validated text and measures first display separately from provider TTFT. It cannot
claim unrestricted live provider-token output with equivalent full-message safety checks.

RAGAS and CrewAI use isolated environments where their dependency families conflict with the
modern application graph. Default fixture tests never masquerade as model training or hosted
integration evidence. Every project remains incomplete until its own acceptance obligations pass.

## Deployment boundary

The native local profile and Compose/Kubernetes profiles share contracts, not identical
operational guarantees. RLS, webhook records, durable broker recovery, dashboards, sandbox
isolation and rollout drills each require their named dependencies and their own evidence.
The available execution host denies the additional sandbox boundary needed for untrusted
submissions. Execution remains disabled; no temporary-directory subprocess is called secure.
