# Current functional verification — 30 September 2026

The local PDF copilot runs actual Qwen generation, MiniLM embeddings, CPU reranking,
mandatory isolated Guardrails validation and the Next.js interface. P03 uses native
LangGraph; CrewAI and its unpatched ChromaDB dependency are removed. `pais setup`
installs the required workers, local dev selects the standard validator/model lock,
and rejected demo acceptance returns a nonzero exit status.

The measured application commit is **`10e53e8c3282cca906e19807e7adf6f5eaf55821`**, clean
on macOS/ARM with Python 3.12.13. The [bounded machine-readable record](functional-verification-20260930.json)
contains commands, timestamps, model/dataset digests, report hashes and exact source
identity. Full runtime reports remain outside the public source. Private output paths
are normalized in the public record. Historical reports and all 139 manifest entries
retain their original bytes and commits.

| Actual check | Result | Scope |
|---|---|---|
| Native LangGraph + Qwen1.5B | Four model responses, two tools, 6.91 seconds; P15 approval executed with local receipt | One curated research case; no external delivery |
| Actual local SQLite lifecycle | 13/13 | Citations, conflict, replacement, deletion, malformed input and cross-tenant rejection |
| Actual local LanceDB lifecycle | 13/13 | Same contract using the separate LanceDB implementation |
| Actual model browser flow | 1/1, no skips/failures/flaky results | Upload PDF → Qwen answer → correct page 2 → original PDF link |
| Complete actual local regression | 144/144, zero errors/skips, exit 0 | 56 real Qwen responses, 16 disclosed excerpt summaries and 72 contract/abstention cases |
| Deliberately degraded actual local regression | 96 pass / 48 fail, zero errors/skips, exit 1 | Quality rejection with functioning prerequisites |
| macOS contract tests | 334 passed | Linux-only P14 supervisor tests are exercised in Linux CI |
| All 18 bounded fixture demo entrypoints | Exit 0 | Real local code paths with deterministic fixture inference; no deployment/quality claim |
| Fresh public branch clone | Frozen README setup and demo exit 0; 13/13 demo checks | 139 evidence hashes and all 327 then-current local Markdown targets checked |

[Linux Actions 36684470475](https://github.com/builtbyhuy/production-ai-systems/actions/runs/36684470475)
completed **success**: 337 Python tests, 11 LangGraph checks, three real Guardrails checks,
144/144 fixture release, degraded 96/48 with exit 1, 14 desktop/mobile browser checks,
Ruff, scoped Mypy, TypeScript and production build. CI tested clean PR merge `6c4a215`,
whose Git tree `38c6fb2e78b4c745c4f52a37e9fa764917bc2a19` exactly matches the application
commit above.

The unchanged blocking Trivy gate scanned all six lockfiles and reported **zero
HIGH/CRITICAL entries and zero secret findings**, reduced from the original 17 entries.
No advisory was suppressed and `ignore-unfixed` remains false. See the
[dependency audit](dependencies/AUDIT.md) for the historical installed-environment scope
and CPU-wheel lookup gaps. A zero-finding scan is point-in-time evidence.

The corrected P09 Linux stack also completed three actual offline SFT and three DPO
steps. Both adapters changed, the frozen backbone remained unchanged and both exports
reloaded with a maximum logit difference of 0.0. `release_approved` and
`substantive_quality_verified` remain false: this verifies compatibility, not useful
trained-model quality.

The [current README](../README.md) and [local provisioning guide](../projects/07-local-first/README.md)
provide explicit commands using the same Ollama model directory. The latest
[actual browser screenshot](images/copilot-local-20260930.png) is from the clean application
commit above; the older screenshot remains preserved separately.

Production deployment, external SaaS delivery, hostile-code sandboxing, live web research,
real vLLM serving and broad model quality remain outside these successful local checks.
The [criterion ledger](PROJECT_LEDGER.md) preserves their incomplete acceptance status.
