# Eighteen-project acceptance ledger

All 18 implementation tracks are present. Results below separate implemented code, measured local contracts, model quality and unexecuted integrations. The complete portfolio is not accepted for production deployment.

Implementation and evidence are separate. `implemented` means the declared code and
configuration exist; it does not mean the full project is accepted or deployed.
Criteria use PASS, FAIL or NOT RUN. A project with a failed or unexecuted required
criterion remains incomplete. Fixture output never establishes actual model quality.

See [VERIFICATION.md](VERIFICATION.md) for integrated run identities, limitations and
the final evidence index. Earlier observations retain their original dirty/unborn Git
metadata. They are not retroactively relabeled as clean-commit runs.

| Project | Implementation | Evidence exercised | Acceptance | Remaining requirement |
|---|---|---|---|---|
| [P01 · RAG with citations](../projects/01-rag-citations/README.md) | implemented | fixture + actual models/storage | PASS within local acceptance scope | None for the measured local lifecycle; broad-domain grounding and scanned PDFs remain outside this acceptance scope. |
| [P02 · Model router](../projects/02-model-router/README.md) | implemented | fixture + actual two-model comparison | PARTIAL | No connected invoice comparison or measured paid-provider savings. |
| [P03 · Multi-agent research](../projects/03-multi-agent-research/README.md) | implemented | native LangGraph + actual local Qwen case | INCOMPLETE | Live web and unseen/general research quality remain unverified. |
| [P04 · Evaluation harness](../projects/04-eval-harness/README.md) | implemented | fixture + clean-commit actual local release/degraded/audit | PARTIAL: local regression accepted | LangSmith integration not run; two evaluator packages retain reported advisories; narrow synthetic exact metrics do not establish general quality. |
| [P05 · Observability](../projects/05-observability/README.md) | implemented | native monitoring deployment profile | PASS within declared native drill scope | Container deployment, mature anomaly baseline and paid invoice reconciliation unverified. |
| [P06 · Security middleware](../projects/06-security-guardrails/README.md) | implemented | fixture + actual Guardrails and HTTP | INCOMPLETE | Untrusted-code sandbox unavailable; isolated Guardrails dependency advisories. |
| [P07 · Local-first environment](../projects/07-local-first/README.md) | implemented | actual models/storage + native offline | PARTIAL | Docker unavailable; Compose build/launch/offline acceptance not executed. |
| [P08 · Streaming copilot](../projects/08-streaming-ui/README.md) | implemented | API + desktop/mobile + actual-model browser | PASS within local UI scope | Provider cancellation is adapter-limited; process-crash pending-message reconciliation and hosted operation remain open. |
| [P09 · LoRA SFT/DPO](../projects/09-lora-training/README.md) | implemented | actual CPU training smoke | INCOMPLETE | Tiny random model remains0% exact match; retention gate rejected. Larger independent evaluation, useful training, crash-resume and dependency remediation remain. |
| [P10 · Multi-tenant SaaS](../projects/10-multi-tenant-saas/README.md) | implemented | local + real SDK contracts | INCOMPLETE | No Supabase test project/two real JWTs or Stripe test account/customer/meter mapping. |
| [P11 · CI/CD and rollout](../projects/11-cicd/README.md) | implemented | contract tests + parsed configuration | INCOMPLETE | No GitHub repository/Actions execution, Docker/cluster/registry target; isolated dependency advisories prevent whole-repo supply-chain pass. |
| [P12 · Vector database](../projects/12-vector-database/README.md) | implemented | actual Qdrant local; synthetic hash embeddings at100/1000/10000 docs | PARTIAL | 10k hybrid recall@1=.21; semantic-model, Qdrant server/HNSW and concurrent-load acceptance not run. |
| [P13 · Agent memory](../projects/13-agent-memory/README.md) | implemented | actual Redis/Qdrant + four model calls | PASS within small local acceptance scope | General-task quality/semantic recall and larger workloads unverified. |
| [P14 · Inference server](../projects/14-inference-server/README.md) | implemented | mock contracts + actual CLI/startup attempt | INCOMPLETE | AF_UNIX creation denied before actual serving; no GPU/cluster for comparisons. |
| [P15 · Human approval](../projects/15-human-approval/README.md) | implemented | actual LangGraph/SQLite + UI | PARTIAL | Grounding0.85 review rule is uncalibrated; external providers need a separately verified idempotency/reconciliation contract. |
| [P16 · Automation pipeline](../projects/16-automation-pipeline/README.md) | implemented | actual Redis/Celery multiprocess recovery | PASS within native pipeline scope | Webhook router requires tenant signing configuration before mounting; external-effect and hosted deployment unverified. |
| [P17 · Code benchmark](../projects/17-domain-benchmark/README.md) | implemented | trusted corpus/controller QA | INCOMPLETE | Missing P06 sandbox; zero actual baseline scores/leaderboard rows; no publication target/community evidence. |
| [P18 · Upstream contribution](../projects/18-upstream-contribution/README.md) | implemented | actual upstream reproduction/patched tests | PARTIAL | Full upstream development checks, approved issue/assignment and PR submission not done. |

