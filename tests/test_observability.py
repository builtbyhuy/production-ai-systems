import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pais.observability import Telemetry


def test_real_otel_queue_propagation_and_redaction():
    exporter = InMemorySpanExporter()
    api = Telemetry(exporter=exporter)
    worker = Telemetry(service_name="pais-worker", exporter=exporter)
    with api.span("api.request", {"request.id": "r-1", "prompt": "private", "token": "sk-xxx"}):
        carrier = api.inject()
    with worker.span("job.execute", {"job.id": "j-1"}, carrier=carrier):
        pass
    spans = exporter.get_finished_spans()
    assert len(spans) == 2
    assert spans[1].context.trace_id == spans[0].context.trace_id
    assert spans[1].parent.span_id == spans[0].context.span_id
    assert "prompt" not in spans[0].attributes and "token" not in spans[0].attributes
    assert set(carrier) == {"traceparent"}


def test_exception_content_not_exported():
    exporter = InMemorySpanExporter()
    telemetry = Telemetry(exporter=exporter)
    with pytest.raises(ValueError), telemetry.span("model.call"):
        raise ValueError("person@example.com Bearer secret-credential")
    span = exporter.get_finished_spans()[0]
    assert span.attributes["error.type"] == "ValueError"
    assert not span.events
    assert span.status.description is None


def test_metric_cardinality_unknown_cost_and_seconds_units():
    telemetry = Telemetry(release="r1")
    for i in range(20):
        telemetry.record_request(f"/api/documents/user-{i}", 200, 0.1)
    telemetry.record_model("unregistered-model-id", "timeout", 2)
    telemetry.update_ledger({"cap": 1000, "reserved": 200, "reconciled": 300,
                             "unknown_hold": 100, "estimated": 250})
    text = telemetry.prometheus().decode()
    assert 'route="other"' in text and "user-1" not in text
    assert 'model="other"' in text
    assert 'pais_usage_unknown_total{model="other",release="r1"} 1.0' in text
    assert 'pais_budget_utilization_ratio{release="r1"} 0.5' in text
    assert 'pais_ledger_cost_microusd{kind="reconciled",release="r1"} 300.0' in text
    assert "pais_model_tokens_total{" not in text  # unknown never turns into 0 known tokens
    with pytest.raises(ValueError):
        telemetry.record_request("/api/chat", 200, float("nan"))
