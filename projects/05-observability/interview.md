# Interview walkthrough

Begin with `Telemetry.record_request` and the API stream-finally block. Produce an HTTP-200 SSE
error and explain why counting only response status would miss it. Compare first display with
provider TTFT and describe the buffering policy that creates the difference.

Read the histogram bucket list and a dashboard p95 expression. Explain why durations use
seconds, how buckets affect quantile precision, and why `request_id` is absent from metric labels.
Change a route to an unexpected user-generated path and demonstrate that it maps to `other`.

Walk a `traceparent` from API producer to persisted job record to a separate worker. Find the
same trace ID in Tempo and inspect the parent span relationship. Explain what an in-memory span
test proves and what the native distributed trace adds.

Open the ledger panel. Explain each series: an estimate is not a charge, reported tokens are
not an invoice, an unknown hold is not zero. Show the raw SQLite-derived snapshot and the saved
Prometheus response agreeing on the displayed figure.

Run the alert drill, observe firing and resolved notifications, then inspect the rule's minimum
observations and hold duration. Explain why the thirty-minute anomaly baseline is unverified in
a short fresh run. Be able to change a threshold intentionally and rerun the drill without
silently weakening the P11 release gate.
