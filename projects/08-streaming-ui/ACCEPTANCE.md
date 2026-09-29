# P08 acceptance and evidence

Implementation and verification are tracked separately. No fixture run demonstrates real
model quality. A single actual model smoke demonstrates integration, not broad accuracy.

| Requirement | Evidence | Status |
|---|---|---|
| Real PDF upload, document listing, exact page and PDF bytes | `tests/test_api.py`, actual browser upload/source case | Pass in fixture integration |
| AI SDK consumes Python UI stream protocol | `copilot.spec.ts`, built `ai` and `@ai-sdk/react` | Pass, both viewports |
| Display partial content and cancel | Browser cancellation case with explicit 180 ms fixture delivery delay | Pass, both viewports |
| Retry without duplicate messages | Browser cancel/error/disconnect cases plus atomic API claim test | Pass, both viewports |
| Malformed event and transport failure recovery | Browser malformed-stream and connection-reset cases | Pass, both viewports |
| Exact page source navigation and keyboard return | Source dialog, authenticated PDF blob, page fragment, Tab cycle and Escape focus restoration | Pass, both viewports |
| Server identity, RBAC, tenant isolation | API authorization, history separation and source tests | Pass |
| Full protected-output buffering | Output-size gate and no text delta on blocked response | Pass |
| Bounded multipart and chunked uploads | Actual request byte limiter and upload tests | Pass |
| Mandatory non-fixture validators | API fail-closed test plus actual local browser with the isolated Guardrails worker | Pass |
| Human approval, bound action and local idempotent effect | Actual ApprovalService API/browser tests | Pass |
| Inert rendering of HTML-like output | Browser adversarial response fixture; no injected DOM element or handler | Pass |
| Desktop/mobile visual inspection | Actual 1440×960 and 390×844 screenshots | Pass; source and approval layouts inspected |
| Actual local model reaches browser with citation | `tests/local.spec.ts`, real model metadata, original PDF page 2 | Pass, one desktop smoke |
| Provider-native cancellation | Synchronous RAG contract has no cancel handle | Unsupported, disclosed; delivery cancellation tested |
| Provider TTFT | Backend returns a complete answer before protected delivery | Not measured; null is intentional |
| Broad accessibility certification / production load | Dedicated audits/load environment not run | Not claimed |

## Current reproducible evidence

Final fixture browser run on 2026-09-29: **14 passed, 0 failed**, 23.621 seconds reported by Playwright.
The whole orchestration took 24,510.303 ms. Browser: Chromium 153.0.8010.0; one worker.
The PDF fixture SHA-256 was
`3be958fbf8db86e97d477dd2f4cc972ed175d378e324cf32c8b0acad77050a05`.
The final fixture and local runs record clean commit `c7b8a793f34795f3d2de148c1c5c211845e8b222`. Earlier development runs retain their null commit/dirty state under `artifacts/ui-pre-freeze`; they are not relabeled.

- `artifacts/ui/browser-evidence.json` records command, time, profile, versions, configuration,
  dataset hash, exit status, and artifact inventory.
- `artifacts/ui/playwright-results.json` contains test results and measured browser first-display
  attachments. Screenshots `desktop-*` and `mobile-*` are captured from the actual application.
- `services/api/demo.py` produced **15/15 checks** in the fixture profile. It is exposed through
  `uv run pais demo 08 --profile fixture`; it does not substitute for browser acceptance.
- `tests/test_api.py`: **20 passed in 2.82 seconds**, including actual chunked-body and
  protected output-size limits. Ruff and frontend TypeScript checks passed.

## Actual local browser integration

The separate final local run completed **1 passed, 0 failed** in 25.821 seconds reported by Playwright,
with 26,511.863 ms for the orchestration. It had no mocked responses and no fixture model.
It uploaded the same three-page synthetic PDF, asked for the safe operating pressure,
received the supported 8 bar answer, and inspected its extracted page-2 source in the browser.
The authenticated PDF blob and `#page=2` link were verified; a browser PDF renderer was not exercised.
The test ran real Ollama embeddings, CrossEncoder reranking, Qwen generation, and the
isolated mandatory Guardrails validator. Authentication used the explicit test-identity
switch, independently from the local model profile.

| Measurement | Observed value |
|---|---|
| Browser first display | 14,785 ms |
| Server first checked-answer delivery | 14,766.393 ms |
| Browser question-to-completed-answer check | 15,072 ms |
| Provider TTFT | Null; not measured by the buffered RAG contract |
| Generator | `ollama:qwen2.5:1.5b` |
| Generator digest | `65ec06548149b04c096a120e4a6da9d4017ea809c91734ea5631e89f96ddc57b` |
| Model-lock SHA-256 | `f6d72df65ac4aefb64f07aa7f4d4af0f547b312dafc222aa5a1f0204463ff45a` |
| Next build ID, shared with the final fixture run | `p57JVxelz6CAGXQnnOrB3` |

A fresh-checkout reproduction command is below. The final recorded run used the equivalent
`.venv-verified/bin/python` core interpreter; its exact command is retained in the JSON manifest:

```bash
PAIS_GUARDRAILS_PYTHON="$PWD/projects/06-security-guardrails/.venv/bin/python" \
  .venv/bin/python scripts/with_local_models.py -- \
  .venv/bin/python projects/08-streaming-ui/run_browser_tests.py --profile local
```

Evidence is in `artifacts/ui/local/browser-evidence.json`,
`artifacts/ui/local/local-smoke-measurements.json`, and the actual application screenshots
`desktop-local-conversation.png` and `desktop-local-source.png` in that same directory.
The test proves this integration path; one question does not establish broad answer quality
or a production latency target. Both local and fixture runs had zero skipped or flaky cases.

## Regression caught during implementation

The first full browser run failed cancellation at both viewports because partial answer text
arrived only when response compression flushed. First display in that diagnostic run was
411 ms on desktop and 406 ms on mobile with a 180 ms delay between fixture delivery chunks.
The proxy now disables compression and preserves `no-transform`. The unchanged semantic
cancellation check succeeds: first text is visible while Stop is available, cancellation
ends delivery, and retry restores one server message.
The final passing run recorded first browser display at **70 ms desktop** and **41 ms mobile**.
These are fixture presentation measurements with an intentional inter-chunk delay, not
production latency targets or provider token timings.

Next's hidden route-announcement element also shares the `alert` role. Error assertions now
scope to the application's composer alert. A further test-instrumentation issue occurred
when Chromium discarded a failed fetch's response body. The recovery test now verifies the
actual repeated request ID and compares UI messages with authoritative server history;
the API test separately checks stable assistant IDs across the failed/retried request.

The strengthened keyboard test also exposed Tab escaping the source dialog in the packaged
browser. The dialog now cycles focus between its interactive controls, and Escape restores
the invoking citation. Both viewport tests verify the cycle. Browser first-display timing is
armed by the actual stream status event, so a fast completed stream still records visible
text without mistaking an old assistant message for a new response.