## P01 — RAG with citations

PDF extraction, immutable page/span/version provenance, LangGraph, sqlite-vec/FTS5 fusion, actual CrossEncoder, constrained source selection, explicit excerpt summaries and abstention.

- **PASS — Cross-page, abstention, conflicts, injection and lifecycle**: 13/13 actual local lifecycle checks after constrained-selection prompt correction; original failed7/13 preserved. Evidence: [local-sqlite-selection-v2.json](../projects/01-rag-citations/evidence/local-sqlite-selection-v2.json).
- **PASS — Retrieval comparison**: 16 frozen queries: lexical recall@5=.9375; dense/hybrid/rerank=1.0. Reranking increased latency without a ranking gain. Evidence: [local-retrieval.json](../projects/01-rag-citations/evidence/local-retrieval.json).
- **PASS — Versioned citations and tenant/deletion checks**: Real SQLite and LanceDB contracts; physical pages and exact complete source spans enforced. Scanned PDFs are explicitly unsupported. Evidence: [contract-tests.json](../projects/07-local-first/evidence/contract-tests.json).
- **PASS — Integrated clean-commit regression**: 144/144 local-profile cases at c7b8; 56 actual Qwen responses, 16 deterministic summaries, 72 contract/abstention cases. See P04 for full scope. Evidence: [release-local-final.json](../artifacts/evals/release-local-final.json).

**Next action:** Use the frozen source as a baseline for a larger independently reviewed corpus; keep the initial development thresholds and extractive-summary policy explicit.

```bash
.venv/bin/python scripts/with_local_models.py -- .venv/bin/python -m pais eval --profile local --suite release --output artifacts/evals/release-local.json
```


## P02 — Model router

LiteLLM routing, capability/context constraints, bounded fallback and circuit breaking, persistent integer budget reservations, unknown usage holds and attempt-level reconciliation.

- **PASS — Same-workload policy comparison**: 12 questions each: cheap4/12, expensive6/12, routed4/12. Mean seconds=.801/2.084/1.054; p95=2.036/5.800/2.608. Local API rates zero; no savings claim. Evidence: [p02-router-local.json](../artifacts/p02-router-local.json).
- **PASS — Retries, cancellation and concurrent budget enforcement**: Three retry/fallback attempts recorded, cancelled usage remains held;24 simultaneous admissions accept3 at declared429 micro-USD simulated cap. Evidence: [p02-router-local.json](../artifacts/p02-router-local.json).
- **NOT RUN — Connected invoice reconciliation and dollar savings**: Requires authorized account, live rate-card identity and explicit spending budget.

**Next action:** Choose an authorized comparable provider workload and versioned price card before a paid comparison; local results are already measured.

```bash
.venv/bin/python scripts/with_local_models.py -- .venv/bin/python -m pais demo 02 --profile local --output artifacts/p02-local.json
```


## P03 — Multi-agent research

Four native LangGraph roles and typed host tools, evidence-linked fact checking, contradictions, source quarantine, bounded calls/deadlines/revisions, durable audit and P15 handoff; explicit authorized web mode.

