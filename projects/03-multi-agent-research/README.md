# P03 — Evidence-driven research crew

**Implemented. Actual CrewAI 1.15.23 orchestration and tools verified with deterministic fixture inference. The bounded actual-local Qwen attempt failed on a model-call timeout. General model quality and live web research are unverified.**

## Problem and architecture

CrewAI performs four sequential role tasks: supervisor, researcher, writer and fact-checker. It passes task context, executes corpus_lookup and inspect_evidence, validates typed outputs and invokes audit callbacks. packages/pais/research.py persists run state, budgets, deadlines, revisions, source identities, retrieval times, passages, hashes and claim linkage.

Researcher tools are limited to corpus lookup; fact-checker tools are limited to evidence inspection. Retrieved instructions cannot grant capabilities. Agent-returned evidence must match the actual corpus/tool retrieval, preventing invented sources. Acceptance requires every claim to match a quoted structured fact, at least one supported claim, and no unresolved contradictory values. Accepted work creates a durable P15 review before local publishing.

## Setup and commands

CrewAI is isolated from core dependencies and locked independently.

~~~bash
uv sync --frozen --project projects/03-multi-agent-research
.venv/bin/python -m pais demo 03 --profile fixture --output artifacts/stateful/p03-fixture.json
PYTHONPATH=packages projects/03-multi-agent-research/.venv/bin/python -m pytest projects/03-multi-agent-research/test_crewai.py -q
.venv/bin/python -m pytest tests/test_research.py -q
~~~

The public CLI selects the isolated interpreter. Telemetry/tracing are disabled. Fixture inference downloads no models. Local mode calls a provisioned loopback Ollama endpoint and never downloads weights. [Evidence](../../artifacts/stateful/p03-fixture.json).

Reproduce the bounded actual-local attempt with already provisioned models:

~~~bash
timeout --signal=TERM --kill-after=5s 120s .venv/bin/python scripts/with_local_models.py -- env PYTHONPATH=packages CREWAI_DISABLE_TELEMETRY=true OTEL_SDK_DISABLED=true projects/03-multi-agent-research/.venv/bin/python projects/03-multi-agent-research/local_attempt.py
~~~

The run permits at most eight model calls, zero revisions and a 90-second total budget. Explicit loopback model requests bypass inherited proxy settings, reject credentials and remote hosts, and never fall back to fixture inference.

The separate web mode uses WebResearchConfig, the P06 HTTPS allowlist/DNS-pinned transport, at most five sources, bounded bodies, two redirects and a total deadline. Quotes must exist in the actual fetched bytes. It defaults to disabled and performs no paid inference. Review the example source quote and tenant before explicitly invoking:

~~~bash
PYTHONPATH=packages projects/03-multi-agent-research/.venv/bin/python projects/03-multi-agent-research/web_demo.py --config projects/03-multi-agent-research/web-config.example.json --question "LangGraph interrupts" --tenant demo --profile fixture --authorize-web
~~~

This command performs real external source reads only when deliberately invoked. The example is a configuration template, not captured live evidence. A controlled transport test exercises the complete acquisition/crew path; live acquisition remains unverified. System DNS resolution requires a deployment-level timeout in addition to socket/body deadlines.

## Acceptance checklist

- [x] Four real CrewAI tasks, two actual tools, strict permissions and durable audit.
- [x] Plausible unsupported claim rejected; conflicts preserved.
- [x] Bounded revision; exhausted budget and missing agent fail.
- [x] Poisoned sources gain no tools; tenant access is checked.
- [x] P15 approval handoff; rejected work cannot publish.
- [ ] Unseen natural-language evidence/model evaluation.
- [ ] Authorized live web acquisition through SSRF-safe transport.

## Case study and limitations

The accepted fixture used four model-call slots and two tools. A deliberately wrong “99 minutes” claim failed against “15 minutes” evidence; one revision used eight slots. Five isolated acceptance tests and six core validator/authorization tests passed.

The actual-local qwen2.5:1.5b attempt received one real model response, then timed out on its second call after 70.02 seconds overall. It executed zero research tools and failed closed; no report was accepted. [Measured local attempt](../../artifacts/stateful/p03-local-attempt.json) includes its manifest, call budget, audit and failure. An earlier attempt failed before any model response because the isolated environment inherited a SOCKS proxy; that transport failure is preserved separately. Neither result establishes model competence or task success.

The fact checker performs conservative curated-fact matching, not general natural-language entailment. Sources are synthetic and manually annotated. Fixture outputs exercise actual CrewAI ordering/tools but establish no language-model competence. State/audit survive restart; an in-flight CrewAI token stream does not. CrewAI warns that the closure callback cannot serialize into its own checkpoint format. P15 supplies final-action checkpointing.

## Interview walkthrough

Identify exactly which work CrewAI performs. Trace tool evidence through immutable validation to the approval. Add a contradictory source, invent a source ID, and exhaust the call budget. Explain call counts versus token cost and why deterministic fixture success does not prove research quality.

References: [processes](https://docs.crewai.com/en/concepts/processes), [custom LLM](https://docs.crewai.com/en/learn/custom-llm), [tasks](https://docs.crewai.com/en/concepts/tasks), [telemetry](https://docs.crewai.com/en/telemetry).
