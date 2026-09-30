"""Actual FastAPI + RAG + SQLite contracts; no real-model quality claim."""
from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from pais.contracts import Answer, Principal, Profile
from pais.rag import RAGService, create_demo_pdf

from services.api.app import create_app
from services.api.message_store import MessageInProgress, MessageStore

ADMIN = {"Authorization": "Bearer fixture-admin"}
READER = {"Authorization": "Bearer fixture-reader"}
OTHER = {"Authorization": "Bearer fixture-other"}
QUESTION = "What is the safe operating pressure?"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PAIS_ENABLE_TEST_FAULTS", "1")
    monkeypatch.delenv("PAIS_AUTH_TOKENS", raising=False)
    application = create_app(tmp_path / "state.db", allow_fixture_auth=True)
    with TestClient(application) as connection:
        yield connection


@pytest.fixture
def document(client):
    payload = create_demo_pdf([
        "Operations handbook. This document covers a pump station.",
        ("Pressure procedure. The maximum safe operating pressure is 8 bar. "
         "The maintenance interval is 30 days. Escalate critical incidents within 15 minutes."),
    ])
    response = client.post("/api/documents", headers=ADMIN,
                           files={"file": ("operating-manual.pdf", payload, "application/pdf")})
    assert response.status_code == 201, response.text
    return response.json(), payload


def parse_stream(response):
    assert response.headers["x-vercel-ai-ui-message-stream"] == "v1"
    lines = [line.removeprefix("data: ") for line in response.text.splitlines() if line.startswith("data: ")]
    assert lines[-1] == "[DONE]"
    return [json.loads(line) for line in lines[:-1]]


def test_fixture_auth_requires_explicit_server_opt_in(tmp_path):
    with TestClient(create_app(tmp_path / "disabled.db", allow_fixture_auth=False)) as client:
        assert client.get("/api/health").json()["fixture_auth"] is False
        assert client.get("/api/documents").status_code == 401
        assert client.get("/api/documents", headers=ADMIN).status_code == 401


def test_trusted_token_mapping_and_client_tenant_header_have_no_authority(tmp_path):
    token = "server-configured-test-token-" + "a" * 32
    principal = Principal(subject="alice", tenant_id="alpha", roles=["reader"])
    with TestClient(create_app(tmp_path / "tokens.db", auth_tokens={token: principal})) as client:
        response = client.get("/api/me", headers={"Authorization": "Bearer " + token, "X-Tenant-ID": "victim"})
        assert response.status_code == 200
        assert response.json()["tenant_id"] == "alpha"
        assert response.json()["subject"] == "alice"


def test_role_and_document_authorization(client, document):
    version, payload = document
    assert client.get("/api/documents", headers=OTHER).json()["documents"] == []
    base = f"/api/documents/{version['document_id']}/versions/{version['version_id']}"
    assert client.get(base + "/pdf", headers=OTHER).status_code in {403, 404}
    assert client.get(base + "/pages/2", headers=OTHER).status_code in {403, 404}
    assert client.post("/api/documents", headers=READER,
                       files={"file": ("forbidden.pdf", payload, "application/pdf")}).status_code == 403
    assert client.delete(f"/api/documents/{version['document_id']}", headers=READER).status_code == 403
    assert client.get(base + "/pdf", headers=READER).content == payload


def test_nonadmin_writer_can_upload_read_and_delete_document(tmp_path):
    token = "writer-contract-token-" + "w" * 32
    principal = Principal(subject="operator", tenant_id="operations", roles=["reader", "writer"])
    headers = {"Authorization": "Bearer " + token}
    payload = create_demo_pdf(["The maximum safe operating pressure is 8 bar."])
    with TestClient(create_app(tmp_path / "writer.db", auth_tokens={token: principal})) as client:
        uploaded = client.post("/api/documents", headers=headers,
                               files={"file": ("manual.pdf", payload, "application/pdf")})
        assert uploaded.status_code == 201, uploaded.text
        version = uploaded.json()
        base = f"/api/documents/{version['document_id']}/versions/{version['version_id']}"
        assert client.get(base + "/pdf", headers=headers).content == payload
        assert client.delete(f"/api/documents/{version['document_id']}", headers=headers).status_code == 204
        assert client.get(base + "/pdf", headers=headers).status_code == 404


