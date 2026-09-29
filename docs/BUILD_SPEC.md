# Build My Production AI Systems Portfolio

You are my lead AI engineer and implementation partner. Build the 18 projects specified below into a coherent, reproducible engineering portfolio. Work in the filesystem, run the software, diagnose failures, and capture evidence. Planning is the first step; executable systems are the deliverable.

The goal is to demonstrate that I can design, ship, operate, evaluate, secure, and explain AI systems. Every project must demonstrate a distinct capability through working behavior, meaningful failure tests, and reproducible results.

## 1. Scope and operating rules

- Preserve all 18 projects. Use a monorepo named `production-ai-systems` by default, with shared implementations where appropriate and an independently runnable demonstration for each project. A shared component can support several projects, but each needs distinct acceptance evidence.
- Use a narrow integrated showcase: a technical-operations copilot that answers from versioned PDFs, investigates unresolved questions, drafts an action, and requests human approval before execution. Specialized training, inference, and benchmark projects may remain separate applications.
- Build one working vertical slice first. Keep the full backlog visible; implement additional services and directories when their phase begins.
- Inspect existing repository instructions and user changes before editing. If the current directory belongs to an unrelated project, create an isolated project directory. Preserve unrelated work, global configuration, and existing history.
- Resolve routine engineering choices yourself. Ask only when a missing decision materially changes scope, access, cost, or an irreversible action. Reuse decisions and authorizations already provided.
- Default to no new paid usage. Check available hardware, storage, models, and credentials. Use local models and test-mode integrations where appropriate. Credentials alone do not establish a spending budget.
- Prepare access-dependent deployments, public submissions, and billing actions as concrete, reviewable artifacts. Execute them when the target and authorization are established. Continue independent implementation when a specific external action is blocked.
- Use synthetic or properly licensed public data. Keep secrets and private documents out of source control, telemetry, screenshots, and published examples.
- Research current official documentation before implementing unfamiliar APIs. Pin compatible dependencies and model revisions. Record important compatibility decisions and source URLs; never invent APIs or install every framework into one conflicting environment.
- Use parallel agents for independent, bounded work when available. Give them separate ownership, share contracts first, and keep concurrency within the machine’s resources. Review and integrate their changes.
- A failure is a result to investigate. Never invent outputs, weaken tests to obtain a green run, quietly skip required gates, or describe unexecuted work as verified.

## 2. Preflight and a workspace that stays manageable

Begin by checking OS, architecture, RAM, disk, available accelerator/VRAM, Python, Node, container runtime, Git, and existing project state. Read a bounded file inventory before opening files. Do not recursively ingest unrelated workspaces.

Create a concise capability matrix covering:

- What can run on this machine now.
- Which dependencies or model downloads are needed, including approximate sizes.
- What needs credentials, network access, stronger hardware, or an approved budget.
- Which execution profiles can demonstrate each project.

Provide these profiles:

1. **Fixture:** deterministic component and contract tests; no claim of real model quality.
2. **Local:** actual local inference, embeddings, reranking, storage, and application behavior.
3. **Connected:** real external integrations using authorized accounts, test modes, and explicit budgets.
4. **Deployment/performance:** named hardware or cluster, declared load, operational tests, and measured results.

Choose resource-appropriate model sizes and concurrency. Large model downloads and heavy service profiles must be deliberate. Once dependencies and models are provisioned, the offline profile must run with external network access disabled, including telemetry and hidden runtime downloads.

Keep root `AGENTS.md` short, preferably under 120 lines. Maintain a compact `STATE.md` with completed work, current blocker, and next command. Load project-specific specifications only when working on them. Exclude dependencies, models, indexes, build outputs, and raw logs from routine agent context and Git. Use scoped ignore files supported by the actual tools; do not claim that an ignore file universally controls every tool.

## 3. Repository and shared contracts

Create only the structure needed for the active phase, using:

