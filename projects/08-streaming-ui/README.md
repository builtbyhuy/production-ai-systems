# P08 — Streaming operations copilot

An accessible Next.js workspace for asking versioned PDFs, inspecting the exact cited page,
and reviewing an action before its local execution. The UI is connected to the shared RAG,
identity, security, telemetry, approval, and capability-control implementations.

**Verified:** 20 API contract tests, 14 fixture browser cases across desktop and mobile, and
one browser smoke through actual local embeddings, reranking, generation, and Guardrails.
The local smoke opened the supporting page from the original PDF. See
[acceptance](ACCEPTANCE.md) for measured results and their limits. Fixture answers are visibly
labeled and do not demonstrate model quality.

## Architecture

`apps/copilot/` uses Next.js, React, `@ai-sdk/react` and the AI SDK's `DefaultChatTransport`.
`services/api/app.py` resolves a trusted `Principal`, applies admission and security rules,
and calls `pais.rag.RAGService`. `MessageStore` atomically claims each user message and stores
the completed answer for reconciliation. Every query, original PDF, extracted page, message
history, approval, and execution flag is scoped to trusted identity.

The Python backend implements **AI SDK UI message stream v1**, with `start`, `text-start`,
`text-delta`, `text-end`, `data-citations`, `finish` and `[DONE]`. The actual AI SDK consumes
these events in the browser; this is not a hand-built imitation of a chat hook. Compatibility
decisions and official sources are in [COMPATIBILITY.md](COMPATIBILITY.md).

The complete answer is validated and redacted before protected content is delivered. The
buffer is limited to 32,768 answer characters, 16 citations, and 128 KiB of serialized answer
data. Delivery uses 64-character chunks and ASGI backpressure, with no unbounded producer
queue. These are **presentation chunks of a checked answer**, not provider tokens. Browser
first display and server first delivery are measured separately; provider TTFT remains null.

## Start the workspace

From the repository root, install the locked Python environment and frontend dependencies:

```bash
uv sync --group dev
cd apps/copilot
npm ci
npm run build
```

Run the API from the repository root:

```bash
PAIS_ALLOW_FIXTURE_AUTH=1 uv run pais dev --profile fixture
```

In a second terminal, run the frontend and open `http://127.0.0.1:3000`:

```bash
cd apps/copilot
npm run start
```

Click **Open fixture workspace**. Upload a PDF, ask a question, and click a page citation.
The source dialog shows the cited quote, extracted page text, and an authenticated original
PDF link with its page fragment. Press Escape to return to the citation.

In **Approvals**, draft a note and name its reviewer. Action execution starts disabled; an
administrator must explicitly enable local execution. The primary card shows the proposed
note and source; **Inspect exact action and fingerprint** exposes all binding details.
Approval submits the exact action hash and source version. A repeated decision uses the
same durable local effect. No external message or publication is sent by this demo.

## Authentication and environment

| Setting | Purpose |
|---|---|
| `PAIS_DB_PATH` | Authoritative shared SQLite state; default `var/pais.db`. |
| `PAIS_PROFILE` | `fixture`, `local`, `connected`, or `deployment`. |
| `PAIS_ALLOW_FIXTURE_AUTH=1` | Explicitly enable the three documented test identities. Otherwise fixture credentials fail. |
| `PAIS_AUTH_TOKENS` | Trusted server JSON mapping credentials to `{subject, tenant_id, roles}`. Never a client tenant override. |
| `PAIS_GUARDRAILS_PYTHON` | Absolute interpreter path for the isolated, mandatory Guardrails worker in non-fixture profiles. |
| `PAIS_REQUEST_TIMEOUT_SECONDS` | HTTP waiting deadline, default 60 seconds. Provider work can outlive delivery. |
| `PAIS_API_URL` | Next proxy destination, default `http://127.0.0.1:8000`; rebuild after changing a production build's rewrite. |
| `PAIS_OTLP_ENDPOINT` | Optional configured telemetry exporter endpoint. No exporter is required for local operation. |

Fixture identities are `fixture-admin` and `fixture-reader` in `fixture-tenant`, plus
`fixture-other` in `fixture-other-tenant`. The browser keeps its credential in memory.
Conversation IDs may be persisted locally, but they never authorize access. Server tokens
are hashed by `CredentialStore`. Missing production validators return 503 and protected
work is disabled. `/api/health` reports this state; `/api/ready` returns a readiness failure.

## Repeatable demonstrations and verification

```bash
uv run pais demo 08 --profile fixture --output artifacts/p08-api-demo.json
uv run pytest tests/test_api.py
cd apps/copilot
npm run typecheck
npm run build
cd ../..
uv run python projects/08-streaming-ui/run_browser_tests.py --profile fixture
```

The browser runner starts FastAPI, Next, and Playwright together in one network namespace,
uses a fresh temporary database, and records actual desktop and mobile screenshots. It
uses the pinned Linux Chromium package when available. On other platforms, install the
normal Playwright browser with `cd apps/copilot && npx playwright install chromium`, or
set `PAIS_BROWSER_EXECUTABLE` to a compatible installed browser. The extraction workaround
keeps current-user archive ownership; it does not change browser contents or relax network
controls. The browser's test launch is **not** the P06 untrusted-execution sandbox.

After P07 models and the isolated P06 validator have been provisioned, the complete actual
local stack can be checked with:

```bash
PAIS_GUARDRAILS_PYTHON="$PWD/projects/06-security-guardrails/.venv/bin/python" \
  .venv/bin/python scripts/with_local_models.py -- \
  .venv/bin/python projects/08-streaming-ui/run_browser_tests.py --profile local
```

This single smoke test runs a genuine PDF upload, local generation, embedding retrieval,
reranking, checked SSE delivery, and browser page navigation. It does not replace the full
RAG evaluation suite. Missing models or validators fail the test; no fixture substitution is
allowed in the local profile.

The measured local run displayed its checked answer after **14,042 ms** in the browser;
server first delivery was **14,024.104 ms**. This was one CPU run with a three-page synthetic
operating manual. The API buffers the answer for validation, so neither value is provider
TTFT. The test used an explicitly enabled test identity while keeping actual local models
and the mandatory non-fixture output validator active.

## Failure behavior and limits

- Stop aborts browser delivery. The synchronous RAG provider contract has no interrupt
  handle; generation may continue consuming CPU and, for a future billed provider, cost.
  A heartbeat keeps its admission lease alive until work ends. Retrying a pending message
  returns 409 without starting another generation; after completion, retry replays the result.
- A provider error makes that message retryable. A process crash can leave a pending claim;
  it is deliberately not reclaimed on a guessed expiry. Operator reconciliation after
  verifying upstream state is still a documented operational limitation.
- Malformed streams and disconnects are shown as incomplete responses with a retry action.
  Exact source references remain bound to the original version. Deleted sources prevent
  old answers from being replayed; archived versions remain inspectable if authorized.
- HTML-like model output is rendered as inert React text. Model-generated HTML and links
  are not executed. Original source pages remain authorized document views.
- Upload bodies, including chunked requests, are bounded before multipart spooling. PDF
  content is limited to 10 MiB. The API is a single SQLite-backed demonstration deployment;
  multi-region state, production SSO, large-scale load, and exhaustive assistive-technology
  compatibility have not been demonstrated.

See [CASE_STUDY.md](CASE_STUDY.md) for the measured streaming defect and its fix, and
[INTERVIEW.md](INTERVIEW.md) for the code walkthrough.