def test_upload_stream_page_navigation_and_stable_replay(client, document):
    version, _payload = document
    body = {"question": QUESTION, "message_id": "stable-message"}
    response = client.post("/api/chat/stream", headers=ADMIN, json=body)
    assert response.status_code == 200
    events = parse_stream(response)
    kinds = [item["type"] for item in events]
    assert kinds[0] == "start"
    assert kinds[-1] == "finish"
    assert kinds.index("text-start") < kinds.index("text-delta") < kinds.index("text-end")
    text = "".join(item["delta"] for item in events if item["type"] == "text-delta")
    assert "8 bar" in text
    metadata = events[-1]["messageMetadata"]
    assert metadata["buffered"] is True and metadata["profile"] == "fixture"
    assert metadata["providerTTFTMs"] is None
    assert metadata["firstDisplayMs"] >= 0
    citations = next(item["data"] for item in events if item["type"] == "data-citations")
    assert citations and citations[0]["page_number"] == 2
    source = citations[0]
    path = f"/api/documents/{source['document_id']}/versions/{source['version_id']}/pages/2"
    page = client.get(path, headers=ADMIN)
    assert page.status_code == 200 and "8 bar" in page.json()["text"]
    assert page.json()["version_id"] == version["version_id"]
    repeated = parse_stream(client.post("/api/chat/stream", headers=ADMIN, json=body))
    assert repeated[0]["messageId"] == events[0]["messageId"]
    assert repeated[-1]["messageMetadata"]["replayed"] is True
    history = client.get("/api/messages", headers=ADMIN).json()["messages"]
    assert len(history) == 2 and len({message["id"] for message in history}) == 2


def test_reusing_an_id_for_another_question_is_rejected(client, document):
    first = {"question": QUESTION, "message_id": "bound-message"}
    assert client.post("/api/chat", headers=ADMIN, json=first).status_code == 200
    response = client.post("/api/chat", headers=ADMIN,
                           json={**first, "question": "What is the maintenance interval?"})
    assert response.status_code == 409
    assert len(client.get("/api/messages", headers=ADMIN).json()["messages"]) == 2


def test_client_identity_fields_are_rejected_and_history_is_private(client, document):
    response = client.post("/api/chat", headers=ADMIN,
                           json={"question": QUESTION, "tenant_id": "victim"})
    assert response.status_code == 422
    assert client.post("/api/chat", headers=ADMIN, json={"question": QUESTION}).status_code == 200
    assert client.get("/api/messages", headers=READER).json()["messages"] == []
    assert client.get("/api/messages", headers=OTHER).json()["messages"] == []


def test_stream_failure_retry_has_one_message_pair(client, document):
    body = {"question": QUESTION, "message_id": "retry-one"}
    headers = {**ADMIN, "X-PAIS-Test-Fault": "fail-once"}
    failed = parse_stream(client.post("/api/chat/stream", headers=headers, json=body))
    assert any(item["type"] == "error" for item in failed)
    assert not any(item["type"] == "text-delta" for item in failed)
    recovered = parse_stream(client.post("/api/chat/stream", headers=headers, json=body))
    assert recovered[0]["messageId"] == failed[0]["messageId"]
    assert recovered[-1]["type"] == "finish"
    history = client.get("/api/messages", headers=ADMIN).json()
    assert len(history["messages"]) == 2
    assert history["pending"] == []


