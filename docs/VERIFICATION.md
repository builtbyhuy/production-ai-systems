# Production AI Systems — implementation and verification report

**Delivery scope:** all 18 projects have implementations, individual demo entrypoints and
project guides in the `production-ai-systems` monorepo. The integrated operations copilot
works with actual local models. The complete portfolio remains **incomplete for production
acceptance** because specific quality, security, account, sandbox and deployment criteria
are failed or unexecuted. Implementation count is not a readiness score.

This report records measurements from 2026-09-29. The original requested scope is preserved
in [BUILD_SPEC.md](BUILD_SPEC.md). The [criterion-level ledger](PROJECT_LEDGER.md) links each
result and remaining action; its [JSON source](PROJECT_LEDGER.json) is machine readable.

## 1. Source identity and verification scope

| Source | What was exercised |
|---|---|
| `c7b8a793f34795f3d2de148c1c5c211845e8b222` | Clean application snapshot: core/library checks, all 18 fixture entrypoints, full positive/degraded/audit local evaluations, both browser profiles, native jobs and P12 scale runs. |
| `9f8e0fdf41f3a170004c297c24b18ab01da7f25b` | Separate P09 dependency declaration and lock correction, followed by a clean actual generic CLI SFT/DPO smoke. Only the P09 manifest, lock and README changed. |
| Final delivery commit, recorded in the archive manifest | Documentation and evidence reconciliation after those runs. It is not a separately exercised deployment candidate. |

Earlier reports retain their actual source snapshots, timestamps and dirty or unborn Git
state. They are not retroactively attributed to either clean commit. The archive contains
a Git bundle so that the recorded commits can be restored. A future release candidate must
run its own full gate; an older report must not authorize a different commit.

The verified host was Linux x86-64, Python 3.12.14 and Node 24.19, with an AMD EPYC 9V74 host
CPU, an eight-CPU cgroup quota and an 8 GiB memory limit. It had no GPU, Docker daemon or
Kubernetes target. Each command received a separate network namespace, so servers and their
clients were orchestrated together. Heavy generation was sequential with small CPU models.
These are functional workload observations, not an uncontended production benchmark: the
start of the positive release overlapped brief integration/build checks.

Four evidence levels remain distinct: deterministic fixture contracts; actual local models
or libraries; connected test-account integrations; and a declared deployment/load profile.
A fixture run can use a real database while still using synthetic embeddings or responses.

## 2. Final integrated results

| Check | Result | Evidence |
|---|---|---|
| Core Python suite | 262 passed; two upstream deprecation warnings; pytest 15.46 s | [Core report](../artifacts/final/core-tests.json) |
| Isolated real CrewAI library | 5 passed; fixture model responses; upstream callback serialization warnings retained | [CrewAI report](../artifacts/final/crewai-tests.json) |
| Isolated real Guardrails library | 3 passed; upstream warnings retained | [Guardrails report](../artifacts/final/guardrails-tests.json) |
| Individual fixture demo entrypoints | 18 of 18 commands exited 0 | [Demo index](../artifacts/final/demos/index.json) |
| Python lint | Ruff passed across packages, services, tests, projects, scripts and infrastructure helpers | [Lint report](../artifacts/final/lint.json) |
| Python type checks | Mypy passed for the explicitly selected contracts and operations modules | [Type-check report](../artifacts/final/typecheck-python.json) |
| Frontend | TypeScript and production Next build passed | [Build report](../artifacts/final/ui-build.json) |
| Fixture browser | 14 passed, no skipped/flaky cases; 1440×960 and 390×844; 23.621 s Playwright time | [Browser evidence](../artifacts/ui/browser-evidence.json) |
| Actual local browser | 1 passed, no skipped/flaky cases; desktop; 25.821 s Playwright time | [Local browser evidence](../artifacts/ui/local/browser-evidence.json) |
| Full positive local release | 144 passed, 0 failed/errors/skips; exit 0; p95 6,366.34 ms | [Positive report](../artifacts/evals/release-local-final.json) |
| Full deliberately degraded local release | 96 passed, 48 failed, 0 errors/skips; exit 1; p95 6,630.03 ms | [Negative report](../artifacts/evals/degraded-local-final.json) |
| Actual audit | 8 passed, 0 failed/errors/skips; p95 6,508.33 ms | [Audit report](../artifacts/evals/audit-local-final.json) |
| Independent release binding | Positive accepted; degraded candidate rejected for failed cases | [Positive binding](../artifacts/final/release-binding.json), [negative binding](../artifacts/final/degraded-binding.json) |
| P09 corrected common CLI | Genuine SFT/DPO completed at its separate clean commit; retention rejected | [CLI report](../artifacts/final/p09-cli/run.json) |