- `apps/` for the integrated UI.
- `services/` for APIs and workers.
- `packages/` for shared contracts and reusable implementations.
- `projects/01-rag-citations` through `projects/18-upstream-contribution` for project documentation, entrypoints, demonstrations, and project-specific tests.
- `evals/` for versioned datasets, evaluators, and baselines.
- `infra/` for Compose, Kubernetes, monitoring, and deployment configuration.
- `docs/` for architecture decisions, threat model, runbooks, and case studies.
- `artifacts/` for generated evidence, normally ignored except small, reviewed reports.

Use typed Python/FastAPI and TypeScript/Next.js where appropriate. Select compatible runtime versions during preflight, lock dependencies, and isolate specialized ML/framework environments when necessary.

Provide a documented command interface for setup, doctor, development, individual project demos, smoke tests, full evaluations, security checks, and evidence capture. Implement the commands you document. Commands must report failures through meaningful exit codes.

Define shared schemas for identity, document/chunk provenance, citations, model requests/responses, usage events, trace context, jobs, approvals, and evaluation results. Assign clear ownership of durable application state, retrieval indexes, caches, model artifacts, and audit records.

Propagate trusted user/tenant identity and request IDs across services, jobs, checkpoints, memory, and caches. Enforce permissions server-side. Treat retrieved documents, tool output, and remembered content as untrusted data.

## 4. The 18 project specifications

### P01 — Production RAG with Citations

**Stack:** LangGraph, SQLite, sqlite-vec, SQLite FTS5, and a real cross-encoder reranker.

Build PDF ingestion, page-preserving extraction, chunking, embeddings, lexical and dense retrieval, documented fusion such as reciprocal rank fusion, reranking, answer generation, citation validation, and abstention.

Persist document hash/version, chunk ID, physical PDF page number, printed page label when available, and supporting text spans. Keep citations tied to the document version originally used. Handle replacement, deletion, duplicate uploads, malformed PDFs, and extraction failures. Detect scanned PDFs; implement OCR or explicitly identify that unsupported input.

Verify citations at three levels: the referenced source exists, its page/span is correct, and it supports the associated claim. Surface conflicting sources. Calibrate grounding and abstention on development examples.

**Acceptance:** demonstrate cross-page answers, an unanswerable question, conflicting evidence, an injected instruction inside a PDF, document replacement, and an incorrect citation caught by validation. Compare lexical-only, dense-only, hybrid, and hybrid-plus-reranking retrieval on the same dataset. Capture real model output and actual retrieval/reranking evidence.

### P02 — Cost-Optimized Model Router

**Stack:** LiteLLM, Prometheus, custom routing policy, persistent usage ledger.

Route requests using task type, context length, required capabilities, quality expectations, budget, and operational conditions. Implement a cheap default, justified escalation, bounded fallbacks, timeouts, and a circuit breaker. Record a concise routing decision without exposing private model reasoning.

Track every provider attempt, retry, cache use, input/output usage, pricing version, and parent request. Separate reserved budget, estimated cost, reported usage, and reconciled cost. Unknown usage must remain visibly unknown. Include routing overhead in comparisons.

Enforce budgets atomically under concurrency. Persist the information needed for spend enforcement rather than assuming an in-memory counter or database-less configuration is sufficient.

**Acceptance:** compare always-cheap, always-expensive, and routed policies on the same held-out workload; report quality, cost, and latency. Demonstrate provider failure, concurrent requests near a budget cap, cancellation, and retry accounting. Label prices applied to local outputs as simulations; claim actual savings only from comparable measured runs.

### P03 — Multi-Agent Research System

**Stack:** CrewAI and a durable audit trail.

Implement supervisor, researcher, writer, and fact-checker roles with explicit task schemas, tool permissions, budgets, deadlines, and bounded revision rounds. Make CrewAI perform substantive orchestration.

Collect evidence with source identity, retrieval time, relevant passage, and claim linkage. The fact-checker must examine the evidence and can reject the draft. Define consensus as an explicit evidence-based acceptance rule. Preserve unresolved contradictions and support an insufficient-evidence outcome.

Persist workflow state and audit records. Require human approval for designated final actions, integrating P15 where useful. Support a local evidence corpus for offline demonstrations and a separate authorized web-research mode.