- **PASS — Current native LangGraph orchestration and rejection/approval contracts**: Eleven isolated and six core checks passed, including a fresh frozen install. CrewAI/ChromaDB removed through normal resolution; existing rejection and approval assertions preserved. Evidence: [test_langgraph.py](../projects/03-multi-agent-research/test_langgraph.py), [test_research.py](../tests/test_research.py).
- **PASS — Current actual local Qwen completing bounded research and local approval**: Clean10e53e8 completed four real model responses/two tools in6.91s; P15 approval recorded a durable local effect with external_delivery=false. This is one curated evidence case, not unseen research quality. Evidence: [functional-verification-20260930.json](../docs/functional-verification-20260930.json), [FUNCTIONAL_VERIFICATION.md](../docs/FUNCTIONAL_VERIFICATION.md).
- **PASS — Historical CrewAI orchestration and rejection/approval paths**: Five isolated real-library tests exercise four roles, tools, evidence rejection, malicious sources and budget termination; model responses deterministic. Final clean-commit five-test run passed; upstream callback-serialization warnings limit native framework checkpoint claims. Evidence: [crewai-tests.json](../artifacts/final/crewai-tests.json), [p03-fixture.json](../artifacts/stateful/p03-fixture.json).
- **FAIL — Historical local model research attempt**: Qwen1.5B received one response, timed out on call2 after70.02s, executed zero tools; no fixture fallback. Evidence: [p03-local-attempt.json](../artifacts/stateful/p03-local-attempt.json).
- **NOT RUN — Authorized live web acquisition**: Bounded pinned HTTPS adapter and controlled-transport contract exist; no live source run.

**Next action:** Evaluate unseen research evidence/model quality separately and provision only reviewed live web targets.

```bash
uv run --no-sync pais demo 03 --profile fixture --output artifacts/p03-langgraph-current.json
```


## P04 — Evaluation harness

144 frozen distinct scenarios, source-separated dev/release/audit data, real DeepEval/RAGAS exact metrics, local reports/trends, optional LangSmith upload and a strict complete-profile gate.

- **PASS — Coverage and real metric execution**: 144 cases across9 categories, plus8 development and8 audit; actual DeepEval custom support and RAGAS exact/string metrics. No model judge. Evidence: [release-local-final.json](../artifacts/evals/release-local-final.json), [release-local-final.metrics.json](../artifacts/evals/release-local-final.metrics.json).
- **FAIL — First actual local release**: 132/144, twelve summary omissions, no errors/skips. Strict thresholds retained; explicit excerpt-summary route now implemented. Evidence: [release-local-first.json](../artifacts/evals/release-local-first.json).
- **PASS — Final clean-commit release and deliberately degraded candidate**: At c7b8, positive144/144 (p95 6366.34ms); degraded96/144 with48 quality failures (p95 6630.03ms), zero errors/skips in either run. Independent P11 binding accepted positive and rejected negative. Evidence: [release-local-final.json](../artifacts/evals/release-local-final.json), [degraded-local-final.json](../artifacts/evals/degraded-local-final.json), [release-binding.json](../artifacts/final/release-binding.json), [degraded-binding.json](../artifacts/final/degraded-binding.json).
- **NOT RUN — LangSmith real dataset/run integration**: Adapter exists, account/key/target not configured.
- **PASS — Small audit execution and exposure disclosure**: 8/8 actual local responses at c7b8, p95 6508.33ms. First actual audit run; same-build synthetic data previously accessed for test/exclusion checks, not an independently blind holdout. Evidence: [audit-local-final.json](../artifacts/evals/audit-local-final.json), [audit-exposures.jsonl](../artifacts/evals/audit-exposures.jsonl).

**Next action:** Preserve c7b8 as the tested baseline; resolve evaluator advisories and run an authorized LangSmith integration. Any new deployment candidate must rerun the full gate.

```bash
.venv/bin/python scripts/with_local_models.py -- .venv/bin/python -m pais eval --profile local --suite release --output artifacts/evals/release-local-final.json
```


## P05 — Observability

OpenTelemetry instrumentation, bounded labels/redaction, provisioned Prometheus/Grafana/Tempo/Alertmanager, durable worker trace propagation, alerts and accounting consistency.