The positive evaluation's `deployment_eligible=true` field has an explicit scope: the local
synthetic regression and source identity. It does not clear package advisories, container
validation, cluster operation, external integrations or the rest of the portfolio.

## 3. Eighteen-project status matrix

“Local scope passed” below means the named behavior was demonstrated. A partial or
incomplete project still has required evidence missing. Each linked guide contains its
architecture, setup/demo commands, acceptance checklist, case study and interview walkthrough.

| Project | Verified behavior and measured result | Status and precise remaining action |
|---|---|---|
| [P01 — RAG with citations](../projects/01-rag-citations/README.md) | Actual embeddings, cross-encoder and Qwen; 13/13 lifecycle cases. On 16 queries, lexical recall@5=.9375 and dense/hybrid/reranked recall@5=1.0. Exact version/page/span validation and explicit abstention work. | Local scope passed. Expand the independent corpus before making broad grounding claims; current initial operating points are not calibrated probabilities. Scanned PDFs are explicitly unsupported. |
| [P02 — Model router](../projects/02-model-router/README.md) | 36 actual requests: cheap 4/12, expensive 6/12, routed 4/12. Persistent reservations, bounded fallback and cancellation holds; simulated 429-micro-USD cap admitted 3/24 concurrent requests. | Partial. Establish an authorized provider workload, rate card and spending budget, then compare actual invoice reconciliation and quality/cost. No paid savings has been demonstrated. |
| [P03 — Research agents](../projects/03-multi-agent-research/README.md) | Real CrewAI roles, tools, rejection and audit pass controlled tests. The actual Qwen run received one response and timed out on call 2 after 70.02 s, before any tool execution. | Incomplete. Resolve dependency findings, evaluate a suitable model/configuration under the same bounded research contract, then run explicitly authorized web acquisition. Native callback checkpoint serialization remains limited. |
| [P04 — Evaluation harness](../projects/04-eval-harness/README.md) | Full positive144/144, degraded48 failures correctly rejected, audit8/8; real DeepEval/RAGAS exact metrics and source-bound reports. | Local regression accepted; overall partial. Resolve two remaining evaluator advisory packages and run the prepared LangSmith integration against an authorized dataset/account. Broader independent quality evaluation remains separate. |
| [P05 — Observability](../projects/05-observability/README.md) | Native Prometheus/Grafana/Tempo/Alertmanager: two alert firing/resolution pairs, linked producer/worker trace, 40 simulated micro-USD equal in ledger and metrics. 12 panels provisioned, eight rendered in the accepted image. | Declared native drill passed. Execute Compose on a Docker host if that deployment is chosen; establish a mature anomaly baseline and actual provider accounting before claiming those capabilities. |
| [P06 — Security](../projects/06-security-guardrails/README.md) | Actual Guardrails enforcement; two API instances admitted3/rejected21 of24 concurrent calls. Injection sample: TP5, FN2, FP1, TN4. Required validation fails closed. | Incomplete. On a suitable host, run the prepared sandbox filesystem/network/CPU/RAM/time/output isolation checks and address dependency findings. The observed misses and false positive remain disclosed. |
| [P07 — Local-first runtime](../projects/07-local-first/README.md) | Actual SQLite and LanceDB profiles each passed13/13 with loopback-only networking, proxy variables removed and failed external IPv4/IPv6 probes. | Partial. Trusted application offline behavior is established. Run the Docker profile on a declared host; it has not been executed here and does not establish hostile-code isolation. |
| [P08 — Copilot UI](../projects/08-streaming-ui/README.md) | 20 API checks,14 desktop/mobile fixture browser cases and1 actual local desktop case. PDF upload, checked answer, extracted source page, authenticated PDF link, approvals and recovery are exercised. | Local UI scope passed. First checked display14,785 ms; provider TTFT unmeasured. Add process-crash reconciliation, production identity and declared load/accessibility work before wider service use. |
| [P09 — LoRA SFT/DPO](../projects/09-lora-training/README.md) | Genuine3-step SFT and3-step DPO; adapters changed, backbone stayed frozen and reload logit difference was0.0. Generic CLI dependency bug fixed and reproduced cleanly. | Incomplete. Base/SFT/DPO all scored0% held-out exact match; six cases per suite fail the minimum20 gate. Use a suitable reviewed pretrained snapshot, larger independent suites and actual checkpoint/resume evidence. |
| [P10 — Multi-tenant SaaS](../projects/10-multi-tenant-saas/README.md) | Local membership, quotas, immutable ledger, Stripe SDK signature/replay/order tests and Supabase JWT/RLS adapters. Concurrent local quota enforcement accepted10/30 and isolated the other tenant. | Incomplete. Supply a named authorized Supabase test project and Stripe test customer/meter mapping; exercise two real user-JWT tenants across remote resources and reconcile actual test records. |
| [P11 — CI/CD](../projects/11-cicd/README.md) | Strict local release binding, durable capability flags, no-data rejection, CI/image/Argo configuration and runbooks exist. | Incomplete. Repair supply-chain findings; establish repository, image registry and cluster targets; run Actions, image validation, canary promotion/degraded rollback, full API/worker stop drill and cross-version state recovery. |
| [P12 — Vector store](../projects/12-vector-database/README.md) | Actual Qdrant local filtering/cache/reindex/restore. Additional1k/10k stores each ran300 query invocations; hybrid recall@1 dropped1.0→.21 with the fixed feature hashes. | Partial. Predeclare quality/resource targets and compare candidate/fusion/embedding configurations on the preserved10k corpus. Semantic embeddings, server HNSW,100k and concurrent load remain unexecuted. |
| [P13 — Agent memory](../projects/13-agent-memory/README.md) | Real Redis/Qdrant restart, correction, tombstone, TTL/capacity and irrelevant-memory rejection. Actual two-fact comparison:0/2 without vs2/2 with memory, with higher token use. | Small local scope passed. This baseline lacked the needed facts; use a larger independent task suite before claiming general uplift or token savings. |
| [P14 — Inference server](../projects/14-inference-server/README.md) | Gateway/supervisor tests and real vLLM CLI inspection. Actual CPU startup failed before readiness; final preflight exits2 because AF_UNIX creation is denied. Zero generation requests ran. | Incomplete. Use a host permitting required IPC, then run the bounded CPU functional profile before serving/load/cache/quantization or multi-instance recovery comparisons. GPU profiles are unexecuted. |
| [P15 — Human approval](../projects/15-human-approval/README.md) | Real LangGraph pause/restart, reviewer/tenant/expiry/context validation and CAS/replay; durable local downstream retained one visible effect. | Partial. Calibrate the current0.85 review rule on reviewed development examples and verify any external provider's idempotency retention, receipt lookup and recovery. |
| [P16 — Automation jobs](../projects/16-automation-pipeline/README.md) | Native Redis AOF/Celery worker death after a successful local effect, restart and replay; two attempts retained one visible effect. Poison jobs, retry bounds and reviewed dead-letter replay exercised. | Declared native pipeline scope passed. External effects need a named downstream contract and receipt-based reconciliation; local evidence does not prove exactly-once arbitrary provider execution. |
| [P17 — Code benchmark](../projects/17-domain-benchmark/README.md) | 100 original MIT tasks,100 distinct ASTs,325 checks and10 categories; every reference passes and every seeded defect is detected. Malformed submissions and unavailable sandbox are rejected. | Incomplete. Establish P06 isolation, then execute both real baselines and publish only result-derived scores. Actual score/leaderboard count is zero; publication and community adoption are unexecuted. |
| [P18 — Upstream fix](../projects/18-upstream-contribution/README.md) | Current upstream SQLite checkpoint transaction defect reproduced: baseline3 failed/1 passed; patched13 passed including9 upstream tests. Patch and PR draft prepared. | Partial. Obtain upstream issue approval/assignment, run the full required format/lint/test commands, then submit when authorized. No PR submission, maintainer response or merge is claimed. |

