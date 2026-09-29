# Case study — A response that could be stopped

The useful outcome is a complete operating workflow: upload a PDF, ask a focused question,
inspect the supporting page, and review a source-bound note. A convincing chat animation
alone would not establish that these operations share the same identity and source version.
This implementation therefore keeps the trust and persistence rules in Python and makes the
browser consume their real results.

## Decisions that mattered

**One authority for identity.** A server credential resolves `Principal`; tenant IDs in client
headers and bodies cannot grant access. The same principal reaches documents, histories,
citations, approvals, and capability controls. Fixture credentials require an explicit server
switch. The frontend keeps its token in memory and fetches original PDFs with authentication
before creating local blob links, so credentials never appear in source URLs.

**Checked answers before display.** RAG returns a complete answer. The API validates citations,
filters protected text, limits output size, and only then emits text events. This introduces
buffering before the first visible text. Calling the resulting 64-character chunks provider
tokens would misrepresent what was measured. The UI reports browser first display; provider
TTFT is null. Stored original provenance supports subsequent validation; only protected
copies leave the API, including history and retry responses.

**Transactional retry.** The client retains its user message ID. SQLite binds that ID to a
principal, conversation, and question hash. A server assistant ID is deterministic. An
in-flight retry receives 409 instead of beginning another generation. A finished retry uses
the stored answer. A real error permits a new attempt under the original message ID. An
unknown process-crash outcome is deliberately left pending instead of silently assuming an
upstream request did not happen.

**Source-bound human decisions.** Approval cards make the proposed note and source readable.
The exact arguments, context version, and action fingerprint remain inspectable. Execution
is disabled by default; an administrator explicitly enables the local capability. Approval
is bound to the designated reviewer, action hash, and current source version. The workflow
engine records an idempotent local effect rather than sending anything externally.

## A defect the browser found

The initial API tests passed: the event sequence, chunk sizes, and stable IDs were correct.
In the browser, the cancellation test failed. Small SSE frames passed through Next response
compression, and the visible answer arrived too late to stop a partial response. The
diagnostic screenshots measured first display at 411 ms and 406 ms with deliberately paced
fixture chunks. API-only tests could not expose this presentation failure.

Disabling Next compression and preserving the API's `no-transform` header fixed delivery.
The browser test now observes answer text while the Stop control remains available, stops
delivery, retries the same message, and compares the result against server history. Both
desktop and mobile fixtures pass the same behavioral cases. See `ACCEPTANCE.md` for actual
counts and evidence paths; no deployment latency guarantee follows from this fixture timing.

The earlier development local browser smoke used the same built frontend. A three-page PDF was
uploaded through the interface, then the configured local embedding model, CrossEncoder,
and Qwen generator answered a pressure question. The mandatory isolated Guardrails worker
protected the completed answer before delivery. Browser first display was 14,042 ms, and
the extracted page-2 source opened successfully. This one measured path demonstrates that
the UI and real inference stack work together; the broader RAG release suite remains the
source of quality evidence. The saved model digest, model-lock hash, Next build ID, command,
timestamps, and actual screenshots make the scope of this result inspectable.

The final clean-commit repetition at `c7b8a793f34795f3d2de148c1c5c211845e8b222` passed with browser first display 14,785 ms and server first delivery 14,766.393 ms. Provider TTFT remains null. Its authenticated original-PDF link was checked without testing a browser PDF renderer. See the final values in `ACCEPTANCE.md`.

## Rejected shortcuts and current limits

No simulated screenshot stands in for a running interface. No fixture model silently stands
in for a missing local model. No client tenant header acts as authorization. HTML-like model
content is shown as text, and source links are constructed from validated resource IDs.

True downstream cancellation still depends on a provider API the synchronous RAG contract
does not expose. Stopping delivery therefore does not promise to stop CPU use or future
provider billing. The generation retains its admission lease and persists its result for
later replay. Process-crash reconciliation, production SSO, distributed multi-region state,
and large-scale UI load remain operational work outside the demonstrated scope.