**Acceptance:** an unsupported but plausible claim is rejected; conflicting sources remain visible; malicious source instructions do not gain tool permissions; a missing agent or exhausted budget terminates predictably; rejection and approval paths work. Show an actual end-to-end CrewAI execution and its audit trail.

### P04 — Automated Eval Harness

**Stack:** DeepEval, RAGAS, LangSmith integration, pytest, local result storage.

Build at least 120 distinct golden cases with provenance and expected outcomes. Include answerable, unanswerable, contradictory, cross-page, citation, adversarial, authorization, malformed-input, and failure-recovery cases. Document coverage; duplicate paraphrases alone do not create meaningful coverage.

Separate development data, training data, release regression cases, and an audit holdout. Disclose repeated holdout exposure. Prevent expected answers from entering retrieval, prompts, or training through test fixtures.

Use DeepEval and RAGAS for explicitly assigned metrics. Implement real LangSmith dataset/run integration when configured; retain complete local reports and a credential-free workflow. Any unavailable integration remains unverified.

Version code, prompts, models, embeddings, datasets, judge configuration, and baselines. Calibrate model judges against reviewed examples. Use deterministic assertions for authorization, page identity, schemas, and accounting.

Each release gate declares its target profile and required services before execution. Local releases run the required 100+ cases against actual local models and dependencies. External integrations outside that profile remain unverified. Fixture runs cannot substitute for model-quality or integration evidence. Profile selection cannot silently remove a project’s full acceptance obligations.

**Acceptance:** every deployment candidate runs the required 100+ case suite; a deliberately degraded candidate blocks deployment. Report per-category quality, retrieval, grounding, latency, cost, and trends. A missing required dependency, skipped mandatory test, judge error, or incomplete required evidence blocks that release.

### P05 — Real-Time Observability Dashboard

**Stack:** OpenTelemetry, Grafana, Prometheus, a trace backend such as Tempo or Jaeger, and alert delivery to a local/test destination.

Instrument UI/API requests, retrieval, reranking, routing, model calls, approval transitions, and background work. Preserve trace context across queue boundaries.

Show request volume, time to first token, end-to-end p50/p95/p99 latency, provider errors, token usage, cost estimates, queue depth, retries, and relevant quality signals. Keep histogram definitions and units consistent. Bound metric-label cardinality; request identifiers belong in traces or logs.

Provide provisioned dashboards and alert rules for errors, latency, budget use, and a defined anomaly baseline. Redact sensitive data before exporting telemetry. Explain sampling and retention.

**Acceptance:** generate traffic through the actual application, trigger a slow request and an error, inspect a distributed trace, and observe an alert firing and resolving. Compare ledger costs with dashboard totals. Dashboard fixtures may support UI tests but cannot satisfy this project’s demonstration.

### P06 — Security Guardrail Middleware

**Stack:** Guardrails AI, custom rules, server-side policy enforcement, isolated execution worker.

Implement input/output schema validation, injection-risk handling, PII redaction, output filtering, tool allowlists, argument validation, and authorization outside the model. Integrate Guardrails AI in the enforcement path.

Enforce configurable per-principal and per-tenant request-rate, burst, and concurrency limits using shared state across API workers. Test simultaneous requests, consistent HTTP 429 rejection, and applicable retry information.

Threat-model uploaded documents, retrieved content, memory, tool results, HTML rendering, outbound URLs, and execution requests. Include SSRF controls for fetchers. Define fail-safe behavior when a required validator is unavailable. Report both missed attacks and false positives.

For code execution, define filesystem, credential, network, privilege, CPU, memory, process, and time boundaries. Use an appropriate sandbox; document shared-kernel limits and stronger isolation requirements. A normal subprocess or temporary directory is insufficient. Disable execution if its required boundary cannot be established.

**Acceptance:** run adversarial and benign cases; demonstrate blocked cross-tenant/tool access, PII handling, denied file/network access, and resource limits. For streaming, enforce the declared filtering policy before protected output reaches the user. State the tested security boundary and observed weaknesses.

### P07 — Local-First Development Environment