## 4. Findings that affect engineering decisions

### Grounding, evaluation and actual generation

The first full actual local release passed132/144. Twelve summary omissions were retained
as failed baseline evidence. The fix adds a disclosed page-balanced assembly of complete
source excerpts for an explicit summary request. Ordinary question answering still uses
actual Qwen selection of complete source sentences. Expected answers, source datasets and
the release thresholds were not relaxed to make the run pass.

The final144-case positive release includes56 actual Qwen responses,16 deterministic
excerpt summaries and72 contract/abstention cases. Actual generated responses reported
12,809 input and836 output tokens. DeepEval source-support and RAGAS reference/string
metrics were1.0 on the narrow expected outputs; these are exact synthetic metrics, not a
calibrated semantic judge. All nine required categories passed. The same full degraded
suite deliberately broke answer content/citations, producing32 answerable and16 summary
failures with no infrastructure errors or skipped cases.

The audit run contains eight actual model responses and is the first executed actual audit;
[the exposure record](../artifacts/evals/audit-exposures.jsonl) is retained. Its data was
authored during this build and previously inspected by source/exclusion tests. It is not an
independently blind study. Single-seed observations and a small synthetic corpus cannot
establish broad accuracy, calibrated confidence or stochastic stability.

The P01 retrieval comparison also limits an attractive default: reranking achieved no
ranking gain over dense/hybrid on these16 questions and added latency. Mean lexical,
dense, hybrid and reranked times were approximately1.93,275.42,282.59 and350.32 ms. That is
a measured reason to evaluate reranking for a workload, not an argument that it never helps.

