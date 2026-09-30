# Portfolio publication verification

Checked 30 September 2026. This is an independent, AI-assisted local engineering lab.
Fixture checks verify application and failure contracts; they do not establish general
model accuracy or production deployment acceptance.

## Restored source and preserved evidence

The supplied ZIP manifest identifies current source
`48649a9cf20f2f504243c566dca9c9cc6de5af85` and tested application
`c74195a7f4f49d6ddf0e40b5262fa5d4062aac27`; both match the independent bundle clone.
Their difference is documentation and final evidence only. No application source,
expectations, dependency lockfiles or security gates were changed for publication.

All 896 handoff entries match their declared sizes and SHA-256 hashes. All 139 entries
in [the public evidence manifest](../artifacts/PUBLIC_EVIDENCE_MANIFEST.json) match.
An additional comparison of 40 historical clean reports checked 9,670 source-file hashes
and 240 dataset hashes against their declared Git objects, with no mismatches. Dirty
historical reports retain their original status.

The original six-commit `main` history was screened in full: 465 unique blobs,
14,480,341 bytes, with no size skips. Key/token/private-data patterns found only explicit
synthetic rejection fixtures. No runtime, installed dependencies, private credentials,
databases or model weights were found in that reviewed history. This bounded pattern
screen is not proof that every conceivable secret is absent. The primary screenshot
was visually inspected; the sole tracked PDF reproduces byte-for-byte from synthetic
browser-test input. All 313 local Markdown references and 80 ledger evidence references
resolve in the clone. The raw private handoff is not included in the public tree.

## Newly executed checks

These checks ran on **clean `48649a9`**, before this publication documentation changed.
Environment: macOS 27.0 / ARM64, Python 3.12.13, uv 0.10.9, Node 24.19.0,
Redis 8.10.2 and pinned Playwright Chrome for Testing 153.0.8010.12 for macOS.
The existing frozen locks installed successfully; no large models or paid providers were used.

| Check | Observed result |
|---|---|
| Exact README full Python command | Exit 2 during collection: the Linux supervisor imports `/proc/self/stat`, unavailable on macOS. This is an unmet platform prerequisite, not a passing suite. |
| `pytest tests projects/13-agent-memory/test_comparison.py -q` | 332 passed, zero skips, two upstream deprecation warnings, exit 0. Includes actual Redis/Celery recovery. Three Linux supervisor tests were not rerun on this machine. |
| Ruff across declared source scope | Passed, exit 0. |
| Mypy for contracts and operations | Passed, exit 0. |
| Full isolated fixture release evaluation | 144 passed, zero failures/errors/skips, exit 0; deployment eligibility remains false. |
| Full isolated deliberately degraded fixture | 96 passed / 48 failed, zero errors/skips, exit **1**. |
| P01 fixture demo | 13/13 lifecycle checks passed, exit 0. |
| Real CrewAI framework contracts using fixture responses | 5 passed, zero skips, exit 0; upstream deprecation warnings. |
| Real Guardrails framework enforcement | 3 passed, zero skips, exit 0; upstream deprecation warnings. |
| TypeScript and Next.js production build | Both passed, exit 0, under Node 24.19.0. |
| Desktop/mobile fixture browser | 14 passed, zero skips/unexpected/flaky cases, exit 0; 1440×960 and 390×844. Actual source-page screenshots inspected. |

The earlier **335-test Linux result on `c74195a`** remains historical evidence in
[REDTEAM.md](REDTEAM.md); it is not relabelled as a new macOS run. The full Linux command
and blocking supply-chain gate remain enabled in [CI](../.github/workflows/ci.yml).

Commands used, from the repository root (choose a new output directory):

```bash
uv sync --frozen --group dev --extra vectors --extra router --extra workflows
uv sync --frozen --project projects/04-eval-harness
uv run --no-sync pytest tests projects/13-agent-memory/test_comparison.py projects/14-inference-server/test_supervisor.py -q
# The command above needs Linux. The explicit macOS scope was:
uv run --no-sync pytest tests projects/13-agent-memory/test_comparison.py -q
uv run --no-sync ruff check packages services tests projects scripts infra
uv run --no-sync mypy packages/pais/contracts.py packages/pais/operations.py
uv run --no-sync pais eval --profile fixture --suite release --output artifacts/new-checks/release-fixture.json
uv run --no-sync pais eval --profile fixture --suite release --degraded --output artifacts/new-checks/degraded-fixture.json
uv run --no-sync pais demo 01 --profile fixture --output artifacts/new-checks/demo01.json
uv sync --frozen --project projects/03-multi-agent-research
uv sync --frozen --project projects/06-security-guardrails --group dev
PYTHONPATH="$PWD/packages:$PWD" projects/03-multi-agent-research/.venv/bin/python -m pytest projects/03-multi-agent-research/test_crewai.py -q
PYTHONPATH="$PWD/packages:$PWD" projects/06-security-guardrails/.venv/bin/python -m pytest projects/06-security-guardrails/test_guardrails_real.py -q
cd apps/copilot
npm ci
npm run typecheck
npm run build
npx playwright install chromium
# On macOS, use the installed Playwright browser instead of the packaged Linux binary:
export PAIS_BROWSER_EXECUTABLE="$(node -e 'console.log(require("@playwright/test").chromium.executablePath())')"
cd ../..
uv run --no-sync python projects/08-streaming-ui/run_browser_tests.py --profile fixture --output-dir artifacts/new-checks/browser
```

Fixture report timestamps are `2026-09-30T04:50:20.714922Z` and
`2026-09-30T04:50:45.422414Z`. Both record clean source snapshot SHA-256
`57d3f677a3d16515170ad333563ab4de9b6caeaf7c6fb59f6cafc0b65742b97b`.
Raw machine-local reports/logs and profile backups are retained privately, outside this
repository. Their observed hashes are preserved here as a record, not public raw downloads:

| Machine-local record | SHA-256 |
|---|---|
| Positive fixture JSON | `62f90b6a3a6c1ab7ab606e3afc194dd3792f8db2b2063b247aea3a94f367cacb` |
| Degraded fixture JSON | `3c95b0abb61b7893f048eff64071eba6dca3d8474404435344a3db0a99781a31` |
| macOS Python transcript | `d0f29a650f42f23826f6ec186efd139830e4cd8211f1c8015dcaeaf29cc4c522` |
| Full-command prerequisite failure transcript | `910cc057aceaead4627b8a85f50e65870e4682640983c1b18555f532f8a9c187` |
| UI type/build transcript | `014ab72dce4dcd5588f06e7e93ae7f50efd213d013cb0ba3dcd2312c5d05aa19` |

## Public-clone instructions and remaining limits

Use the current [README](../README.md) to clone and run the application. The original
[VERIFICATION.md](VERIFICATION.md) describes an older full evidence archive: its
`RESTORE.md` reference is obsolete for this handoff. Historical prose in
[artifacts/README.md](../artifacts/README.md) also names archive-only
`final/verification-index.json`, `pip-audit-core.json` and `pip-audit-training.json`.
These are not public-clone prerequisites. Public acceptance hyperlinks resolve to
the reviewed selected evidence; the public manifest defines the historical allowlist.

Reported dependency advisories, scan coverage gaps, disabled hostile-code execution,
unavailable vLLM serving and unfinished deployment criteria remain open. The historical
actual-model result belongs to `c7b8a793f34795f3d2de148c1c5c211845e8b222` and includes
56 Qwen responses, 16 deterministic excerpt summaries and 72 contract/abstention cases.
No new actual-model or production release is claimed. GitHub Actions status must be
read from the actual run; no passing badge is added here.
