# Interview walkthrough

## Demonstrate the actual path

1. Start the fixture API and Next app. Explain the visible fixture label before showing an
   answer. Upload a two- or three-page operating document and ask about a value on page two.
2. Inspect the browser request. It carries a credential, question, stable user message ID,
   and conversation ID. It does not choose an authorized tenant.
3. Follow `identity()` in `services/api/app.py`, then `prepare()` and `MessageStore.claim()`.
   The transaction binds the key and prevents a concurrent duplicate. Show the same request
   ID when a client retries.
4. Follow `generate()`: shared admission lease, RAG, citation validation, output protection,
   durable completion, and release. Explain why unfiltered model/source evidence is not
   automatically included in a public API response.
5. Walk through `chat_stream()` and `services/api/streaming.py`. Explain the AI SDK v1 header,
   message start, text block ID, delta, citation part, finish metadata, and terminal marker.
   Show the `DefaultChatTransport` configuration in `app/page.tsx` consuming this protocol.
6. Open the citation. The API authorizes the exact document and version, extracts that page,
   and separately returns original PDF bytes. Escape closes the dialog and restores focus.
7. Draft a note. Inspect the readable proposal and exact action details. Explicitly enable
   local execution, approve the bound action, and show its executed status. A repeated
   decision must preserve one local effect.

Repeat the question in the documented local browser runner to show real inference. Keep
the explicit test-identity switch separate from `PAIS_PROFILE=local`, and point to the
mandatory Guardrails interpreter. The saved smoke used Qwen with a recorded digest and
displayed the checked answer after 14,785 ms. Explain why that timing includes retrieval,
generation, and validation, and why a successful single question is not a quality benchmark.

## Questions you should answer without hand-waving

**Why buffer the answer if this is a streaming UI?** The existing RAG contract returns a
complete answer, and mandatory protection runs before text is displayed. SSE provides
incremental delivery and cancellable presentation, but it does not change the provider
contract. State the latency cost clearly and do not call delivery chunks provider tokens.

**Why were API tests insufficient?** They verified the backend stream sequence, but Next
compression changed when the browser could see it. Actual browser tests found the failure
to stop partial output. The fix and regression check operate through the complete proxy.

**What happens if the user closes the page during generation?** The delivery task ends.
The synchronous provider can continue, so a tracked background task retains and renews the
admission lease, records the result, and releases admission when it actually finishes. A
retry reuses this result; a pending retry does not start duplicate work.

**What if the process dies?** The durable claim may remain pending. Automatically expiring
the claim could repeat a paid or stateful upstream action. This implementation exposes that
uncertainty and documents operator reconciliation as a limitation. A stronger system would
tie durable provider request IDs and outcome reconciliation to a recoverable worker.

**Does a citation prove a claim is true?** It proves a checked relationship to a specific
stored page/span under this implementation's validation policy. It does not establish the
real-world truth of the document. Inspect the original and use P01/P04 evaluations to assess
retrieval and grounding quality beyond this one browser demonstration.

**Why not render model Markdown/HTML?** The narrow workflow does not require executable or
arbitrary linked content. Plain text with separately typed citation controls gives a small,
testable surface. The adversarial HTML fixture verifies that no DOM element or handler runs.

## Changes you should be able to make yourself

- Add a metadata field to the typed message contract, emit it in Python, and render it in
  React without changing message IDs. Update the browser assertion to verify the real event.
- Change the upload size cap in both API enforcement and the UI explanation. Keep the
  chunked-body test; checking only `Content-Length` is insufficient.
- Add another approved local action using an explicit schema and capability gate. Include
  its readable preview, exact inspection details, binding checks, and one-effect replay test.
- Introduce a genuinely cancellable async model adapter. Propagate the signal through the
  provider call, keep outcome/cost reconciliation, and replace the current limitation only
  after a test proves downstream cancellation.
- Adapt source inspection to a richer PDF renderer while preserving the original version,
  bearer authentication, keyboard focus behavior, and inert handling of source text.