def test_fixture_fault_header_is_ignored_without_opt_in(tmp_path, monkeypatch):
    monkeypatch.delenv("PAIS_ENABLE_TEST_FAULTS", raising=False)
    with TestClient(create_app(tmp_path / "no-faults.db", allow_fixture_auth=True)) as client:
        stream = parse_stream(client.post("/api/chat/stream", headers={**ADMIN, "X-PAIS-Test-Fault": "fail-once"},
                                          json={"question": QUESTION}))
        assert stream[-1]["type"] == "finish"
        assert stream[-1]["messageMetadata"]["abstained"] is True


def test_abstention_for_empty_workspace(client):
    answer = client.post("/api/chat", headers=ADMIN,
                         json={"question": "What is the orbital velocity of the moon?"}).json()
    assert answer["abstained"] is True
    assert answer["citations"] == []


def test_deleted_source_blocks_replay_and_removes_history_answer(client, document):
    version, _ = document
    body = {"question": QUESTION, "message_id": "source-deletion"}
    first = client.post("/api/chat", headers=ADMIN, json=body)
    assert "8 bar" in first.json()["text"]
    assert client.delete(f"/api/documents/{version['document_id']}", headers=ADMIN).status_code == 204
    assert client.post("/api/chat", headers=ADMIN, json=body).status_code == 409
    history = client.get("/api/messages", headers=ADMIN).text
    assert "8 bar" not in history
    assert "source changed or was removed" in history


@pytest.mark.parametrize("content,name,expected", [
    (b"not a PDF", "manual.pdf", 415),
    (b"%PDF-1.7\ninvalid", "manual.pdf", 400),
    (b"%PDF-1.7\n" + b"x" * (10 * 1024 * 1024), "oversized.pdf", 413),
])
def test_invalid_uploads_have_actionable_status(client, content, name, expected):
    response = client.post("/api/documents", headers=ADMIN,
                           files={"file": (name, content, "application/pdf")})
    assert response.status_code == expected


def test_request_timeout_keeps_generation_claim_and_replays_finished_result(tmp_path, monkeypatch):
    monkeypatch.setenv("PAIS_REQUEST_TIMEOUT_SECONDS", "0.05")
    rag = RAGService(tmp_path / "timeout.db", profile="fixture")
    original = rag.answer
    calls = []
    def delayed(*args, **kwargs):
        calls.append(1)
        time.sleep(0.18)
        return original(*args, **kwargs)
    monkeypatch.setattr(rag, "answer", delayed)
    body = {"question": QUESTION, "message_id": "slow-request"}
    with TestClient(create_app(tmp_path / "timeout.db", rag=rag, allow_fixture_auth=True)) as client:
        assert client.post("/api/chat", headers=ADMIN, json=body).status_code == 504
        assert client.post("/api/chat", headers=ADMIN, json=body).status_code == 409
        time.sleep(0.2)
        assert client.post("/api/chat", headers=ADMIN, json=body).status_code == 200
        assert len(calls) == 1


def test_atomic_claim_prevents_concurrent_duplicate_generation(tmp_path):
    store = MessageStore(str(tmp_path / "claims.db"))
    principal = Principal(subject="alice", tenant_id="alpha")
    def submit(_):
        try:
            return store.claim(principal, "one", "conversation", QUESTION)
        except MessageInProgress:
            return None
    with ThreadPoolExecutor(max_workers=8) as pool:
        claims = list(pool.map(submit, range(8)))
    assert sum(claim is not None for claim in claims) == 1
    claim = next(claim for claim in claims if claim)
    answer = Answer(request_id=claim.request_id, message_id=claim.answer_id,
                    text="No evidence.", abstained=True, model="fixture", profile=Profile.FIXTURE)
    store.complete(principal, "one", answer)
    assert store.claim(principal, "one", "conversation", QUESTION).answer == answer