**Stack:** Ollama, FastAPI, SQLite/sqlite-vec, a selectable LanceDB adapter, Docker Compose.

Resolve the two local storage choices explicitly: SQLite/sqlite-vec is the default; LanceDB is a separate selectable implementation behind the same retrieval contract. Deliver both adapters, with only the selected backend running by default. They have distinct storage and migration implementations.

Run real local generation, embeddings, and reranking. Provide models/fixture setup, persisted volumes, health checks, seeds, resource limits, teardown, and troubleshooting. On platforms where native model serving is preferable, support a documented native Ollama service with containerized application components.

Keep local and connected architectures aligned through contracts. Document differences in ranking, concurrency, durability, auth, and deployment behavior.

**Acceptance:** perform setup from a clean project environment, provision dependencies, disable external network access, and complete ingestion → retrieval → generation → citation. Run CRUD, filtering, and authorization conformance tests against both local retrieval adapters. Record RAM/disk consumption. Claim zero API charges only for the verified local profile.

### P08 — Streaming Copilot UI

**Stack:** Next.js and Vercel AI SDK.

Build an accessible interface for document upload, conversations, streamed responses, page citations, source inspection, pending approvals, and explicit partial/error states. Provide useful loading, empty, failure, and retry behavior.

Choose and implement a stream protocol compatible with the pinned AI SDK version and Python backend. Define typed events, stable message IDs, cancellation, bounded buffering, and reconciliation of optimistic UI state with server state.

Handle disconnects before and during generation, malformed events, slow consumers, provider timeout, and retry. Propagate cancellation to downstream work where supported; disclose when a provider continues producing billable output. Sanitize rendered content and links.

**Acceptance:** browser tests verify first-token display, cancellation, page citation navigation, retry without duplicated messages/actions, and recovery after a forced failure. Inspect the running UI at desktop and mobile widths with keyboard navigation. Screenshots and recordings must come from the actual application.

### P09 — Fine-Tuning Pipeline with LoRA

**Stack:** Hugging Face PEFT, Transformers, Datasets, and TRL for SFT/DPO.

Implement data preparation, instruction-example validation, preference-pair validation, deduplication, source-based splits, tokenization, LoRA SFT, DPO, checkpointing, adapter export/reload, and evaluation.

Record data/model licenses and revisions, seeds, configuration, compute requirements, training logs, and dataset hashes. Preference pairs need a defensible chosen/rejected rationale. Prevent contamination from release and benchmark test sets.

Compare base, SFT, and DPO models on identical held-out domain and general-capability suites. Define retention tolerances prospectively; mitigate forgetting through data design, training controls, checkpoint selection, and rejected regressions. Do not promise that LoRA prevents forgetting.

**Acceptance:** run a genuine small training smoke test when feasible, reload the adapter, and evaluate it. Keep that result distinct from substantive training. Full completion requires actual before/after evidence for the configured stages. If hardware is insufficient, finish runnable configurations and validation, report the exact prerequisite, and leave performance/quality claims unverified.

### P10 — Multi-Tenant SaaS Agent

**Stack:** Supabase, Stripe test mode, LangGraph.

Implement authentication, tenant membership, roles, server-side tenant resolution, database/storage policies, tenant-aware retrieval, per-tenant rate limits, usage metering, subscription state, and audit access.

Maintain a durable append-only usage ledger with correction events and billing reconciliation. Define billable units separately from underlying provider costs. Verify webhook signatures and handle duplicate/out-of-order events. Prevent privileged workers or administrative credentials from unintentionally bypassing tenant boundaries.

Test isolation across documents, citations, storage URLs, vectors, conversations, caches, jobs, memory, checkpoints, exports, and usage. A client-supplied tenant ID must never authorize access.

**Acceptance:** use two real authenticated test tenants; tenant A referencing valid tenant B resource IDs must fail throughout the system. Demonstrate concurrent quota enforcement, webhook replay, subscription changes, worker authorization, and reconciliation with Stripe test-mode records. A local billing simulator is useful for development; the real Stripe integration retains its own verification status.

