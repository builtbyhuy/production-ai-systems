import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pais.contracts import Principal
from pais.jobs import JobService, sign_webhook, webhook_router


def test_actual_fastapi_webhook_durable_acceptance_authentication_and_duplicate(tmp_path):
    principal = Principal(subject="owner", tenant_id="a", roles=["admin"])
    service = JobService(tmp_path / "jobs.db")
    service.capability_flags.set(principal, "agent.execute", True, reason="explicit HTTP fixture setup")

    def resolve(token):
        if token != "fixture-a":
            raise PermissionError("Invalid token")
        return principal

    app = FastAPI()
    app.include_router(webhook_router(service, resolve, lambda p: "secret"), prefix="/api")
    client = TestClient(app)
    body = json.dumps({"event_id": "http-1", "tool": "record_note",
                       "arguments": {"note": "HTTP accepted"}, "context_version": "v1"}).encode()
    headers = {"authorization": "Bearer fixture-a", "x-webhook-signature": sign_webhook(body, "secret")}
    first = client.post("/api/webhooks", content=body, headers=headers)
    assert first.status_code == 202 and first.json()["durably_accepted"]
    repeated = client.post("/api/webhooks", content=body, headers=headers)
    assert repeated.json()["job_id"] == first.json()["job_id"]
    assert JobService(tmp_path / "jobs.db").get(principal, first.json()["job_id"]).status == "pending"
    assert client.post("/api/webhooks", content=body).status_code == 401
    assert client.post("/api/webhooks", content=body, headers={**headers, "authorization": "Bearer wrong"}).status_code == 403