def test_approval_executes_local_effect_once_with_exact_binding(client):
    flags = client.get("/api/capabilities", headers=ADMIN).json()["capabilities"]
    state = next(item for item in flags if item["capability"] == "agent.execute")
    enabled = client.put("/api/capabilities/agent.execute", headers=ADMIN,
                         json={"enabled": True, "expected_version": state["version"], "reason": "API contract test"})
    assert enabled.status_code == 200
    body = {"reviewer": "fixture-admin", "action": {"tool": "record_note", "arguments": {
        "text": "Inspect the pressure valve.", "context_id": "workspace"},
        "context_version": "workspace-v1", "idempotency_key": "api-note-one"}}
    request = client.post("/api/approvals", headers=ADMIN, json=body)
    assert request.status_code == 201, request.text
    approval = request.json()
    url = f"/api/approvals/{approval['approval_id']}/decision"
    decision = {"decision": "approve", "expected_action_hash": approval["action_hash"], "context_version": "workspace-v1"}
    invalid = client.post(url, headers=ADMIN, json={**decision, "expected_action_hash": "tampered"})
    assert invalid.status_code in {400, 409}
    assert client.post(url, headers=READER, json=decision).status_code == 403
    approved = client.post(url, headers=ADMIN, json=decision)
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "executed"
    repeated = client.post(url, headers=ADMIN, json=decision)
    assert repeated.status_code == 200 and repeated.json()["status"] == "executed"
    assert client.get("/api/approvals", headers=OTHER).json()["approvals"] == []


def test_capability_updates_reject_stale_versions(client):
    first = client.put("/api/capabilities/agent.execute", headers=ADMIN,
                       json={"enabled": True, "expected_version": 0})
    assert first.status_code == 200
    stale = client.put("/api/capabilities/agent.execute", headers=ADMIN,
                       json={"enabled": False, "expected_version": 0})
    assert stale.status_code in {400, 409}
    assert client.put("/api/capabilities/agent.execute", headers=ADMIN, json={"enabled": False}).status_code == 422


def test_production_validator_absence_is_fail_closed(tmp_path, monkeypatch):
    from pais import security
    def unavailable(*args, **kwargs):
        raise security.ValidatorUnavailable("Required validator is missing")
    monkeypatch.setattr(security, "SecurityPolicy", unavailable)
    with TestClient(create_app(tmp_path / "closed.db", profile="local", allow_fixture_auth=True)) as client:
        assert client.get("/api/health").json()["required_validator_ready"] is False
        assert client.get("/api/ready").status_code == 503
        assert client.post("/api/chat", headers=ADMIN, json={"question": QUESTION}).status_code == 503


def test_chunked_upload_cannot_bypass_body_limit(client):
    boundary = "pais-upload-boundary"
    parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="large.pdf"\r\n'
             'Content-Type: application/pdf\r\n\r\n'.encode()]
    # Build a generator so httpx emits Transfer-Encoding: chunked, without a Content-Length.
    def content():
        yield parts[0]
        yield b"%PDF-1.7\n"
        for _ in range(11):
            yield b"x" * (1024 * 1024)
        yield f"\r\n--{boundary}--\r\n".encode()
    response = client.post("/api/documents", headers={**ADMIN,
        "Content-Type": f"multipart/form-data; boundary={boundary}"}, content=content())
    assert response.status_code == 413


def test_oversized_model_output_is_blocked_before_any_text_delta(tmp_path, monkeypatch):
    rag = RAGService(tmp_path / "bounded.db", profile="fixture")
    def oversized(principal, question, request_id=None):
        return Answer(request_id=request_id, text="x" * 32_769, model="oversized-fixture",
                      profile=Profile.FIXTURE)
    monkeypatch.setattr(rag, "answer", oversized)
    with TestClient(create_app(tmp_path / "bounded.db", rag=rag, allow_fixture_auth=True)) as client:
        events = parse_stream(client.post("/api/chat/stream", headers=ADMIN, json={"question": QUESTION}))
        assert any(event["type"] == "error" for event in events)
        assert not any(event["type"] == "text-delta" for event in events)
