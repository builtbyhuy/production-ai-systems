# P03 — Evidence-driven research graph

**Implemented. Actual LangGraph 1.2.12 orchestration, tools and bounded revisions are verified with deterministic fixture inference, a controlled web transport and one actual local Qwen run. General model quality and live web research are unverified.** The earlier CrewAI/Qwen attempt and its timeout remain historical evidence; they do not attest the migrated graph.

## Problem and architecture

LangGraph executes four native nodes: supervisor, researcher, writer and fact-checker. Typed graph state carries the plan, retrieved evidence, draft, validation and round count. Fixed edges enforce role order; the fact-checker's conditional edge ends accepted/conflicted work or starts a bounded revision. An immutable runtime context carries the authenticated principal and run ID. [research.py](../../packages/pais/research.py) persists run state, budgets, deadlines, revisions, source identities, retrieval times, passages, hashes and claim linkage.

The researcher invokes only the schema-validated corpus_lookup tool; the fact-checker invokes only inspect_evidence. Retrieved instructions cannot grant capabilities. Evidence must match the actual tenant-scoped tool retrieval, preventing invented sources. A model-supplied plan cannot change roles or permissions, and the checker cannot replace the writer's draft. Acceptance requires every claim to match a quoted structured fact, at least one supported claim, and no unresolved contradictory values. Accepted work can create a durable P15 review before a local report effect; it performs no external publishing.

## Setup and commands

The research environment is locked independently and directly declares LangGraph,
its SQLite checkpoint package for P15, Pydantic, HTTPX and Pytest. CrewAI and ChromaDB
are no longer dependencies of this project; their advisory failure was addressed by
replacing the orchestration implementation. The security scan remains mandatory.

~~~bash
uv sync --frozen --project projects/03-multi-agent-research
.venv/bin/python -m pais demo 03 --profile fixture --output artifacts/stateful/p03-langgraph-fixture.json
PYTHONPATH=packages projects/03-multi-agent-research/.venv/bin/python -m pytest projects/03-multi-agent-research/test_langgraph.py -q
.venv/bin/python -m pytest tests/test_research.py -q
~~~

The public CLI selects the isolated interpreter. LangSmith tracing is disabled. Fixture inference downloads no models. Local mode requests typed JSON from a provisioned loopback Ollama endpoint and never downloads weights. The graph validates each response before advancing. Invalid output, failed tools, exhausted calls or deadlines fail closed. [Earlier CrewAI fixture evidence](../../artifacts/stateful/p03-fixture.json) retains its original source identity and bytes.

Reproduce the bounded actual-local attempt with already provisioned models:

~~~bash
.venv/bin/python scripts/with_local_models.py -- env PYTHONPATH=packages projects/03-multi-agent-research/.venv/bin/python projects/03-multi-agent-research/local_attempt.py
~~~

The run permits at most eight call slots (model and tool calls), zero revisions and a 90-second total budget. Explicit loopback model requests bypass inherited proxy settings, reject credentials and remote hosts, and never fall back to fixture inference. The script creates a timestamped directory and fresh database; `--output FRESH_DIRECTORY` selects another location and refuses any existing directory. An accepted report requests P15 review. Add `--approve-local` only when authorizing this local operator to approve and record the local report effect. Its durable receipt explicitly records `external_delivery: false`.

The separate web mode uses WebResearchConfig, the P06 HTTPS allowlist/DNS-pinned transport, at most five sources, bounded bodies, two redirects and a total deadline. Quotes must exist in the actual fetched bytes. It defaults to disabled and performs no paid inference. Review the example source quote and tenant before explicitly invoking:

~~~bash
PYTHONPATH=packages projects/03-multi-agent-research/.venv/bin/python projects/03-multi-agent-research/web_demo.py --config projects/03-multi-agent-research/web-config.example.json --question "LangGraph interrupts" --tenant demo --profile fixture --authorize-web
~~~

This command performs real external source reads only when deliberately invoked. The example is a configuration template, not captured live evidence. A controlled transport test exercises the complete acquisition/graph path; live acquisition remains unverified. System DNS resolution requires a deployment-level timeout in addition to socket/body deadlines.

## Acceptance checklist

- [x] Four real LangGraph nodes, two actual tools, strict permissions and durable audit.
- [x] Plausible unsupported claim rejected; conflicts preserved.
- [x] Bounded revision; exhausted budget and missing agent fail.
- [x] Poisoned sources gain no tools; tenant access is checked.
- [x] P15 approval handoff; rejected work cannot publish.
- [ ] Unseen natural-language evidence/model evaluation.
- [ ] Authorized live web acquisition through SSRF-safe transport.

## Case study and limitations

The migrated fixture uses four model-call slots and two tools. A deliberately wrong “99 minutes” claim fails against “15 minutes” evidence; one revision uses eight slots through the graph's conditional edge. Eleven isolated cases pass: the five preserved acceptance tests plus durable tool failure and five controlled local-output/deadline cases. Six core validator/authorization tests pass. Controlled local responses test the HTTP/JSON contract; they do not establish real-model competence.

On clean `10e53e8`, the current graph completed one real Qwen1.5B case in 6.91 seconds:
four model responses, two tools and a P15 approval with a durable local effect receipt.
`external_delivery` was false. [Current verification](../../docs/FUNCTIONAL_VERIFICATION.md)
and its [bounded record](../../docs/functional-verification-20260930.json) preserve the
source identity, model digests and measured outcome. This tests the curated evidence
contract; unseen research quality remains unverified.

The historical CrewAI qwen2.5:1.5b attempt received one real model response, then timed out on its second call after 70.02 seconds overall. It executed zero research tools and failed closed; no report was accepted. [Measured historical local attempt](../../artifacts/stateful/p03-local-attempt.json) includes its manifest, call budget, audit and failure. An earlier attempt failed before any model response because the isolated environment inherited a SOCKS proxy; that transport failure is preserved separately. Neither result establishes model competence or task success, and neither is a test of the current LangGraph stack.

The fact checker performs conservative curated-fact matching, not general natural-language entailment. Sources are synthetic and manually annotated. Fixture outputs exercise actual LangGraph ordering/tools but establish no language-model competence. The research run ledger and audit survive restart; interrupted in-flight graph/model calls are not resumed automatically. P15 supplies final-action checkpointing and durable local effect receipts.

## Interview walkthrough

Identify exactly which work LangGraph performs. Trace node state and runtime context, then tool evidence through immutable validation to the approval. Add a contradictory source, invent a source ID, and exhaust the call budget. Explain call counts versus token cost and why deterministic fixture success does not prove research quality.

References: [LangGraph state, nodes, edges and runtime context](https://docs.langchain.com/oss/python/langgraph/graph-api), [LangChain tool schemas](https://docs.langchain.com/oss/python/langchain/tools), [Ollama structured outputs](https://docs.ollama.com/capabilities/structured-outputs).