### P11 — CI/CD for AI Systems

**Stack:** GitHub Actions, Argo CD, Argo Rollouts, Prometheus, feature flags.

Implement lint/type checks, relevant tests, container builds, dependency/secret checks, immutable artifacts, full release evaluations, staging verification, and controlled deployment.

Use Argo CD for Git reconciliation and Argo Rollouts for progressive delivery. Define traffic routing, canary stages, analysis windows, minimum observations, failure thresholds, missing-data handling, promotion, and rollback ownership.

Version application images, prompts, model configuration, embeddings/index schema, and feature flags together. Address backward-compatible migrations and persisted graph/checkpoint compatibility. Explain how failed desired state is handled in Git.

Implement a runtime feature flag and an emergency disable switch for an agent capability. Define caching and propagation behavior; verify that disabling the capability stops new affected actions across API and worker processes.

**Acceptance:** on an actual test cluster, promote a passing candidate and introduce a deliberately quality-degraded one. Show analysis failure, traffic returning to the stable version, and recovery verification. Missing quality measurements must prevent promotion. Manifests or dry runs alone establish configuration validity; deployment and rollback verification require an executed drill.

### P12 — Vector Database at Scale

**Stack:** Qdrant by default; use Weaviate only with a documented reason.

Implement dense/sparse hybrid retrieval, metadata filtering, tenant-aware access, batch ingestion, embedding caching, index configuration, deletion/update consistency, and versioned reindexing.

Key embedding caches by content and embedding configuration, with authorization-aware access. Document dimensions, distance metric, fusion strategy, filter behavior, and re-embedding triggers. Keep the authoritative document store distinct from derived indexes.

Provide a reproducible corpus generator and benchmark profiles for different dataset sizes. Measure recall/ranking quality, throughput, p50/p95/p99 latency, RAM/disk, warm/cold state, and concurrency on named hardware.

**Acceptance:** compare meaningful index/cache configurations, prove filtering and update/delete consistency, and restore a backup into a fresh instance. Verify vectors, metadata, documents, and tenant boundaries after restoration. Report only dataset sizes and loads actually exercised; make larger runs explicitly unexecuted targets.

### P13 — Agent Memory System

**Stack:** Redis and a vector database, reusing P12 where appropriate.

Separate short-term conversation buffers, durable workflow checkpoints, and long-term memory. Implement memory creation, retrieval, provenance, confidence, versioning, compression, TTL, capacity limits, eviction, correction, deletion, and cross-session synchronization.

Define deterministic conflict handling for concurrent sessions and source changes. Keep permissions outside recalled content. Preserve references through lossy compression and retain enough provenance to challenge a stored assertion.

Propagate deletion/correction through vectors, caches, and summaries. Use deletion/version markers or another explicit mechanism to prevent stale sessions from restoring removed information.

**Acceptance:** test restart recall, concurrent updates, expiry, eviction, correction, poisoned memory, cross-tenant lookup, and deletion followed by stale-session synchronization. Compare task success and context/token consumption with memory enabled and disabled. Show a case where irrelevant or low-confidence memory is deliberately excluded.

### P14 — Production Inference Server

**Stack:** vLLM and Kubernetes.

Check current hardware/backend compatibility; do not assume all laptops, accelerators, or quantization formats behave alike. Provide a supported functional profile and a separate deployment/performance profile.

Implement model serving, continuous batching, KV/prefix-cache configuration, supported quantization, readiness/warmup, concurrency limits, admission control, streaming/cancellation, graceful shutdown, load balancing, and observable failures.

Measure time to first token, intertoken latency, throughput, p95/p99 latency, memory use, errors/OOMs, and queueing under declared input/output lengths and concurrency. Record hardware, runtime, model revision, quantization, and warmup.

**Acceptance:** run comparative batching/cache/quantization experiments where supported and quantify quality/performance tradeoffs. Demonstrate load balancing and recovery when a serving instance fails. Configuration-only checks and small functional runs remain separate from cluster and performance claims; unavailable hardware is a precise blocker, never a fabricated benchmark.

