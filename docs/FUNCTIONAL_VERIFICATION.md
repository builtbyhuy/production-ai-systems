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

The later interface revision **`0a7c94e0b89f016a6345a7a3de53bc5b0974f0ab`** uses a single
light entrance, Geist typography and a verified product preview. Authentication,
readiness/error handling, form order and authenticated workspace markup are preserved.
At 390, 740 and 1440 pixels the entrance has no horizontal overflow, both access
controls remain above fold, the preview loads and browser errors are zero. Package
and dependency locks are unchanged by this interface refinement.

That clean revision passed all six actual local checks again: four Qwen research
responses/two tools with local approval, both SQLite/LanceDB lifecycles 13/13, actual
browser 1/1, full release 144/144 with 56 real responses, and a fresh complete degraded
run 96/48 with zero errors/skips and exit 1. Clean fixture browser 14 also passed.
[Linux Actions36687370179](https://github.com/builtbyhuy/production-ai-systems/actions/runs/36687370179)
passed the unchanged full CI, including 337 contracts, 11 LangGraph, 3 Guardrails,
browser 14, actual offline training/export/reloads and the six-lock security scan.
Its merge tree exactly matches the interface revision. The
[interface verification record](functional-verification-interface-20260930.json)
binds these reports to their commands, clean commit, dataset/model digests and hashes.

The first degraded attempt at this revision had one Ollama embedding HTTP400 runtime
error and is preserved separately. The same case then passed its normal and degraded
diagnostics, followed by the fresh complete zero-error run above. The provider's
precise cause remains unknown; no error was suppressed or expectation weakened.

The [current README](../README.md) and [local provisioning guide](../projects/07-local-first/README.md)
provide explicit commands using the same Ollama model directory. The latest
[actual browser screenshot](images/copilot-interface-local-20260930.png) is from clean
`0a7c94e`; the [earlier verified screenshot](images/copilot-local-20260930.png) and older
evidence remain preserved separately.

Production deployment, external SaaS delivery, hostile-code sandboxing, live web research,
real vLLM serving and broad model quality remain outside these successful local checks.
The [criterion ledger](PROJECT_LEDGER.md) preserves their incomplete acceptance status.