- **PASS — Actual traffic, trace, alerts firing and resolving**: Two alert pairs observed firing/resolved; linked producer/worker Tempo spans and successful real worker;155.3733s drill. Evidence: [p05-native-run.json](../artifacts/p05-native-run.json), [report.json](../artifacts/p05-native-first-pass/report.json), [distributed-trace.json](../artifacts/p05-native-first-pass/distributed-trace.json).
- **PASS — Accounting and dashboard**: Ledger40 micro-USD equals Prometheus40, explicitly simulated prices.12 panels provisioned; screenshot proves first8, lower4 were lazily unrendered. Evidence: [ledger-query.json](../artifacts/p05-native-first-pass/ledger-query.json), [grafana-dashboard.png](../artifacts/p05-native-first-pass/grafana-dashboard.png).
- **PASS — Declared resource bound**: Sampled sum-RSS1,448,546,304 bytes below1536MiB. Original1GiB failure and locale failure preserved; shared pages may double-count. Evidence: [report.json](../artifacts/p05-native-first-pass/report.json).

**Next action:** Review the accepted actual dashboard/trace/alert evidence; execute Compose separately on a Docker host if that deployment is selected.

```bash
.venv/bin/python projects/05-observability/native_drill.py --binaries-dir .tools/monitoring --output artifacts/p05-native-new --max-rss-mib 1536
```


## P06 — Security middleware

Actual Guardrails isolated validation, server-resolved identities, PII filtering, tool/argument policy, DNS-pinned bounded HTTPS and cross-instance admission; rootless Docker execution adapter fails closed.

- **PASS — Real schema/output enforcement and shared limits**: Three Guardrails tests;24 requests across two FastAPI instances admit3 and return21 real429 responses; missing validator fails closed. Evidence: [p06-guardrails-real.json](../artifacts/p06-guardrails-real.json), [guardrails-tests.json](../artifacts/final/guardrails-tests.json).
- **PASS — Injection detector measurement**: Measured twelve examples: TP5,FN2,FP1,TN4. This records two missed attacks and one false alarm; not a comprehensive defense. Evidence: [p06-guardrails-real.json](../artifacts/p06-guardrails-real.json).
- **NOT RUN — Sandbox filesystem/network/CPU/RAM/time/output isolation**: No Docker daemon; namespace/netlink operations denied. Execution stays disabled; no host-subprocess substitute.

**Next action:** Use a reviewed patched-compatible validator environment; on a suitable host provision a rootless Docker/cgroupv2/seccomp boundary and an audited Python image, then run real denial/resource drills.

```bash
.venv/bin/python projects/06-security-guardrails/sandbox_drill.py --enabled --image "$PAIS_SANDBOX_IMAGE" --endpoint "$PAIS_SANDBOX_ENDPOINT" --output artifacts/p06-sandbox/report.json
```


## P07 — Local-first environment

Native CPU Ollama and safetensors CrossEncoder, revision/hash locking, selectable real SQLite/LanceDB, offline checks, resource measurement and prepared container profiles.

- **PASS — Both local storage adapters with actual models**: SQLite13/13 and LanceDB13/13 lifecycle checks. Evidence: [offline-local-sqlite.json](../projects/07-local-first/evidence/offline-local-sqlite.json), [offline-local-lancedb.json](../projects/07-local-first/evidence/offline-local-lancedb.json).
- **PASS — Offline application boundary and resources**: Only loopback routes; proxy variables stripped; direct IPv4/IPv6 egress fails before/after. Corrected app+Ollama sampledRSS1,865,792KiB. Trusted-app profile, not hostile-code isolation. Evidence: [offline-local-sqlite-resources.json](../projects/07-local-first/evidence/offline-local-sqlite-resources.json).
- **NOT RUN — Container deployment/offline profile**: Compose and mandatory security bridge prepared; no Docker runtime.

**Next action:** On a Docker host choose a reviewed base-image digest, regenerate container-specific model paths, build and run the documented Compose acceptance.

```bash
.venv/bin/python projects/07-local-first/offline_acceptance.py --backend sqlite --output artifacts/p07-offline.json
```


