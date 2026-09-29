"""Explicit local fixture application for the real observability stack drill.

It uses real API, durable ledger, routing, and job code. Generated answers and prices
remain fixture/simulation evidence. The extra endpoint is never mounted by the main app.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path

import uvicorn
from fastapi import Header
from pais.contracts import ModelRequest, ModelResponse, TraceContext, new_id
from pais.jobs import JobService, sign_webhook
from pais.observability import Telemetry
from pais.reliability import BudgetLedger, ModelRouter, ModelSpec, Price, ProviderResult
from pais.security import CredentialStore

from services.api.app import create_app


class FixtureProvider:
    async def generate(self, spec, request):
        return ProviderResult(ModelResponse(text="Explicit monitoring ledger fixture",
                                            model=spec.model, input_tokens=20,
                                            output_tokens=10, finish_reason="stop"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--port", type=int, default=18180)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--worker-job")
    args = parser.parse_args()
    if args.worker_job:
        telemetry = Telemetry(service_name="pais-durable-worker")
        service = JobService(args.db, allow_stored_principal=True, telemetry=telemetry)
        result = service.worker_execute(args.worker_job)
        (args.output/"worker-result.json").write_text(result.model_dump_json(indent=2))
        telemetry.close()
        return
    os.environ["PAIS_ENABLE_TEST_FAULTS"] = "1"
    os.environ["PAIS_FIXTURE_STREAM_DELAY_MS"] = "200"
    app = create_app(db_path=args.db, profile="fixture", allow_fixture_auth=True)
    resources = app.state.resources()
    telemetry = resources["telemetry"]
    p = CredentialStore.FIXTURES["fixture-admin"].model_copy(deep=True)
    ledger = BudgetLedger(args.db)
    ledger.configure_budget(p, 1000)
    router = ModelRouter(ledger, [ModelSpec("cheap", "fixture-ledger",
                          Price(1000, 2000, "native-drill-simulation-v1"))], FixtureProvider())
    asyncio.run(router.complete(ModelRequest(principal=p,
                messages=[{"role": "user", "content": "local monitoring ledger fixture"}],
                max_output_tokens=10, budget_microusd=1000)))
    snapshot = ledger.snapshot(p)
    telemetry.update_ledger(snapshot)
    (args.output/"ledger.json").write_text(json.dumps(snapshot | {"price_basis": "simulation"}, indent=2))
    service = JobService(args.db, allow_stored_principal=True, telemetry=telemetry)
    service.capability_flags.set(p, "agent.execute", True, reason="Explicit local observability fixture")

    @app.post("/api/observability/drill-job")
    def enqueue(authorization: str = Header()):
        identity = resources["credentials"].resolve_bearer(authorization)
        identity.require("admin")
        with telemetry.span("api.request", {"http.route": "/api/observability/drill-job"}):  # noqa: SIM117 -- explicit producer parent/child trace.
            with telemetry.span("job.publish"):
                carrier = telemetry.inject()
                body = json.dumps({"event_id": new_id(), "tool": "record_note",
                                   "arguments": {"text": "explicit local monitoring drill"},
                                   "context_version": "monitoring-v1"}).encode()
                signature_secret = "local-monitoring-fixture-secret"
                job = service.accept_webhook(identity, body, sign_webhook(body, signature_secret),
                                             signature_secret, TraceContext(traceparent=carrier["traceparent"]))
                # SQLite outbox publication is a durable handoff to the separately launched worker.
                service.dispatch(lambda job_id, trace: (args.output/"job-envelope.json").write_text(
                    json.dumps({"job_id": job_id, "traceparent": trace.get("traceparent")})))
        telemetry.record_queue(1)
        return {"job_id": job.job_id, "trace_id": carrier["traceparent"].split("-")[1]}

    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
