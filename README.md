# Production AI Systems

**Eighteen engineering projects around one technical-operations copilot.**

Upload a versioned PDF, ask an operational question, inspect the exact page behind an
answer, and require an authorized reviewer before a proposed action executes. Follow the
same identity, provenance, usage, approval and job contracts into separate research,
memory, training, inference and deployment projects.

This is a reproducible engineering portfolio under validation. Read the
[project ledger](docs/PROJECT_LEDGER.md) for each project's implementation, acceptance
results, evidence and next command. A passing component demonstration establishes its
stated scope; outstanding integration and deployment requirements remain visible.

## Start locally

Requires Python 3.12, uv, and Node.js 24 for the UI. The commands below use the checked-in
lockfiles. The complete test suite also needs `redis-server` on `PATH` for actual memory
and broker crash/recovery tests (on Ubuntu: `sudo apt-get install redis-server`). Redis is
started on temporary loopback ports by the tests. Model downloads are a separate explicit step.

```bash
cd production-ai-systems
uv sync --frozen --group dev --extra vectors --extra router --extra workflows
uv sync --frozen --project projects/04-eval-harness
uv run --no-sync pais doctor
uv run --no-sync pais smoke
uv run --no-sync pais demo 01 --profile fixture
uv run --no-sync pais dev --profile fixture
```

In another terminal:

```bash
cd production-ai-systems/apps/copilot
npm ci
npm run dev
```

