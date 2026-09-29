"""Content-free application telemetry with bounded metrics and W3C queue propagation."""
from __future__ import annotations

import math
import os
import re
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any

from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor
from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased
from opentelemetry.trace import Status, StatusCode
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest

BUCKETS_SECONDS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 20, 30, 60, 120)
_ROUTES = {"/api/health", "/api/documents", "/api/documents/{id}",
           "/api/documents/{id}/versions/{version}/pdf", "/api/chat", "/api/chat/stream",
           "/api/approvals", "/api/approvals/{id}/decision", "/api/metrics", "/metrics",
           "/api/cancel/{id}", "/api/jobs", "/api/webhooks", "other"}
_STAGES = {"retrieval", "reranking", "routing", "generation", "approval", "job", "other"}
_SPAN_NAMES = {"api.request", "api.chat", "api.stream", "document.ingest", "rag.answer",
               "rag.retrieve", "rag.rerank", "retrieval", "reranking", "router.route",
               "model.call", "approval.transition", "job.publish", "job.execute", "job.retry",
               "memory.retrieve", "security.validate", "sandbox.execute", "other"}
_ATTRIBUTES = {"request.id", "parent.request.id", "job.id", "approval.id", "http.route",
               "http.response.status_code", "model.name", "model.profile", "model.attempt",
               "routing.reason", "usage.input_tokens", "usage.output_tokens", "usage.known",
               "cost.estimated_microusd", "cost.reconciled_microusd", "cache.hit", "quality.passed",
               "retrieval.mode", "retrieval.hits", "reranking.enabled", "error.type",
               "approval.status", "job.attempt", "document.pages", "security.validator"}


def _seconds(value: float) -> float:
    value = float(value)
    if not math.isfinite(value) or value < 0:
        raise ValueError("Telemetry durations must be finite, nonnegative seconds")
    return value


def safe_attributes(attributes: Mapping[str, Any] | None) -> dict[str, Any]:
    """Allowlist before export. No prompts, documents, tokens, URLs, bodies or exceptions."""
    result = {}
    for key, value in (attributes or {}).items():
        if key not in _ATTRIBUTES or value is None:
            continue
        if isinstance(value, str):
            # IDs/codes only. Free-form strings, emails, query params, and bearer keys disappear.
            if not re.fullmatch(r"[A-Za-z0-9_./{}: -]{1,120}", value):
                continue
            if any(word in value.lower() for word in ("bearer ", "password", "secret", "sk-")):
                continue
            result[key] = value
        elif isinstance(value, bool | int) or isinstance(value, float) and math.isfinite(value):
            result[key] = value
    return result


class ProtectedSpan:
    def __init__(self, span):
        self._span = span

    def set_attribute(self, key: str, value: Any) -> None:
        self._span.set_attributes(safe_attributes({key: value}))

    def set_attributes(self, attributes: Mapping[str, Any]) -> None:
        self._span.set_attributes(safe_attributes(attributes))

    def get_span_context(self):
        return self._span.get_span_context()