## P08 — Streaming copilot

Next.js/AI SDK and FastAPI PDF upload, source inspection, auth/tenant boundaries, persistent conversations, approved actions, stable replay IDs, cancellation and error recovery with accessibility checks.

- **PASS — API and browser failure/recovery contracts**: 262 integrated core checks include20 API tests; fixture browser14/14 at1440x960/390x844, zero skips/flaky cases, clean c7b8. Evidence: [core-tests.json](../artifacts/final/core-tests.json), [browser-evidence.json](../artifacts/ui/browser-evidence.json).
- **PASS — Actual PDF-to-model-to-page browser path**: Clean c7b8 actual local browser1/1: browser first checked display14785ms, server14766.393ms, providerTTFT null. Next buildp57JVxelz6CAGXQnnOrB3. Synthetic test identity; actual model and Guardrails. Evidence: [browser-evidence.json](../artifacts/ui/local/browser-evidence.json), [local-smoke-measurements.json](../artifacts/ui/local/local-smoke-measurements.json).
- **PASS — Citation interaction and keyboard/modal behavior**: Both viewport keyboard/modal contracts pass; actual local extracted page2 source and authenticated PDF blob/page-fragment link verified. Browser PDF renderer itself not inspected by the test. Evidence: [desktop-local-source.png](../artifacts/ui/local/desktop-local-source.png).

**Next action:** Launch the documented API/UI and rerun the browser profiles; preserve first-display versus provider-TTFT distinction.

```bash
.venv/bin/python projects/08-streaming-ui/run_browser_tests.py --profile fixture
```


## P09 — LoRA SFT/DPO

Original licensed data, source-disjoint splits, genuine PEFT/TRL SFT and DPO, checkpoint/export/reload, source exclusion and prospective domain/general retention checks.

- **PASS — Genuine training and exact adapter reload**: 39,456 base parameters/1,024 LoRA;3SFT+3DPO steps; both adapters changed, frozen base retained; reload maximum logit difference0. Evidence: [training-result.json](../artifacts/p09-smoke/training-result.json).
- **FAIL — Before/after domain/general comparison and retention**: Base/SFT/DPO exact match all0%; six held-out cases per suite below declared minimum20; retention rejected. Evidence: [training-result.json](../artifacts/p09-smoke/training-result.json).
- **NOT RUN — Substantive training quality and checkpoint/resume**: Small smoke establishes mechanics, not a useful tuned model; full compute/data/profile remains separate.
- **PASS — Common CLI in the declared isolated training environment**: Missing Pydantic declaration reproduced before training; dependency-only fix committed separately as9f8e. Generic local CLI then completed genuine3-step SFT+3-step DPO with clean source and retention still rejected. Evidence: [p09-local.log](../artifacts/final/p09-local.log), [p09-cli-command.json](../artifacts/final/p09-cli-command.json), [run.json](../artifacts/final/p09-cli/run.json).

**Next action:** Select a licensed pretrained model and reviewed larger held-out source groups, resolve supported runtime advisories, then execute the same stages and retention gate.

```bash
.venv/bin/python -m pais demo 09 --profile local --output artifacts/p09-local.json
```


## P10 — Multi-tenant SaaS

Server-derived memberships and roles, tenant-scoped resource contracts, append-only billable usage/corrections, atomic quotas, Supabase user-JWT/RLS adapters and Stripe test-only webhooks/metering/reconciliation.

- **PASS — Local quota, role, ledger and signature boundaries**: Thirty concurrent quota requests admit ten; cross-tenant/role rejection and immutable correction history; actual Stripe signature/replay/stale/tied-event tests. Evidence: [p10-fixture.json](../artifacts/stateful/p10-fixture.json).
- **NOT RUN — Two real authenticated tenant isolation across remote RLS/storage**: SQL and user-scoped SDK adapters prepared; remote policies not applied or proved.
- **NOT RUN — Stripe test records/subscription/meter reconciliation**: Test-only adapters implemented; real account execution absent.

**Next action:** Review/apply migration.sql in an authorized test project, create two users/resources, then exercise SupabaseTenantAdapter and StripeTestBilling with test credentials and compare remote records.

