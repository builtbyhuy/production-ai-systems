# Current state

The integrated local PDF copilot and all 18 related implementation tracks exist.
This is an engineering lab portfolio; complete production acceptance remains unfinished.
Read docs/REDTEAM.md for the 30 September source review and docs/PROJECT_LEDGER.md for
criterion-level historical results.

## Redteam revision

- Hardened release-report binding against subsets, unknown IDs, modified metrics,
  missing model evidence and mismatched committed source/datasets.
- Unified writer authorization; guarded memory and standalone vector reads.
- Offloaded cached reply validation without releasing admission on cancelled delivery.
- CI now runs complete positive/degraded fixture evaluations with the isolated worker.
- Public-facing README leads with one integrated app and honest module/evidence scope.
- Selected historical evidence is tracked through artifacts/PUBLIC_EVIDENCE_MANIFEST.json;
  runtime binaries, model weights, databases and installed dependencies remain excluded.

Baseline reproduction: 262 Python checks, fixture release 144/144 and degraded 96/48,
SQLite/LanceDB fixture lifecycle 13/13, 14/14 fixture browser checks, UI build and scoped
lint/types. Focused repaired checks: security/API 87, release/evaluation 25, Qdrant 59.
Final committed-revision checks are recorded in docs/REDTEAM.md when completed.

## Historical source identities

- c7b8a793f34795f3d2de148c1c5c211845e8b222: actual-model release 144/144,
  degraded 96/48, core262, local/browser/stateful checks; source hashes match Git objects.
- 9f8e0fdf41f3a170004c297c24b18ab01da7f25b: isolated training CLI dependency
  correction and actual tiny SFT/DPO reproduction, quality still rejected.
- a1e0a0c2068f3e86c90257c6c246ac2fc4afad34: original documentation handoff.

Historical reports retain their commits, timestamps and dirty flags. They do not attest
the repaired revision. Current actual-model results have their own clean source identity below; no production-deployment claim is made.

## Remaining gates

Historical installed-environment audit coverage gaps, hostile-code sandbox and real inference
serving remain unresolved. External SaaS, registry/cluster rollout/rollback, downstream
receipt reconciliation and upstream submission still require independently verified targets.
Router savings, 10k-vector quality and tiny training quality are unproven or failed.
The eight audit cases reuse development templates; direct source access was reviewed here.

## Current functional revision

The owner approved P03 CrewAI→LangGraph on 30 September 2026. The research graph
retains fixed roles/tools, tenant/source validation, deadlines, budgets and P15 review.
Clean application `10e53e8` passed actual local research (four Qwen responses/two tools,
executed local approval), SQLite/LanceDB13/13 each, real-model browser 1/1 and full local
release 144/144. Degraded local96/48 exits1 with zero errors/skips. All18 bounded fixture
demo entrypoints run. Local334 contracts, LangGraph11 and realGuardrails3 pass.

[Linux Actions36684470475](https://github.com/builtbyhuy/production-ai-systems/actions/runs/36684470475)
passed337 contracts, both complete fixture gates, browser 14, lint/types/build and actual
offline SFT3/DPO3/export/reloads. Its clean merge tree matches `10e53e8` exactly. The
unchanged security gate now reports zero HIGH/CRITICAL and secret findings across all
six locks. P06/P09 compatible upgrades and approved P03 removal resolved the original17
blocking entries without suppressing advisories or weakening expectations.

`pais setup` installs the required isolated workers. Local dev selects the standard
model lock and Guardrails worker, respecting explicit overrides. Rejected demo acceptance
now returns1. README documents explicit Ollama model-directory startup. Small local model
weights remain ignored; historical CrewAI reports and139 public evidence hashes are preserved.
See [current verification](docs/FUNCTIONAL_VERIFICATION.md) and its bounded record.

The later clean interface revision `0a7c94e` retains authenticated workspace behavior
and improves the entrance with Geist, a single light theme and an exact verified
preview. Type/build and 390/740/1440 layout/focus/contrast checks pass. Fixture browser 14
and all six actual local checks pass again, including release 144/144 and fresh
degraded 96/48 with zero errors/skips. The first degraded attempt's one embedding HTTP400
error is preserved separately; its provider cause remains unknown. No exception was
swallowed. Linux Actions36687370179 passed the full unchanged CI on an identical
merge tree. The new bounded interface record preserves the earlier 10e evidence.

The mobile cancellation fixture check now observes partial delivery and activates the
visible Stop control in one browser turn. This removes a race between driver commands
within the unchanged 180 ms frame interval. It retains stopped/retry/message-count
checks and also verifies identical request/conversation IDs. Targeted desktop/mobile
checks pass without retries or timing/expectation changes. Application handlers and
model dependencies are unchanged; full CI remains the publication gate.

Main Actions36691053698 exposed a timeout/replay test race: fixed sleeps assumed that
generation and its subsequent validation/durable completion had finished. HTTP409
correctly retained the active generation claim. The test now holds generation with
an event, verifies504 and409, then releases it and awaits the actual tracked background
task before asserting200 replay and one generation. Waits have bounded failure deadlines;
request timeouts, runtime behavior, replay assertions and CI gates remain unchanged.
The failed main log is preserved; the follow-up's complete CI must pass before merge.

The model regression is synthetic and does not establish broad quality or authorize a
production cluster. Remaining acceptance gates above remain independent. Continue with:

```bash
uv run --no-sync pais setup --profile local
# Start Ollama with the exact model directory as documented in README.
PAIS_ALLOW_FIXTURE_AUTH=1 uv run --no-sync pais dev --profile local
```

Publication reproduction on 30 September 2026 used clean `48649a9` on macOS/ARM:
332 Python checks, 144/144 fixture evaluation, degraded 96/48 with exit 1, 14/14 browser,
5 CrewAI and 3 Guardrails framework checks, Ruff, scoped Mypy, TypeScript and UI build.
The complete Python command exits 2 here because P14's three supervisor checks require
Linux `/proc` and affinity. No tests or security gates were weakened. Historical Linux
335 remains bound to `c74195a`. See [publication verification](docs/PUBLICATION.md).
Public target: https://github.com/builtbyhuy/production-ai-systems. Confirm its live
commit and Actions outcome before describing external status:

```bash
gh repo view builtbyhuy/production-ai-systems
gh run list --repo builtbyhuy/production-ai-systems --limit 5
```

Use Python3.12/uv; Node24 for the UI; redis-server on PATH for full native tests.

```bash
uv sync --frozen --group dev --extra vectors --extra router --extra workflows
uv sync --frozen --project projects/04-eval-harness
uv run --no-sync pais doctor
uv run --no-sync pytest tests projects/13-agent-memory/test_comparison.py projects/14-inference-server/test_supervisor.py -q
uv run --no-sync pais eval --profile fixture --suite release
```

A new actual-model candidate needs a clean committed tree and its own complete local gate.
Do not infer external publication from local commits; inspect the configured remote and
publication record before describing GitHub, LinkedIn, deployment or upstream status.