### Scaling exposes the feature-hash configuration

The [additional P12 experiment](../artifacts/p12-scale/scale-report.json) reused the existing
benchmark with100 identifier questions per mode at each declared size. Both datasets were
actually indexed and counted. It used Qdrant client local exact search and64-dimensional
feature-hash embeddings, independently from P01's actual semantic-model comparison.

| Measurement | 1,000 documents | 10,000 documents |
|---|---:|---:|
| Dense recall@1 | .12 | .01 |
| Sparse recall@1 | 1.00 | 1.00 |
| Hybrid recall@1 | 1.00 | .21 |
| Dense p95 | 12.21 ms | 91.60 ms |
| Sparse p95 | 13.03 ms | 125.10 ms |
| Hybrid p95 | 31.45 ms | 317.93 ms |
| Ingestion throughput | 793.14 docs/s | 850.21 docs/s |
| Worker elapsed time | 7.13 s | 57.73 s |
| Worker kernel peak RSS | 99,213,312 bytes | 143,163,392 bytes |
| Logical disk while store was open | 2,646,697 bytes | 25,207,465 bytes |

Sparse exact-identifier retrieval retained all targets. The dense/fusion configuration lost
many targets at10k; this configuration is not validated for useful semantic retrieval at
that scale. The parent process could not inspect nested child PIDs, so its live RSS/thread
guard was unavailable. Worker `getrusage` high-water marks are valid; a separate short
reopened-store probe observed one thread and161,812,480-byte peak RSS. It does not provide
a continuous thread trace for the full benchmark. No HNSW or Qdrant server claim follows.

### Router policy and memory did not demonstrate cost savings

In the [actual router comparison](../artifacts/p02-router-local.json), each policy received
the same12 questions. Cheap, expensive and routed quality were4/12,6/12 and4/12. Mean
latencies were0.801,2.084 and1.054 seconds, with p95s2.036,5.800 and2.608 seconds. The route
was slower than cheap and matched its exact-match score. The local API price ledger was
zero; hardware/electricity were not measured. Simulated-budget concurrency and retry
accounting are useful contract evidence, but not measured dollar savings.

The [P13 local memory comparison](../artifacts/stateful/p13-local-comparison.json) answered
two stored facts correctly with memory and abstained without them. Input tokens increased
121→136 and output tokens4→10; four actual responses took4.43 seconds. This demonstrates
retrieval of the required facts in a controlled task. It does not establish a general agent
quality improvement or a reduction in token use.

### Recovery and observability have concrete downstream boundaries

The accepted P05 native drill ran155.3733 seconds and stayed below its declared1,536 MiB
combined process RSS bound: peak1,448,546,304 bytes. An earlier1 GiB attempt exceeded its
bound and remains failed evidence. A later interrupted visualization attempt overwrote the
convenient canonical output directory; the authoritative accepted report is
[p05-native-first-pass/report.json](../artifacts/p05-native-first-pass/report.json), with a
[reviewed copy](../artifacts/reports/p05-native-accepted.json). Its SHA-256 is
`7ee4e5bdf01420327bdd93977280c3e1c2d265b7f5e278fadf55581c5aca8133`.

Native Prometheus, Grafana, Tempo and Alertmanager observed actual app/worker traffic,
linked producer/worker spans and two firing/resolution alert pairs. Ledger40 micro-USD
matched the metric total under a simulated rate card. Twelve panels were provisioned;
eight were rendered in the captured browser viewport. The remaining four lazy panels were
not visually verified. Compose operation and a mature anomaly baseline remain separate.