```bash
.venv/bin/python -m pais demo 10 --profile fixture --output artifacts/p10-fixture.json
```


## P11 — CI/CD and rollout

Pinned GitHub Actions, frozen runtime gates, immutable image/bundle validation, default-disabled capability/emergency flags, ArgoCD/Rollouts/Prometheus configuration and explicit recovery ownership.

- **PASS — Release validation and runtime emergency control**: Clean c7b8 positive full144 accepted with report SHA; same full degraded144 rejected for48 failures. Durable flags enforce emergency-disable on new admissions; no-data canary rejected. Evidence: [test_operations.py](../tests/test_operations.py), [test_operations_inference.py](../tests/test_operations_inference.py), [release-binding.json](../artifacts/final/release-binding.json), [degraded-binding.json](../artifacts/final/degraded-binding.json).
- **FAIL — Dependency scans**: Core audit queried162 of164 entries and reported0 findings, with editable project/CPU Torch skipped; npm production reported0. Eval2, Guardrails4, CrewAI1, training3 and inference1 affected packages remain. Five inference CPU wheels unmatched. Whole production gate not passed. Evidence: [pip-audit-verified.json](../artifacts/pip-audit-verified.json), [pip-audit-eval-final.json](../artifacts/pip-audit-eval-final.json), [pip-audit-security.json](../artifacts/pip-audit-security.json), [pip-audit-research.json](../artifacts/pip-audit-research.json), [pip-audit-training-final.json](../artifacts/pip-audit-training-final.json), [pip-audit-inference.json](../artifacts/pip-audit-inference.json), [npm-audit-production.json](../artifacts/npm-audit-production.json).
- **NOT RUN — Actual image build, Actions, promotion and rollback**: Templates/tests are not cluster proof; use one pinned-node POSIX volume for this SQLite functional deployment. Evidence: [ROLLOUT_RUNBOOK.md](../projects/11-cicd/ROLLOUT_RUNBOOK.md).

**Next action:** Resolve dependency findings, provision a protected self-hosted model runner and test cluster/immutable images, then run passing, degraded and missing-data rollout drills in the runbook.

```bash
.venv/bin/python -m pais.operations check-release artifacts/evals/release-local-final.json --commit "$(git rev-parse HEAD)"
```


## P12 — Vector database

Qdrant dense/sparse/hybrid retrieval, tenant filtering, version authority/tombstones, configuration-keyed caches, reindexing, portable checksummed backup and fresh restore.

- **PASS — Actual store comparison and fresh restore**: 100 documents/300 queries; denseRecall@1=.71, sparse/hybrid1.0. Restored100documents/vectors; version/deletion/tenant checks pass. Evidence: [p12-fixture.json](../artifacts/stateful/p12-fixture.json).
- **PASS — Embedding cache and consistency**: 100cache hits/200misses in the recorded fixture-embedding run; derived indexes never override source tombstones. Evidence: [p12-fixture.json](../artifacts/stateful/p12-fixture.json).
- **NOT RUN — Large-index HNSW/server performance**: Qdrant client local mode uses exact search; measured small-corpus timings are not scalable ANN performance.
- **PASS — Measured local scale experiment**: 1000 and10000 actual docs,300 query invocations each. Dense recall@1=.12/.01; sparse1.0/1.0; hybrid1.0/.21, hybrid p95=31.45/317.93ms. Worker HWM99,213,312/143,163,392bytes; parent live RSS guard unavailable. This records the observed hybrid quality limitation, not semantic or HNSW acceptance. Evidence: [scale-report.json](../artifacts/p12-scale/scale-report.json), [worker-1000.json](../artifacts/p12-scale/worker-1000.json), [worker-10000.json](../artifacts/p12-scale/worker-10000.json), [resource-verification.json](../artifacts/p12-scale/resource-verification.json).

**Next action:** Predeclare a quality/resource target, then compare candidate depth, fusion and embedding configurations on the preserved10k workload before attempting server/HNSW load.

```bash
.venv/bin/python -m pais demo 12 --profile fixture --output artifacts/p12-local-store.json
```


## P13 — Agent memory

