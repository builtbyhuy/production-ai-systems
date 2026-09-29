# Case study — A successful HTTP status can contain a failed stream

The first useful instrumentation decision was to measure stream completion separately from
response headers. Once an SSE response starts, an error may arrive as a protocol event while
the HTTP status remains 200. The API records the stream's actual terminal result and separately
records first-display delay. The real API fixture demo captured exactly that case: HTTP 200,
an error event, and a 5xx-class application metric.

Cost metrics required a different distinction. Prometheus counters reset with process restarts,
and provider timeouts may not produce usage. The dashboard therefore exposes the durable ledger's
reported/reconciled amounts and outstanding reservations as separate gauges. Unknown holds are
visible, and the native drill compares the authoritative ledger number with a real Prometheus query.
Its illustrative prices are explicitly simulated; the comparison is consistency evidence, not an
invoice or economic claim.

Trace protection happens before export. A wrapper admits only approved attributes, suppresses
raw exception events, and propagates only a validated `traceparent`. A queue record contains the
carrier; the worker reconstructs the parent context after a durable handoff. The native drill
retrieves a trace containing producer and worker spans from Tempo rather than inferring success
from a configuration file or an SDK import.

The dashboard includes deliberately empty measurements when the underlying signal does not exist.
For example, a buffered provider does not establish provider TTFT, and a missing grounding judge
does not emit a passing quality counter. This is useful operational information, especially for
release gates that must fail closed when quality measurements are absent.

Both execution paths remain reproducible. Compose expresses service topology; the native runner
allows integration evidence where containers are unavailable. The runner verifies official
binary checksums, bounds runtime memory, stores actual observations, stops its children and keeps
short-lived Grafana credentials out of deliverable evidence. A native passing drill does not
prove container deployment, long-term anomaly quality, or production load capacity.

The first full native run exposed a capacity assumption. All functional checks passed, then
Chromium startup pushed the observed sum of process-tree RSS to 1,153,880,064 bytes, above the
declared 1 GiB profile. The supervisor stopped the children and recorded failure. That evidence
is preserved under `artifacts/p05-native-initial-1gib`; a separate rerun explicitly declares a
1.5 GiB ceiling, including the browser. Go's soft memory targets do not substitute for this
live process-tree measurement. The RSS sampler also accounts for the executor's distinction
between namespace PIDs and the host PIDs exposed under `/proc`.

Another failure looked like a missing login field but came from the browser environment.
Grafana's actual page error was `Invalid language tag: en-US@posix`; its JavaScript stopped
before the form rendered. A narrow browser probe reproduced the problem and then verified
successful authentication with an explicitly configured `en-US` locale. The full monitoring
drill was repeated with the same corrected browser context so its screenshot represents the
actual collected traffic.

The accepted run completed in 155.37 seconds. Both alerts fired and resolved, the worker
succeeded, Tempo returned the handoff trace, and Prometheus matched the ledger's simulated
40 micro-USD amount. Peak process-tree RSS was 1,448,546,304 bytes under the declared
1,610,612,736-byte cap. The actual screenshot includes the cost panel; four lower panels were
not mounted by Grafana's viewport-based rendering and remain outside the screenshot's verified
scope. Their twelve-panel dashboard definition was retrieved from Grafana's running API.
