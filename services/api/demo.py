"""API vertical-slice demonstration. Browser acceptance is a separate mandatory gate."""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import shlex
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient
from pais.rag import create_demo_pdf

from .app import create_app


def demo(profile: str = "fixture", output_dir: str | Path | None = None) -> dict:
    start = time.perf_counter()
    root = Path(__file__).resolve().parents[2]
    document = create_demo_pdf([
        "Pump station operations. This handbook defines operating rules.",
        "The maximum safe operating pressure is 8 bar. The maintenance interval is 30 days.",
    ])
    headers = {"Authorization": "Bearer fixture-admin"}
    checks = {}
    with tempfile.TemporaryDirectory(prefix="pais-api-demo-") as directory:
        app = create_app(Path(directory) / "state.db", profile=profile, allow_fixture_auth=True)
        with TestClient(app) as client:
            readiness = client.get("/api/ready")
            if readiness.status_code != 200:
                raise RuntimeError(f"P08 {profile} prerequisite unavailable: {readiness.json()['detail']}")
            bad = client.post("/api/documents", headers=headers,
                              files={"file": ("invalid.pdf", b"not a pdf", "application/pdf")})
            checks["invalid_upload_rejected"] = bad.status_code == 415
            upload = client.post("/api/documents", headers=headers,
                                 files={"file": ("operations-manual.pdf", document, "application/pdf")})
            checks["real_pdf_upload"] = upload.status_code == 201
            if upload.status_code != 201:
                raise RuntimeError("P08 PDF ingestion failed")
            version = upload.json()
            request = {"question": "What is the maximum safe operating pressure?", "message_id": "demo-stable-message"}
            response = client.post("/api/chat/stream", headers=headers, json=request)
            lines = [line[6:] for line in response.text.splitlines() if line.startswith("data: ")]
            events = [json.loads(line) for line in lines if line != "[DONE]"]
            checks["sdk_protocol"] = (response.headers.get("x-vercel-ai-ui-message-stream") == "v1"
                                      and lines[-1] == "[DONE]" and events[-1]["type"] == "finish")
            answer_text = "".join(item["delta"] for item in events if item["type"] == "text-delta")
            checks["supported_answer"] = "8 bar" in answer_text
            sources = next((item["data"] for item in events if item["type"] == "data-citations"), [])
            checks["page_citations"] = bool(sources) and sources[0]["page_number"] == 2
            source_path = f"/api/documents/{version['document_id']}/versions/{version['version_id']}"
            page = client.get(source_path + "/pages/2", headers=headers)
            checks["working_page_source"] = page.status_code == 200 and "8 bar" in page.json()["text"]
            checks["original_pdf_bytes"] = client.get(source_path + "/pdf", headers=headers).content == document
            other = {"Authorization": "Bearer fixture-other", "X-Tenant-ID": "fixture-tenant"}
            checks["cross_tenant_source_denied"] = client.get(source_path + "/pdf", headers=other).status_code in {403, 404}
            replay = client.post("/api/chat", headers=headers, json=request)
            checks["stable_retry"] = replay.status_code == 200 and replay.json()["message_id"] == events[0]["messageId"]
            checks["no_duplicate_history"] = len(client.get("/api/messages", headers=headers).json()["messages"]) == 2
            abstention = client.post("/api/chat", headers=headers,
                                      json={"question": "Who won the intergalactic chess championship in 2840?"})
            checks["abstention"] = abstention.status_code == 200 and abstention.json()["abstained"]
            flags = client.get("/api/capabilities", headers=headers).json()["capabilities"]
            control = next(item for item in flags if item["capability"] == "agent.execute")
            enabled = client.put("/api/capabilities/agent.execute", headers=headers,
                                 json={"enabled": True, "expected_version": control["version"],
                                       "reason": "Explicit isolated demonstration setup"})
            checks["explicit_execution_enable"] = enabled.status_code == 200
            proposal = client.post("/api/approvals", headers=headers, json={
                "reviewer": "fixture-admin", "action": {
                    "tool": "record_note", "arguments": {"text": "Review the 8 bar limit.",
                                                             "context_id": version["document_id"]},
                    "context_version": version["version_id"], "idempotency_key": "demo-note-one"}})
            checks["approval_created"] = proposal.status_code == 201
            if proposal.status_code == 201:
                approval = proposal.json()
                decision = {"decision": "approve", "expected_action_hash": approval["action_hash"],
                            "context_version": approval["action"]["context_version"]}
                url = f"/api/approvals/{approval['approval_id']}/decision"
                approved = client.post(url, headers=headers, json=decision)
                repeated = client.post(url, headers=headers, json=decision)
                checks["approved_local_action"] = approved.status_code == 200 and approved.json()["status"] == "executed"
                checks["approval_replay_idempotent"] = repeated.status_code == 200 and repeated.json()["status"] == "executed"
            else:
                checks["approved_local_action"] = False
                checks["approval_replay_idempotent"] = False
            metadata = events[-1].get("messageMetadata", {})
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=False)
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=root, capture_output=True, text=True, check=False)
    result = {
        "project": "P08", "profile": profile, "timestamp": datetime.now(UTC).isoformat(),
        "command": shlex.join(getattr(sys, "orig_argv", [sys.executable, *sys.argv])),
        "commit": commit.stdout.strip() if commit.returncode == 0 else None,
        "dirty_tree": bool(dirty.stdout.strip()) if dirty.returncode == 0 else None,
        "versions": {name: importlib.metadata.version(name) for name in ("fastapi", "pydantic", "httpx", "pypdf")},
        "dataset_sha256": hashlib.sha256(document).hexdigest(),
        "checks": checks, "passed": all(checks.values()), "exit_status": 0 if all(checks.values()) else 1,
        "elapsed_ms": round((time.perf_counter() - start) * 1000, 3),
        "first_display_server_ms": metadata.get("firstDisplayMs"), "provider_ttft_ms": None,
        "model": metadata.get("model"), "answer": answer_text,
        "streaming": "full protected answer buffered, then bounded SSE delivery chunks",
        "browser_acceptance": "separate required gate; TestClient does not demonstrate browser behavior",
        "external_delivery": False,
        "evidence_scope": "fixture contracts only" if profile == "fixture" else "actual configured runtime dependencies",
    }
    if output_dir:
        output = Path(output_dir)
        output.mkdir(parents=True, exist_ok=True)
        (output / "api-demo.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


if __name__ == "__main__":
    report = demo(os.getenv("PAIS_PROFILE", "fixture"))
    print(json.dumps(report, indent=2))
    raise SystemExit(report["exit_status"])