class Telemetry:
    """One instance per app worker; aggregate scrapes per replica in Prometheus.

    In-memory metrics reset on restart. Durable ledger gauges are refreshed from SQLite.
    Traces use parent-based sampling; approved local demos use 100%, production defaults
    should be chosen explicitly and retained with the deployment's evidence configuration.
    """

    def __init__(self, service_name: str = "pais-api", exporter_endpoint: str | None = None,
                 sample_rate: float = 1.0, release: str | None = None, exporter=None,
                 models: set[str] | None = None):
        release = release or os.environ.get("PAIS_RELEASE", "development")
        if not 0 <= sample_rate <= 1:
            raise ValueError("sample_rate must be between zero and one")
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,80}", release):
            raise ValueError("release is a bounded operator configured version")
        exporter_endpoint = exporter_endpoint or os.environ.get("PAIS_OTLP_ENDPOINT")
        self.release = release
        self.models = models or {"fixture", "local", "cheap", "expensive"}
        self.registry = CollectorRegistry()
        common = {"registry": self.registry}
        self.requests = Counter("pais_requests_total", "Completed API requests",
                                ["route", "status_class", "release"], **common)
        self.request_duration = Histogram("pais_request_duration_seconds", "End to end API seconds",
                                          ["route", "release"], buckets=BUCKETS_SECONDS, **common)
        self.first_display = Histogram("pais_first_display_seconds", "Protected first text display delay",
                                       ["route", "release"], buckets=BUCKETS_SECONDS, **common)
        self.ttft = Histogram("pais_provider_ttft_seconds", "Provider time to first token, when measured",
                              ["model", "release"], buckets=BUCKETS_SECONDS, **common)
        self.attempts = Counter("pais_provider_attempts_total", "Every explicit provider attempt",
                               ["model", "outcome", "release"], **common)
        self.model_duration = Histogram("pais_provider_duration_seconds", "Provider attempt seconds",
                                        ["model", "release"], buckets=BUCKETS_SECONDS, **common)
        self.tokens = Counter("pais_model_tokens_total", "Reported provider tokens only",
                              ["model", "direction", "release"], **common)
        self.unknown_usage = Counter("pais_usage_unknown_total", "Attempts with unknown usage",
                                     ["model", "release"], **common)
        self.cache = Counter("pais_cache_hits_total", "Authorized response cache uses", ["release"], **common)
        self.retries = Counter("pais_retries_total", "Explicit retries or fallbacks",
                               ["kind", "release"], **common)
        self.queue = Gauge("pais_queue_depth", "Durable queue depth", ["queue", "release"], **common)
        self.quality = Counter("pais_quality_observations_total", "Measured quality observations",
                               ["kind", "outcome", "release"], **common)
        self.stage_duration = Histogram("pais_stage_duration_seconds", "Internal stage seconds",
                                        ["stage", "release"], buckets=BUCKETS_SECONDS, **common)
        self.ledger = Gauge("pais_ledger_cost_microusd", "Authoritative ledger aggregate in micro USD",
                            ["kind", "release"], **common)
        self.admission = Counter("pais_admission_rejections_total", "Admission rejections",
                                 ["kind", "release"], **common)
        self.budget_ratio = Gauge("pais_budget_utilization_ratio", "Aggregate committed budget / cap",
                                  ["release"], **common)
        self.provider = TracerProvider(
            resource=Resource.create({"service.name": service_name, "service.version": release}),
            sampler=ParentBased(TraceIdRatioBased(sample_rate)))
        if exporter is not None:
            self.provider.add_span_processor(SimpleSpanProcessor(exporter))
        elif exporter_endpoint:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
            self.provider.add_span_processor(BatchSpanProcessor(
                OTLPSpanExporter(endpoint=exporter_endpoint, timeout=5)))
        self.tracer = self.provider.get_tracer("pais", "0.1.0")
        self.propagator = TraceContextTextMapPropagator()

    @contextmanager
    def span(self, name: str, attributes: Mapping[str, Any] | None = None,
             carrier: Mapping[str, str] | None = None) -> Iterator[ProtectedSpan]:
        context = self.extract(carrier) if carrier else None
        with self.tracer.start_as_current_span(
            name if name in _SPAN_NAMES else "other", context=context,
            attributes=safe_attributes(attributes), record_exception=False,
            set_status_on_exception=False,
        ) as span:
            try:
                yield ProtectedSpan(span)
            except BaseException as exc:
                # Exception text/stack may hold credentials. Only the type is exported.
                span.set_attribute("error.type", type(exc).__name__[:80])
                span.set_status(Status(StatusCode.ERROR))
                raise

    @contextmanager
    def stage(self, name: str):
        start = time.perf_counter()
        try:
            yield
        finally:
            stage = name if name in _STAGES else "other"
            self.stage_duration.labels(stage, self.release).observe(time.perf_counter()-start)

    def inject(self) -> dict[str, str]:
        carrier: dict[str, str] = {}
        self.propagator.inject(carrier)
        # Baggage/tracestate are omitted to avoid arbitrary content crossing the boundary.
        return {key: value for key, value in carrier.items() if key == "traceparent"}

    def extract(self, carrier: Mapping[str, str]):
        value = carrier.get("traceparent", "")
        if not re.fullmatch(r"[0-9a-f]{2}-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}", value):
            return self.propagator.extract({})
        return self.propagator.extract({"traceparent": value})

    def record_request(self, route: str, status: int, seconds: float,
                       first_display_seconds: float | None = None) -> None:
        route = route if route in _ROUTES else "other"
        status_class = f"{status//100}xx" if 100 <= status < 600 else "other"
        self.requests.labels(route, status_class, self.release).inc()
        self.request_duration.labels(route, self.release).observe(_seconds(seconds))
        if first_display_seconds is not None:
            self.first_display.labels(route, self.release).observe(_seconds(first_display_seconds))

    def record_model(self, model: str, outcome: str, seconds: float,
                     input_tokens: int | None = None, output_tokens: int | None = None,
                     ttft_seconds: float | None = None) -> None:
        model = model if model in self.models else "other"
        if outcome not in {"success", "error", "timeout", "cancelled"}:
            outcome = "error"
        self.attempts.labels(model, outcome, self.release).inc()
        self.model_duration.labels(model, self.release).observe(_seconds(seconds))
        for direction, amount in (("input", input_tokens), ("output", output_tokens)):
            if amount is not None:
                if not isinstance(amount, int) or amount < 0:
                    raise ValueError("Reported token usage must be nonnegative integers")
                self.tokens.labels(model, direction, self.release).inc(amount)
        if input_tokens is None or output_tokens is None:
            self.unknown_usage.labels(model, self.release).inc()
        if ttft_seconds is not None:
            self.ttft.labels(model, self.release).observe(_seconds(ttft_seconds))

    def record_quality(self, kind: str, passed: bool) -> None:
        if kind not in {"grounding", "citation", "authorization", "schema"}:
            raise ValueError("Unknown quality signal")
        self.quality.labels(kind, "pass" if passed else "fail", self.release).inc()

    def record_queue(self, depth: int, queue: str = "default") -> None:
        if depth < 0:
            raise ValueError("Queue depth cannot be negative")
        self.queue.labels(queue if queue in {"default", "dead", "approvals"} else "other",
                          self.release).set(depth)

    def record_retry(self, kind: str = "provider") -> None:
        self.retries.labels(kind if kind in {"provider", "job"} else "other", self.release).inc()

    def record_cache(self) -> None:
        self.cache.labels(self.release).inc()

    def record_admission(self, kind: str) -> None:
        self.admission.labels(kind if kind in {"rate", "concurrency", "budget"} else "other",
                              self.release).inc()

    def update_ledger(self, totals: Mapping[str, int]) -> None:
        for kind in ("reserved", "estimated", "reported", "reconciled", "unknown_hold"):
            self.ledger.labels(kind, self.release).set(int(totals.get(kind, 0)))
        cap = totals.get("cap", 0)
        committed = totals.get("committed", totals.get("reconciled", 0)
                               + totals.get("reported", 0) + totals.get("reserved", 0))
        self.budget_ratio.labels(self.release).set(committed/cap if cap else 0)

    def prometheus(self) -> bytes:
        return generate_latest(self.registry)

    def close(self) -> None:
        self.provider.force_flush(timeout_millis=5000)
        self.provider.shutdown()