### P15 — Human-in-the-Loop Workflow

**Stack:** LangGraph and custom approval UI.

Detect uncertainty using defined evidence/validation signals, calibrated on development data. Trigger review for insufficient grounding, unresolved conflicts, sensitive actions, or policy requirements.

Persist graph state and approval records. Bind approval to tenant, authorized reviewer, exact action/arguments, source/context version, expiry, and idempotency key. Revalidate authorization and relevant context before execution. Support approve, reject, edit-and-reapprove, cancel, expiry, and restart/resume.

Account for interrupted-node replay. Isolate side effects and make them idempotent under retries and process crashes. A thread ID is a lookup identifier, not authorization.

**Acceptance:** restart while paused, then resume safely; reject wrong-user/tenant, expired, changed-action, and stale-context approvals. Test concurrent decisions and replay after an external effect succeeds. Demonstrate at most one visible effect within the documented downstream idempotency contract and record the full action history.

### P16 — Agentic Automation Pipeline

**Stack:** FastAPI, Celery, persistent broker, durable job storage.

Implement signed webhook ingestion, durable acceptance, asynchronous execution, explicit job states, schema validation, bounded retries, exponential backoff with jitter, cancellation, dead-letter handling, and safe replay.

Use persistent idempotency keys and uniqueness constraints. Address the gap between recording an event and publishing a job using an outbox or justified equivalent. Distinguish retryable failures, permanent failures, and uncertain external outcomes.

Carry identity and trace context into jobs. Design downstream effects for idempotent retry and reconciliation; document residual uncertainty when an external system cannot provide that guarantee.

**Acceptance:** deliver duplicate webhooks, terminate a worker at relevant transaction boundaries, simulate provider failure, exhaust retries, and inspect/replay a dead-letter job. Demonstrate crash recovery after an external action succeeds but before local completion is recorded. Bound retries and confirm one poison job does not halt unrelated work.

### P17 — Domain-Specific Benchmark

**Stack:** Custom tooling and pytest.

Choose code as the initial domain: narrowly defined Python/API maintenance or debugging tasks with executable correctness checks. Justify the domain and scoring rubric.

Create at least 100 meaningful, licensed, versioned tasks spanning declared difficulty and failure categories. Include dataset provenance, split policy, contamination limitations, scoring rules, baseline implementations, submission format, and reproducibility instructions.

Run untrusted submissions through the sandbox boundary from P06. Validate submissions and resource limits. Maintain a leaderboard generated from actual scored runs, with model/version, configuration, compute, cost, and uncertainty where relevant.

**Acceptance:** evaluate real available baselines, reject a malformed or invalid submission, reproduce scores, and verify the leaderboard matches raw results. Prepare publication and contribution instructions; publish when a target is authorized. Track actual community use separately. External adoption is a goal whose evidence must come from real users.

### P18 — Open Source Contribution

**Stack:** One of LangGraph, CrewAI, or LlamaIndex.

Find a genuine, current issue encountered during this work or a clearly useful documented gap. Inspect upstream contribution rules, existing issues/PRs, tests, style, and maintainer expectations before choosing scope.

Prefer a small, credible fix or feature with a reproduction and focused regression test. For a documentation contribution, validate the corrected instructions/example against the relevant version. Preserve upstream licensing and attribution.

Prepare the patch, tests, focused explanation, and a PR description stating the problem, change, behavior, and verification. Use the authorized account/target when publication is permitted.

**Acceptance:** reproduce the original issue or documentation failure, demonstrate the correction, and run relevant upstream checks. Record separate states for patch prepared, PR submitted, maintainer response, and merge. Link actual public evidence when available. Never invent acceptance or make unrelated contributions just to increase the count.

## 5. Build sequence

**Phase A — Foundation and first vertical slice:** preflight, shared contracts, minimal P07/P01/P08, initial P04 cases, and essential identity/telemetry/security boundaries. Demonstrate real PDF upload → hybrid retrieval → reranking → streamed answer → working page citation, plus abstention and one failure path.

