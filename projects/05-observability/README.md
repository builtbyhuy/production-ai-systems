# P05 — Application observability and an executed alert drill

**Implementation:** real OpenTelemetry instrumentation, Prometheus metrics, provisioned Grafana
dashboard, Tempo tracing, Alertmanager rules and a local alert destination. **Verified:** actual
FastAPI traffic, native Prometheus/Grafana/Tempo/Alertmanager, a separate worker trace, and both
error and latency alerts firing and resolving. Model responses and prices in this integration
drill are explicitly fixtures. The container profile remains separate and unexecuted.

## What is measured

`Telemetry` instruments API requests, retrieval/reranking, model calls, routing, approvals and
durable jobs. Queue carriers persist W3C `traceparent`. Request IDs belong in spans, never in
Prometheus labels. Spans use an attribute allowlist and omit prompts, documents, model responses,
credentials, arbitrary URL parameters, baggage and raw exception messages.

All latency histograms use seconds and the same documented buckets. API response-header timing
is distinguished from stream completion. Protected first-display delay is separate from provider
TTFT; TTFT remains absent when a provider measurement is unavailable. Unknown tokens and costs
remain visibly unknown. Ledger gauges refresh from durable totals instead of reconstructing
authoritative spending from restartable metrics counters.

| Metric | Unit / bounded labels |
|---|---|
| `pais_requests_total` | count; route template, status class, release |
| `pais_request_duration_seconds` | seconds; route template, release |
| `pais_first_display_seconds` / `pais_provider_ttft_seconds` | seconds; bounded route/model, release |
| `pais_provider_attempts_total` | count; configured model, outcome, release |
| `pais_model_tokens_total` / `pais_usage_unknown_total` | reported tokens / unknown-attempt count |
| `pais_ledger_cost_microusd` | integer micro-USD; reserved, estimated, reported, reconciled, unknown_hold |
| `pais_budget_utilization_ratio` | committed cost divided by cap |
| `pais_queue_depth` / `pais_retries_total` | depth/count; named queue or retry kind |
| `pais_quality_observations_total` | measured pass/fail counts; metric kind, release |

Operator-controlled `PAIS_RELEASE` identifies one deployment version. The P11 canary uses the
pod-template hash to scope observations. Missing quality observations remain missing; an absent
metric cannot become an invented passing score.

## Component and actual API evidence

```bash
.venv/bin/pais demo 05 --profile fixture --output artifacts/p05-component.json
.venv/bin/python -m pytest tests/test_observability.py -q
```

The component demo sends actual FastAPI stream requests, including explicit fixture failure
injection and delayed protected delivery. It exports real spans and metrics. Its initial measured
run produced nine spans, a correctly counted stream error despite HTTP status 200, and a roughly
0.4-second delayed response. These are application instrumentation measurements; they are not
Grafana/Tempo/Alertmanager deployment evidence or model-quality measurements.

## Repeatable native stack drill

The native option uses pinned official Linux distributions and verifies their publisher-provided
SHA-256 checksums before extraction. The versions are reproducibility pins, not a claim that they
are the latest security releases. Review/update them before production use. No paid model calls
or cloud resources are used. Downloads are bounded below 1 GB compressed. The runner defaults to
a combined 1 GiB RSS budget. The command below explicitly selects a 1.5 GiB profile that includes
the Chromium screenshot process. A first run completed the alert and trace checks but exceeded
the original budget during browser startup at 1,153,880,064 bytes; that failed evidence is retained
under `artifacts/p05-native-initial-1gib`. This larger budget was declared before the rerun. The
supervisor samples real process-tree RSS using host PID/namespace PID mapping, includes browser
descendants, and stops the run on a cap breach. Shared pages can count toward more than one process.

```bash
.venv/bin/python projects/05-observability/provision_native.py --target .tools/monitoring
.venv/bin/pais evidence --profile deployment --output artifacts/p05-native-run.json -- \
  .venv/bin/python projects/05-observability/native_drill.py \
  --binaries-dir .tools/monitoring --output artifacts/p05-native --max-rss-mib 1536
cp .tools/monitoring/manifest.json artifacts/p05-native-first-pass/binaries-manifest.json
```

The supervisor starts a separate API, Prometheus, Grafana, Tempo, Alertmanager and test alert
sink, all on loopback. It sends real API traffic, injects stream failures, measures a slow
protected response, persists a job's trace context, and executes the job in another process.
It retrieves that distributed trace from Tempo, compares the ledger gauge with Prometheus,
and observes both firing and resolved error/latency notifications. It fetches the provisioned
dashboard from Grafana and, when the configured Chromium/Playwright runtime is available,
captures the actual dashboard screenshot. All children are stopped after the run.