Open [http://127.0.0.1:3000](http://127.0.0.1:3000). The fixture profile visibly labels
deterministic responses and explicitly enables its synthetic local identity. Uploaded
PDFs still pass through actual extraction, storage, retrieval and citation validation.
Follow [P07](projects/07-local-first/README.md) to provision the actual Ollama generation,
embedding and cross-encoder models, then run the local profile. Use the fixture identity
only for these local demonstrations.

## The portfolio

Each guide contains setup, a repeatable demo, verification commands, an acceptance
checklist, a case study and an interview walkthrough. The ledger binds results to
evidence files instead of inferring readiness from the framework names below.

| Project | Capability and critical failure | Main implementation |
| --- | --- | --- |
| [01 · RAG with citations](projects/01-rag-citations/README.md) | Versioned PDF → hybrid retrieval → reranking → grounded answer; invalid source spans fail | [rag.py](packages/pais/rag.py), [models.py](packages/pais/models.py) |
| [02 · Model router](projects/02-model-router/README.md) | Cost/quality routing and persistent reservations; concurrent requests cannot overspend the declared cap | [reliability.py](packages/pais/reliability.py) |
| [03 · Multi-agent research](projects/03-multi-agent-research/README.md) | Four actual CrewAI roles with evidence and audit; unsupported claims can be rejected | [research.py](packages/pais/research.py) |
| [04 · Evaluation harness](projects/04-eval-harness/README.md) | 144 frozen cases and actual DeepEval/RAGAS metrics; incomplete or degraded candidates block | [evaluation.py](packages/pais/evaluation.py) |
| [05 · Observability](projects/05-observability/README.md) | OTel traces, Prometheus metrics, Grafana and alert drill; sensitive telemetry is filtered | [observability.py](packages/pais/observability.py) |
| [06 · Security middleware](projects/06-security-guardrails/README.md) | Guardrails AI, authorization, shared limits and execution boundary; unavailable required validation fails closed | [security.py](packages/pais/security.py), [sandbox.py](packages/pais/sandbox.py) |
| [07 · Local-first environment](projects/07-local-first/README.md) | Actual local models and two selectable retrieval adapters; offline prerequisites are actively checked | [retrieval.py](packages/pais/retrieval.py) |
| [08 · Streaming copilot](projects/08-streaming-ui/README.md) | Next.js/AI SDK upload, citations, approvals and recovery; stable IDs reconcile retries | [UI](apps/copilot), [API](services/api) |
| [09 · LoRA training](projects/09-lora-training/README.md) | Genuine tiny SFT/DPO, adapter reload and held-out comparison; retention rejects inadequate evidence | [training.py](packages/pais/training.py) |
| [10 · Multi-tenant SaaS](projects/10-multi-tenant-saas/README.md) | Membership, metering, Supabase/Stripe adapters; tenant headers and webhook replay cannot grant privileges | [tenancy.py](packages/pais/tenancy.py) |
| [11 · CI/CD](projects/11-cicd/README.md) | Immutable release evidence, Argo configuration and emergency disable; missing observations block promotion | [operations.py](packages/pais/operations.py), [workflows](.github/workflows) |
| [12 · Vector database](projects/12-vector-database/README.md) | Qdrant hybrid/filter/cache/reindex/restore; stale derived records cannot revive deleted content | [vectors.py](packages/pais/vectors.py) |
| [13 · Agent memory](projects/13-agent-memory/README.md) | Redis buffers and versioned long-term memory; stale sessions respect correction and deletion markers | [memory.py](packages/pais/memory.py) |
| [14 · Inference server](projects/14-inference-server/README.md) | vLLM profiles and bounded serving gateway; admission and instance failures are observable | [inference.py](packages/pais/inference.py) |
| [15 · Human approval](projects/15-human-approval/README.md) | Durable LangGraph interruption; changed, expired and replayed actions are revalidated | [workflows.py](packages/pais/workflows.py) |
| [16 · Automation pipeline](projects/16-automation-pipeline/README.md) | Signed webhook → transactional outbox → Celery job; retries and uncertain effects have explicit states | [jobs.py](packages/pais/jobs.py) |
| [17 · Code benchmark](projects/17-domain-benchmark/README.md) | 100 original tasks with executable checks; untrusted scoring requires the P06 sandbox | [benchmark.py](packages/pais/benchmark.py) |
| [18 · Upstream contribution](projects/18-upstream-contribution/README.md) | Current SQLite-checkpoint transaction reproduction and focused patch; submission/merge tracked separately | [contribution](projects/18-upstream-contribution) |

## Commands and profiles

```bash
uv run --no-sync pais demo 15 --profile fixture
uv run --no-sync pais test
uv run --no-sync pais security
uv run --no-sync pais eval --profile fixture --suite release
uv run --no-sync pais status
```

`pais demo 01` through `pais demo 18` are individual entrypoints. Specialized demos
dispatch to their locked environment or explain the missing prerequisite with exit 2.
Run `uv sync --frozen --project projects/03-multi-agent-research` before P03,
`projects/06-security-guardrails` before required real Guardrails validation, and
`projects/09-lora-training` before P09 local training. See each README for dependencies
that cannot be supplied by Python alone.

Fixture checks establish deterministic contracts. Local runs use actual provisioned
models and dependencies. Connected runs require named authorized test accounts and an
explicit budget. Deployment/performance runs require the declared hardware, services and
load. Selecting a smaller profile does not remove a project's other acceptance criteria.

After P07 provisioning, a Unix local-model evaluation is:

```bash
uv run --no-sync python scripts/with_local_models.py -- \
  .venv/bin/python -m pais eval --profile local --suite release \
  --output artifacts/evals/release-local.json
```

The wrapper starts and stops its own Ollama instance. It is useful on execution hosts
where each command gets a separate network namespace. On a normal development machine,
native Ollama may run separately; set the documented model-lock and local service URL.
`PAIS_EVAL_PYTHON` optionally selects the exact isolated evaluation-worker interpreter;
`PAIS_GUARDRAILS_PYTHON` selects the mandatory validator interpreter for non-fixture API runs.

To capture a command and its provenance:

```bash
uv run --no-sync pais evidence --profile fixture \
  --output artifacts/checks.json -- .venv/bin/python -m pytest tests -q
```

Exit 0 means the requested run succeeded, exit 1 means required assertions failed, and
exit 2 means a required prerequisite or validator was unavailable. The JSON report
retains individual results. A fixture success never authorizes deployment.

## Evidence and design decisions

Start with [architecture and state ownership](docs/ARCHITECTURE.md),
[shared contracts](docs/CONTRACTS.md), [capabilities](docs/CAPABILITIES.md),
[evaluation data](evals/README.md), and the [verification report](docs/VERIFICATION.md).
The complete requested scope is preserved in [BUILD_SPEC.md](docs/BUILD_SPEC.md).

Ordinary answers use complete source sentences selected by the model. Explicit document
summaries use a disclosed page-balanced assembly of retrieved source excerpts. Both paths
retain exact page/span validation; summary reports identify deterministic assembly and do
not count it as model generation. This grounding constraint does not prove
arbitrary paraphrase entailment or broad-domain accuracy. Protected output is validated
before streamed delivery, so first displayed text and provider time to first token are
distinct measurements.

Original code and synthetic corpora use the [MIT license](LICENSE). Downloaded models
and tools retain their own licenses. Dependencies, model weights, indexes, databases
and raw logs stay outside source control. Small reviewed reports and data manifests
remain versioned; the delivery archive also contains selected raw evidence.

## Continue the work

Open this directory as the project root. Read [AGENTS.md](AGENTS.md) and [STATE.md](STATE.md)
before making changes. Use the ledger's next command to resolve a specific remaining
criterion, retain the failed baseline, and rerun the same acceptance contract. Public
deployment, billing-account execution and upstream submission each need their own named
target and evidence.