The [final native P16 run](../artifacts/final/p16-native.json) retained a queued message
through Redis AOF restart, killed the worker after the downstream effect succeeded, and
recovered with two attempts and one visible durable local effect. It also exercised bounded
transient retries, poison-job isolation and reviewed replay. P15's action fingerprint,
context revalidation and compare-and-swap protect its local approval/replay path. An external
provider can only inherit these guarantees if its own durable idempotency and receipt
lookup contracts are demonstrated.

### Training works mechanically; its output is not useful model evidence

The clean [P09 CLI reproduction](../artifacts/final/p09-cli/run.json) used60 original
licensed records, with36/12/12 source-grouped training/development/test splits. The model
was a locally initialized GPT-2 architecture with39,456 base parameters and1,024 trainable
LoRA parameters, not a pretrained assistant. SFT and DPO each ran three optimizer steps.
Adapter parameters changed, frozen backbone parameters did not, and both exported adapters
reloaded with0.0 maximum logit difference. SFT loss was5.716662 and DPO loss0.692596; these
are different objectives and should not be compared as one quality score.

Base, SFT and DPO all achieved0% exact match on the identical domain/general held-out suites.
Each suite contained six examples, below the prospective minimum of20, so retention and
release approval stayed false. The small NLL changes do not prove useful answers or freedom
from forgetting. Pipeline time after imports/setup was1.208 s in the final run; it is not
pretrained-model throughput. Full training, calibrated selection and crash-resume remain open.

The first generic CLI attempt failed before training because its isolated environment
omitted Pydantic while importing shared contracts. The separate dependency/lock correction
preserves [that failed log](../artifacts/final/p09-local.log) and the successful actual rerun.

### Isolation and inference startup could not be established on this host

P07's offline checks constrain trusted application traffic after provisioning. They do not
establish hostile-code containment. P06's required execution sandbox remains disabled;
P17 therefore has zero actual submitted baseline scores. A plain subprocess or the trusted
UI test browser launched without Chromium's sandbox cannot substitute for filesystem,
network and resource isolation of submitted code.

The actual P14 vLLM process failed before health/readiness because required AF_UNIX/ZeroMQ
IPC was denied. The final entrypoint correctly reports prerequisite exit2 and zero inference
calls. Its sampled startup peak was1,342,173,184 bytes before shutdown; this is not serving
capacity or throughput. The3.75 GiB watchdog was an application monitor, not a kernel memory
limit. The one-head random functional model is a distinct derivative of the tiny training
architecture, not evidence that a P09-trained adapter was served. GPU profiles and load,
batching, prefix cache, quantization and multi-instance failover were not executed.

## 5. Dependency and security gate

The [dependency report](dependencies/AUDIT.md) retains every finding without ignore rules.
The scan used pip-audit2.10.1; npm audited production dependencies. Counts below are affected
package names, not a count of exploitable defects; duplicate advisory records are preserved.

| Environment | Queried / listed entries | Packages with reported findings | Important coverage gap |
|---|---:|---:|---|
| Fresh core | 162 / 164 | 0 | Editable project skipped; CPU Torch version unmatched |
| Adopted evaluator | 120 / 120 | 2 | DiskCache and RAGAS findings remain |
| Guardrails | 108 / 108 | 4 | Package findings remain despite bounded exercised paths |
| CrewAI | 158 / 158 | 1 | Chroma findings remain even though its memory path was not selected |
| Training after CLI fix | 48 / 49 | 3 | CPU Torch version unmatched |
| CPU vLLM runtime | 148 / 153 | 1 | Five CPU wheel versions unmatched |
| UI production | npm production scope | 0 reported | Development dependencies outside this scan |

The evaluator was upgraded in a disposable candidate and a fresh adopted environment. The
unchanged worker reproduced all432 numeric metric values on144 preserved observations
exactly. This reduced affected evaluator packages from six to two while retaining the
required metrics. Known RAGAS/DiskCache findings, other isolated-environment findings and
unmatched CPU wheels still prevent a complete production dependency clearance.

“No reported findings” applies only to queried packages at the scan time. It is not a
security guarantee. A bounded source secret-pattern screen found no unresolved real key
material; its short private-key marker was an intentional rejection-test fixture. That
screen is not a comprehensive secret scanner or a successful Trivy production image scan.
The prepared CI keeps its strict HIGH/CRITICAL image gate; no actual container scan ran here.