_default: Telemetry | None = None


def get_telemetry() -> Telemetry:
    global _default
    if _default is None:
        _default = Telemetry()
    return _default


def set_telemetry(telemetry: Telemetry) -> None:
    global _default
    _default = telemetry


def demo(profile: str = "fixture", db_path: str | None = None,
         output_dir: str | None = None) -> dict:
    """Actual API traffic + real SDK metrics/spans; backend deployment remains separate."""
    if profile != "fixture":
        raise RuntimeError("Run projects/05-observability/native_drill.py against the declared local stack; a fixture cannot satisfy the deployment gate")
    from pathlib import Path
    from tempfile import TemporaryDirectory

    from fastapi.testclient import TestClient
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    from services.api.app import create_app

    exporter = InMemorySpanExporter()
    telemetry = Telemetry(service_name="pais-observability-demo", exporter=exporter,
                          release="fixture-observability")
    old_fault = os.environ.get("PAIS_ENABLE_TEST_FAULTS")
    old_delay = os.environ.get("PAIS_FIXTURE_STREAM_DELAY_MS")
    os.environ["PAIS_ENABLE_TEST_FAULTS"] = "1"
    os.environ["PAIS_FIXTURE_STREAM_DELAY_MS"] = "200"
    request_results = []
    start = time.perf_counter()
    try:
        with TemporaryDirectory(prefix="pais-observe-") as temp:
            app = create_app(db_path=db_path or str(Path(temp)/"demo.sqlite"), profile="fixture",
                             allow_fixture_auth=True)
            app.state.resources()["telemetry"] = telemetry
            set_telemetry(telemetry)
            with TestClient(app) as client:
                headers = {"Authorization": "Bearer fixture-admin"}
                for i, fault in enumerate((False, True, False)):
                    before = time.perf_counter()
                    response = client.post("/api/chat/stream", headers=headers | (
                        {"x-pais-test-fault": "fail-once"} if fault else {}),
                        json={"message_id": f"observability-{i}", "question": "What is the retry timeout?"})
                    request_results.append({"case": "error" if fault else "protected-buffered-response",
                                            "http_status": response.status_code,
                                            "stream_error": '"type":"error"' in response.text,
                                            "seconds": time.perf_counter()-before})
                metric_response = client.get("/api/metrics", headers=headers)
                metric_text = metric_response.text
            with telemetry.span("job.publish", {"job.id": "telemetry-component-probe"}):
                carrier = telemetry.inject()
            with telemetry.span("job.execute", {"job.id": "telemetry-component-probe"}, carrier=carrier):
                pass
            spans = exporter.get_finished_spans()
            if output_dir:
                directory = Path(output_dir)
                directory.mkdir(parents=True, exist_ok=True)
                (directory/"metrics.prom").write_text(metric_text)
                (directory/"traces.json").write_text(__import__("json").dumps([
                    {"name": s.name, "trace_id": f"{s.context.trace_id:032x}",
                     "span_id": f"{s.context.span_id:016x}",
                     "parent_span_id": f"{s.parent.span_id:016x}" if s.parent else None,
                     "attributes": dict(s.attributes), "status": s.status.status_code.name}
                    for s in spans], indent=2))
    finally:
        for name, old in (("PAIS_ENABLE_TEST_FAULTS", old_fault), ("PAIS_FIXTURE_STREAM_DELAY_MS", old_delay)):
            if old is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = old
    return {"project": "P05", "profile": profile, "status": "partial",
            "evidence_scope": "actual FastAPI traffic with fixture generation; real OTel+Prometheus clients",
            "requests": request_results, "exported_spans": len(spans),
            "metric_bytes": len(metric_text.encode()),
            "recorded_stream_errors": 'status_class="5xx"' in metric_text,
            "queue_context_component_verified": spans[-1].context.trace_id == spans[-2].context.trace_id,
            "duration_seconds": time.perf_counter()-start,
            "deployment": {"grafana": "not_run", "tempo_trace_inspection": "not_run",
                           "alert_firing_and_resolved": "not_run", "ledger_dashboard_reconciliation": "not_run"}}