Actual Redis buffers and Qdrant, authoritative memory versions/provenance/confidence, TTL/eviction, source-linked summaries, corrections/tombstones and stale-session conflict handling.

- **PASS — Restart, updates, expiry/eviction, correction and deletion**: Redis SIGKILL/AOF restart, actual Qdrant, cross-tenant checks, invalidated summaries and stale-session resurrection rejection. Evidence: [p13-fixture.json](../artifacts/stateful/p13-fixture.json).
- **PASS — Memory enabled/disabled task and token comparison**: Two fixed supplied facts: disabled0/2, enabled2/2; prompttokens121/136 and outputtokens4/10. Four Qwen responses in4.43s. Baseline lacks facts; no general uplift or token savings claim. Evidence: [p13-local-comparison.json](../artifacts/stateful/p13-local-comparison.json).
- **PASS — Irrelevant and low-confidence exclusion**: Both model prompts exclude two conflicting low-confidence records and an unrelated record; actual Redis/Qdrant retrieval test. Evidence: [test_comparison.py](../projects/13-agent-memory/test_comparison.py).

**Next action:** Expand the independently authored workload before interpreting quality or token impact; preserve the present two-fact baseline and exact token measurements.

```bash
.venv/bin/python scripts/with_local_models.py -- .venv/bin/python projects/13-agent-memory/compare_local.py --output artifacts/p13-comparison.json
```


## P14 — Inference server

vLLM CPU provisioning/profile, bounded admission gateway, readiness/warmup, streaming/cancellation/drain/load harness, resource/cleanup supervisor and a CPU Kubernetes template and separate GPU JSON profiles.

- **PASS — Admission/gateway/supervisor contracts**: Eleven tests pass; fixture four checks have zero model calls. Four Kubernetes YAML documents parse; no API-schema/cluster validation. Evidence: [EVIDENCE.json](../projects/14-inference-server/EVIDENCE.json).
- **FAIL — Actual CPU serving**: CLI/help/flags verified; server exit1 before readiness from denied ZeroMQ IPC. Follow-up preflight exits2 on AF_UNIX errno1; zero generation calls. Evidence: [report.json](../artifacts/p14-cpu-functional-first/report.json), [p14-local-final-preflight.json](../artifacts/p14-local-final-preflight.json), [p14-local-blocked.json](../artifacts/final/p14-local-blocked.json).
- **NOT RUN — Load/batching/cache/quantization and instance recovery**: Separate random39,456parameter one-head derivative; no trained-adapter quality or serving-performance evidence.

**Next action:** Use a host permitting AF_UNIX IPC, provision the exact CPU runtime and model derivative, run the functional supervisor, then separately qualify cluster/cache/batching/quantization profiles.

```bash
PAIS_VLLM_PYTHON=/path/to/cpu-runtime/bin/python .venv/bin/python -m pais demo 14 --profile local --output artifacts/p14-local.json
```


## P15 — Human approval

LangGraph interrupts and durable approval/checkpoint state bound to trusted tenant/reviewer/exact action/context/expiry/idempotency, edit/reapprove/cancel/restart and atomic visible effects.

- **PASS — Paused restart and authorization/context decision paths**: Wrong user/tenant, changed action, expired/stale context, concurrent decisions, edit/reapprove/cancel and restart/resume tests pass. Evidence: [p15-fixture.json](../artifacts/stateful/p15-fixture.json), [test_workflows.py](../tests/test_workflows.py).
- **PASS — Effect succeeds before replay**: Durable local downstream receipt preserves at most one visible effect despite replay; effect boundary explicitly documented. Evidence: [p15-approval-demo.json](../artifacts/p15-approval-demo.json).
- **NOT RUN — Development-data calibration of review trigger**: review_signals uses an explicit0.85 development rule plus mandatory conflict/sensitive-action review. It is not a calibrated probability or uncertainty model. Evidence: [README.md](../projects/15-human-approval/README.md).

**Next action:** Collect reviewed development examples for review_signals, measure false acceptance/rejection under the unchanged0.85 baseline and version any justified threshold change. Then verify a selected external provider idempotency contract.