The browser capture declares the valid `en-US` locale explicitly. In this executor, Chromium's
inherited `en-US@posix` locale caused Grafana's `Intl` initialization to fail before rendering
the login form. The saved first browser failure and a separate successful login probe document
that correction; changing a login selector alone would not have addressed the cause.

The native ledger uses clearly labeled fixture provider tokens and illustrative prices.
Matching that ledger to Prometheus establishes accounting-to-dashboard consistency, not actual
provider invoice reconciliation. The models remain fixtures even though the monitoring stack
and traffic are real. Look at `artifacts/p05-native-first-pass/report.json`, `traffic.jsonl`,
`distributed-trace.json`, `alerts.jsonl`, `ledger-query.json`, and `grafana-dashboard.png`.

### Accepted native result

The preserved successful run began at `2026-09-29T10:36:28.671400+00:00` and completed in
155.37 seconds. Its enclosing evidence command exited 0 and `report.json` records `verified_scope`.

| Check | Observed result |
|---|---|
| Slow protected response | 0.414 seconds |
| Error and latency alert lifecycle | Both firing and resolved notifications received |
| Durable handoff | Separate worker succeeded; producer and `job.execute` spans retrieved from Tempo |
| Ledger and Prometheus | 40 micro-USD reported in each, using the declared simulated price basis |
| Grafana | 12 panels provisioned through its API; actual dashboard screenshot captured |
| Peak combined process-tree RSS | 1,448,546,304 bytes, below the declared 1,610,612,736-byte cap |
| Cleanup | All supervised monitoring processes stopped after the run |

The screenshot shows the first eight panels, including the cost comparison. Grafana lazily
renders the four lower panels outside the initial viewport; their definitions were retrieved
through its API, but they are blank in this capture. Provider TTFT correctly shows no data for
the buffered fixture path. This capture does not establish visual verification of every panel.
The first successful run is also preserved under `artifacts/p05-native-first-pass`. The original
1 GiB cap failure and the invalid-locale browser failure remain under
`artifacts/p05-native-initial-1gib` and `artifacts/p05-native-initial-browser`. A later visual-only
repeat was interrupted at the source freeze; it is explicitly marked as unaccepted evidence.

For a container environment, configure a local Grafana password and run:

```bash
docker compose -f infra/monitoring/compose.yaml up -d
```

Run the existing API separately on port 8000 with fixture auth explicitly enabled and
`PAIS_OTLP_ENDPOINT=http://127.0.0.1:4318/v1/traces`. The Compose scrape credential is an obvious
fixture token; provision a separately authorized credential for any real environment. All
published ports bind loopback. Container configuration and native execution are distinct profiles.

## Alerts, sampling and retention

The local drill declares an error ratio above 5% with at least ten observations and a 250 ms
protected-delivery p95 threshold, each sustained for ten seconds. These low demo thresholds are
versioned in `rules.yaml`; P11 release thresholds are independently defined. Additional rules
cover committed budget above 80%, unknown-cost holds, missing telemetry, and traffic above twice
a thirty-minute baseline after at least twenty-five minutes of samples. The anomaly rule cannot
claim a useful baseline during a fresh short run.

The demo uses 100% parent-based trace sampling, 24-hour trace retention and 48-hour metric
retention. Production must deliberately choose sampling and retention for its workload.
Sampling changes what is visible; histogram metrics are independent of trace sampling.

## Acceptance checklist

- [x] Real SDK span propagation, attribute protection and exception-content suppression.
- [x] Actual API error and protected delivery measurements; metric cardinality checks.
- [x] Runnable native stack and provisioned container assets.
- [x] Native functional drill: both alert lifecycles, separate worker trace, ledger consistency,
  provisioned Grafana dashboard and actual screenshot; viewport limitation disclosed above.
- [ ] Container deployment execution, production workload sizing and a mature anomaly baseline.
- [ ] Actual paid-provider invoice-to-dashboard reconciliation.

See [case study](case-study.md) and [interview](interview.md).
Official references: [OpenTelemetry instrumentation](https://opentelemetry.io/docs/languages/python/instrumentation/),
[propagation](https://opentelemetry.io/docs/languages/python/propagation/),
[Alertmanager configuration](https://prometheus.io/docs/alerting/latest/configuration/),
[Grafana provisioning](https://grafana.com/docs/grafana/latest/administration/provisioning/),
[Tempo configuration](https://grafana.com/docs/tempo/latest/configuration/), consulted 2026-09-29.