## 6. Restore and launch

The delivery ZIP includes the source snapshot, selected raw evidence, original small
training weights, a source-history bundle and a per-file SHA-256 manifest. It excludes
virtual environments, downloaded large models/tools, dependency caches, indexes, service
databases and `node_modules`. Evidence manifests preserve the original machine's paths;
regenerate runtime-specific paths rather than treating those paths as portable assets.

For a Git-backed restoration, use the included `RESTORE.md` instructions:

```bash
git clone production-ai-systems-source.bundle restored-production-ai-systems
cp -R production-ai-systems/artifacts/. restored-production-ai-systems/artifacts/
cd restored-production-ai-systems
```

On a Linux/POSIX host with Python3.12, uv, Node24 and `redis-server` on PATH, start the fixture
workspace from that repository root:

```bash
uv sync --frozen --group dev --extra vectors --extra router --extra workflows
uv sync --frozen --project projects/04-eval-harness
uv run --no-sync pais doctor
uv run --no-sync pais smoke
uv run --no-sync pais demo 01 --profile fixture
uv run --no-sync pais dev --profile fixture
```

Use another terminal for the frontend:

```bash
cd apps/copilot
npm ci
npm run build
npm run start
```

Open [http://127.0.0.1:3000](http://127.0.0.1:3000) and choose the visibly labeled fixture
workspace. This uses synthetic local identities and deterministic model responses while
still exercising actual PDF extraction/storage/citation mechanics. It is not production SSO.

Each project has a separate command, `pais demo 01` through `pais demo 18`. Install the
specialized locked environments before the corresponding library or training demos:

```bash
uv sync --frozen --project projects/03-multi-agent-research
uv sync --frozen --project projects/06-security-guardrails
uv sync --frozen --project projects/09-lora-training
uv run --no-sync pais test
uv run --no-sync pais demo 09 --profile local --output artifacts/new-p09/run.json
```

For actual model profiles, follow [P07 provisioning](../projects/07-local-first/README.md)
first, including the locked core local extra, official Ollama runtime, model digests and
cross-encoder snapshot. No paid-provider request is necessary. Choose fresh output names
when preserving the supplied evidence:

```bash
uv run --no-sync python scripts/with_local_models.py -- \
  .venv/bin/python -m pais eval --profile local --suite release \
  --output artifacts/evals/new-release.json

uv run --no-sync python scripts/with_local_models.py -- \
  .venv/bin/python -m pais eval --profile local --suite release --degraded \
  --output artifacts/evals/new-degraded.json

PAIS_GUARDRAILS_PYTHON="$PWD/projects/06-security-guardrails/.venv/bin/python" \
  .venv/bin/python scripts/with_local_models.py -- \
  .venv/bin/python projects/08-streaming-ui/run_browser_tests.py --profile local
```

The degraded command should exit1 for actual quality failures. Exit2 means a missing
prerequisite or validator and does not establish a correctly rejected quality candidate.
Fixture exit0 never authorizes deployment. Windows/POSIX portability has not been verified.

In the original managed checkout, use `.venv-verified/bin/python` for core and set
`PAIS_EVAL_PYTHON` to `projects/04-eval-harness/.venv-final/bin/python` as documented in
[STATE.md](../STATE.md). Fresh restoration uses the ordinary `.venv` paths from locked setup.
The alternate names avoid stale distributions left by an experimental in-place upgrade;
virtual environments are not included in the archive.

## 7. Remaining work and publication state

The next acceptance work is concrete: remediate the listed compatible dependency graphs;
run P06 isolation and P14 IPC/serving on a suitable host; improve and compare P12's measured
10k retrieval configuration; calibrate P15's review rule; obtain useful P03/P09 model-quality
evidence; then exercise named Supabase/Stripe/LangSmith and deployment targets. Every row
in the matrix links the project's precise prerequisites and verification procedure.

Git is local only. The connected GitHub account was available, but the proposed
`builtbyhuy/production-ai-systems` target returned404 and the connector exposed no repository
creation action. No external remote, push, public site or production account mutation was
performed. The complete source and evidence are ready for review before publication.

P18 is a prepared upstream correction with focused RED/GREEN evidence, not a submitted or
merged contribution. Its issue approval/assignment and full upstream checks remain open.
No users, clients, revenue, paid-provider savings, secure untrusted benchmark scores,
production operation or maintainer acceptance is invented.