```bash
.venv/bin/python -m pais demo 15 --profile fixture --output artifacts/p15-approval.json
```


## P16 — Automation pipeline

Signed FastAPI webhook adapter, durable acceptance/outbox, Celery/Redis, leases, bounded backoff/jitter, cancellation/dead/uncertain state and reviewed replay with explicit idempotent local effects.

- **PASS — Broker/worker crash and downstream replay recovery**: AOF Redis SIGKILL/restart retains queued job; worker exits71 after effect commit; replacement worker produces one visible effect and succeeds on second attempt. Repeated at clean c7b8: AOF restart retained queue, worker exited71 after effect, recovery kept one visible effect across two attempts. Evidence: [p16-local.json](../artifacts/stateful/p16-local.json), [p16-native.json](../artifacts/final/p16-native.json).
- **PASS — Bounded retries, poison isolation and reviewed replay**: Transient job succeeds after2attempts; poison dead-letters while healthy job continues; authorized replay succeeds; four effects belong to four distinct jobs. Evidence: [p16-local.json](../artifacts/stateful/p16-local.json).
- **PASS — Signed duplicate webhook/outbox and authorization**: Durable uniqueness and tenant/trace binding, invalid signatures rejected, published job retries safe. Evidence: [test_jobs.py](../tests/test_jobs.py).

**Next action:** Configure trusted tenant signing secrets and mount the documented router; revalidate each external effect provider contract before using it.

```bash
.venv/bin/python -m pais demo 16 --profile local --output artifacts/p16-native.json
```


## P17 — Code benchmark

100 original MIT Python/API repair tasks,325 checks, source-split policy, correctness controller, submission validation, two explicit rule/no-op baselines and result-derived leaderboard.

- **PASS — Meaningful licensed corpus and reference QA**: 100 unique ASTs across10categories;325checks;100references pass and100seeded defects reproduced;60/20/20splits. Evidence: [EVIDENCE.json](../projects/17-domain-benchmark/EVIDENCE.json).
- **PASS — Malformed submission and fail-closed scoring**: Invalid schema/tampering rejected; missing sandbox fails closed; fixture corpus checks cannot become leaderboard rows. Evidence: [test_benchmark.py](../tests/test_benchmark.py).
- **NOT RUN — Actual baseline scoring and reproducible leaderboard**: Zero scored runs/rows; no invented model score.
- **NOT RUN — Publication and actual community adoption**: Contribution guide prepared; no external users or adoption claimed.

**Next action:** After P06 real isolation passes, run both baseline submissions in fresh sandboxes on the same split twice and generate the leaderboard only from raw scored results.

```bash
.venv/bin/python -m pais.benchmark score artifacts/p17-submissions/no-op.json --split test --sandbox-image "$PAIS_SANDBOX_IMAGE" --enable-sandbox --output artifacts/p17-runs/no-op-test
```


## P18 — Upstream contribution

Current LangGraph checkpoint-sqlite transaction defect reproduction, small rollback patch, hash-pinned MIT source snapshot, byte-identical RED/GREEN tests and concrete English PR draft.

- **PASS — Original issue and correction**: Baseline3fail/1pass; patched4regressions+9upstream saver checks=13pass. Commit07b33185eab893be2ed031eedae52f09314bf77c. Evidence: [p18-demo.json](../artifacts/p18-demo.json), [upstream-verification.json](../artifacts/p18-outputs/upstream-verification.json), [upstream-verification.json](../artifacts/final/demos/p18-outputs/upstream-verification.json).
- **NOT RUN — Full upstream format/lint/test**: Focused synchronous saver checks passed; complete upstream development environment not executed.
- **NOT RUN — PR submitted, maintainer response, merge**: Patch and PR draft prepared; no issue/assignment/submission/merge fabricated. Evidence: [PROPOSED_PR.md](../projects/18-upstream-contribution/PROPOSED_PR.md).

**Next action:** Use the recorded upstream commit and contribution rules to obtain issue approval/assignment, run complete upstream package checks in a fresh checkout, then submit the prepared scoped patch when authorized.

```bash
.venv/bin/python -m pais demo 18 --profile local --output artifacts/p18-patch.json
```