**Phase B — Reliability and proof:** complete P01, P02, P04, P05, P06, P07, and P08 around the working slice. Establish the complete release gate and genuine evidence capture.

**Phase C — Stateful workflows:** complete P15/P16, then P03/P10/P12/P13. Reuse shared contracts and add meaningful isolation, replay, and recovery evidence.

**Phase D — Advanced operations and learning:** complete P17, P09, P14, and P11 according to available resources. Pursue P18 when a real upstream opportunity is established. Collect access/hardware blockers early so independent work continues.

Do not stop permanently after the first successful demo. Work through the full backlog. If a project is blocked, finish its independent work, record the missing prerequisite and verification command, then proceed to the next feasible project.

## 6. Acceptance, evidence, and honest status

Track implementation and verification separately in a project ledger. For each project, show:

- Implementation: planned / in progress / implemented.
- Evidence: fixture verified / real dependency verified / deployment or load profile verified.
- Blocker: none or a specific missing prerequisite.
- Acceptance criteria: pass / fail / not run, with evidence links.

Implemented-but-unverified work stays visibly incomplete. A skipped mandatory gate is not a pass. An overall project cannot be marked complete while required acceptance evidence is missing.

Before tuning, define numerical quality/performance thresholds in a versioned configuration. Record baseline measurements and justify thresholds for the workload. If initial performance misses the target, report and fix it. Changing a target requires a visible rationale and comparison, not silent relaxation.

Use meaningful unit, contract, integration, browser, adversarial, and recovery tests where they resolve actual risks. Avoid tests that merely mirror an implementation or assert that a dependency was imported. Real named dependencies must appear in the project’s verification path.

Every evidence run must include the tested commit, dirty-tree status where applicable, timestamp, exact command, profile, relevant dependency/model versions, dataset hashes, configuration, exit status, and measured outputs. Track stochastic variability. Redact secrets and sensitive content.

Every project must include:

1. A concise README: problem, scope, stack, architecture, setup, demo command, verification commands, and limitations.
2. A repeatable demo showing the capability and a meaningful failure/recovery case.
3. Tests and an acceptance checklist tied to evidence.
4. A short case study explaining design decisions, rejected alternatives, measured results, and limits.
5. An interview walkthrough explaining the critical code path, tradeoffs, and what I should be able to modify myself.

Publish a small portfolio index that links each project to its actual demo, code, evidence, and case study. Use accurate readiness labels. Never invent users, clients, revenue, benchmark superiority, security guarantees, production operation, or upstream acceptance.

## 7. Start now and report concretely

Begin with the environment/repository preflight, a compact dependency plan, and the first working slice. Proceed directly into implementation after planning.

After each milestone, report what now works, the evidence, the important failure caught or limitation found, and the next implementation step. Keep communication concise while continuing the work.

Before any context/session boundary, update `STATE.md` with exact progress, blockers, changed files, last verification commands, and the next executable action. Maintain small reproducible commits when repository policy allows. Never claim work continued after the session ended.

Your completion report must include the 18-project status matrix, working launch commands, evidence locations, significant measured findings, unresolved prerequisites, and the precise next action for anything still incomplete.

### Official documentation starting points

Verify the relevant current version when implementing:

- [LangGraph interrupts and persistence](https://docs.langchain.com/oss/python/langgraph/interrupts)
- [sqlite-vec](https://github.com/asg017/sqlite-vec)
- [SQLite FTS5](https://www.sqlite.org/fts5.html)
- [LiteLLM spend tracking](https://docs.litellm.ai/docs/proxy/cost_tracking)
- [Vercel AI SDK stream protocol](https://ai-sdk.dev/docs/ai-sdk-ui/stream-protocol)
- [Hugging Face TRL DPO](https://huggingface.co/docs/trl/en/dpo_trainer)
- [Supabase RLS](https://supabase.com/docs/guides/database/postgres/row-level-security)
- [Stripe webhooks](https://docs.stripe.com/webhooks)
- [Argo Rollouts](https://argoproj.github.io/argo-rollouts/)
- [vLLM installation](https://docs.vllm.ai/en/stable/getting_started/installation/)