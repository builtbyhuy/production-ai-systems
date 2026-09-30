"""FastAPI application and the server-side trust boundary for the copilot.

Run: PAIS_ALLOW_FIXTURE_AUTH=1 uv run uvicorn services.api.app:app --host 127.0.0.1.
Fixture credentials are explicitly enabled and never interpreted as production credentials.
"""
import asyncio
import io
import json
import os
import re
import threading
import time
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from typing import Annotated, Any, Literal
from uuid import uuid4

from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pais.contracts import Action, Answer, Principal, StrictModel
from pydantic import Field
from pypdf import PdfReader

from .body_limit import RequestBodyLimitMiddleware
from .message_store import Claim, MessageConflict, MessageStore
from .streaming import DONE, answer_metadata, event

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_ANSWER_CHARS = 32_768


class ChatRequest(StrictModel):
    question: str = Field(min_length=1, max_length=8_000)
    message_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1, max_length=128)
    conversation_id: str = Field(default="workspace", min_length=1, max_length=128)


class ApprovalRequest(StrictModel):
    action: Action
    reviewer: str = Field(min_length=1, max_length=200)
    ttl_seconds: int = Field(default=900, ge=30, le=86400)


class ApprovalDecision(StrictModel):
    decision: Literal["approve", "reject", "cancel"]
    expected_action_hash: str = Field(min_length=1, max_length=128)
    context_version: str = Field(min_length=1, max_length=200)


class CapabilityUpdate(StrictModel):
    enabled: bool
    expected_version: int = Field(ge=0)
    reason: str = Field(default="", max_length=500)


def create_app(
    db_path: str | Path | None = None,
    profile: str | None = None,
    rag: Any = None,
    allow_fixture_auth: bool | None = None,
    auth_tokens: dict[str, Principal | dict] | None = None,
) -> FastAPI:
    path = str(db_path or os.getenv("PAIS_DB_PATH", "var/pais.db"))
    active_profile = profile or os.getenv("PAIS_PROFILE", "fixture")
    if active_profile not in {"fixture", "local", "connected", "deployment"}:
        raise ValueError("Unknown PAIS_PROFILE")
    fixture_auth = (os.getenv("PAIS_ALLOW_FIXTURE_AUTH") == "1"
                    if allow_fixture_auth is None else allow_fixture_auth)
    test_faults = active_profile == "fixture" and os.getenv("PAIS_ENABLE_TEST_FAULTS") == "1"
    timeout_seconds = float(os.getenv("PAIS_REQUEST_TIMEOUT_SECONDS", "60"))
    if not 0.05 <= timeout_seconds <= 600:
        raise ValueError("PAIS_REQUEST_TIMEOUT_SECONDS must be between 0.05 and 600")
    delivery_delay = (min(0.25, max(0.0, float(os.getenv("PAIS_FIXTURE_STREAM_DELAY_MS", "0")) / 1000))
                      if test_faults else 0)
    lock = threading.Lock()
    state: dict[str, Any] = {}

    def resources() -> dict[str, Any]:
        with lock:
            if state:
                return state
            from pais.observability import Telemetry, set_telemetry
            from pais.security import CredentialStore, SecurityPolicy, SharedLimiter

            creds = CredentialStore(path, allow_fixture=fixture_auth)
            trusted_tokens = auth_tokens
            if trusted_tokens is None and os.getenv("PAIS_AUTH_TOKENS"):
                try:
                    trusted_tokens = json.loads(os.environ["PAIS_AUTH_TOKENS"])
                except (ValueError, TypeError) as exc:
                    raise RuntimeError("PAIS_AUTH_TOKENS is not valid JSON; authentication is disabled") from exc
                if not isinstance(trusted_tokens, dict):
                    raise RuntimeError("PAIS_AUTH_TOKENS must map tokens to trusted principal records")
            if trusted_tokens:
                creds.load_tokens(trusted_tokens)
            # Missing mandatory production validators deny protected work, while health remains inspectable.
            policy = None
            policy_error = None
            try:
                policy = SecurityPolicy(require_guardrails=active_profile != "fixture")
            except (ImportError, RuntimeError, ValueError) as exc:
                policy_error = type(exc).__name__
            state.update({
                "credentials": creds, "policy": policy, "policy_error": policy_error,
                "limiter": SharedLimiter(path, lease_seconds=max(120, timeout_seconds + 60)),
                "telemetry": Telemetry(service_name="pais-api", exporter_endpoint=os.getenv("PAIS_OTLP_ENDPOINT")),
                "messages": MessageStore(path), "rag": rag,
            })
            set_telemetry(state["telemetry"])
            return state

    def rag_service():
        env = resources()
        with lock:
            if env["rag"] is None:
                from pais.rag import RAGService
                env["rag"] = RAGService(path, profile=active_profile,
                                        backend=os.getenv("PAIS_VECTOR_BACKEND", "sqlite"))
            return env["rag"]

    def policy():
        value = resources()["policy"]
        if value is None:
            raise HTTPException(503, "The required output validator is unavailable. Protected work is disabled.")
        return value

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        resources()
        yield

    application = FastAPI(title="Operations Copilot", version="0.1.0", lifespan=lifespan)
    application.state.resources = resources
    application.state.db_path = path
    application.state.profile = active_profile
    application.state.background_tasks = set()

    def track_job(job):
        application.state.background_tasks.add(job)
        def completed(done):
            application.state.background_tasks.discard(done)
            if not done.cancelled():
                done.exception()
        job.add_done_callback(completed)
        return job

    @application.middleware("http")
    async def response_headers(request: Request, call_next):
        request_id = request.headers.get("x-request-id", "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", request_id):
            request_id = str(uuid4())
        request.state.request_id = request_id
        if (request.headers.get("content-length", "").isdigit()
                and int(request.headers["content-length"]) > MAX_UPLOAD_BYTES + 65_536):
            return JSONResponse({"detail": "The request exceeds the 10 MiB upload limit."}, 413)
        start = time.perf_counter()
        with resources()["telemetry"].span("api.request", {"request.id": request_id},
                                           carrier={"traceparent": request.headers.get("traceparent", "")}):
            response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        if response.headers.get("x-vercel-ai-ui-message-stream") != "v1":
            response.headers["Cache-Control"] = "no-store"
        # This is time to response headers. Stream delivery is separately measured below.
        route = getattr(request.scope.get("route"), "path", "unmatched")
        if response.headers.get("x-vercel-ai-ui-message-stream") != "v1":
            resources()["telemetry"].record_request(route, response.status_code, time.perf_counter() - start)
        return response

    @application.exception_handler(PermissionError)
    async def denied(request, exc):
        return JSONResponse({"detail": "This identity is not permitted to perform this operation."}, 403)

    @application.exception_handler(KeyError)
    @application.exception_handler(FileNotFoundError)
    async def missing(request, exc):
        return JSONResponse({"detail": "The requested resource was not found."}, 404)

    @application.exception_handler(ValueError)
    async def invalid(request, exc):
        # Do not reflect parser traces, source text, model output, or credentials.
        code = 409 if isinstance(exc, MessageConflict) else getattr(exc, "status_code", 400)
        message = str(exc) if isinstance(exc, MessageConflict) else "The request could not be validated."
        return JSONResponse({"detail": message}, code)

    @application.exception_handler(RuntimeError)
    @application.exception_handler(Exception)
    async def unavailable(request, exc):
        code = getattr(exc, "status_code", 503)
        code = code if isinstance(code, int) and 400 <= code < 600 else 503
        headers = {}
        if hasattr(exc, "retry_after"):
            headers["Retry-After"] = str(max(1, int(exc.retry_after)))
        return JSONResponse({"detail": "The operation could not finish. Retry or inspect the local service health.",
                             "request_id": getattr(request.state, "request_id", None)}, code, headers=headers)

    def identity(authorization: Annotated[str | None, Header()] = None) -> Principal:
        try:
            return resources()["credentials"].resolve_bearer(authorization or "")
        except (PermissionError, ValueError):
            raise HTTPException(401, "A valid workspace credential is required.",
                                headers={"WWW-Authenticate": "Bearer"}) from None

    Trusted = Annotated[Principal, Depends(identity)]

    @application.get("/api/health")
    def health():
        env = resources()
        return {"status": "ok" if env["policy"] is not None else "degraded",
                "profile": active_profile, "fixture_auth": fixture_auth,
                "test_faults": test_faults, "buffered_output": True,
                "required_validator_ready": env["policy"] is not None,
                "evidence": "deterministic fixture; not model-quality evidence" if active_profile == "fixture"
                else "runtime profile; readiness must be verified separately"}

    @application.get("/api/me")
    def me(principal: Trusted):
        return principal

    @application.get("/api/ready")
    def ready():
        policy()
        try:
            rag_service()
        except (ImportError, RuntimeError, ValueError):
            raise HTTPException(503, "A required runtime prerequisite is unavailable.") from None
        return {"status": "ready", "profile": active_profile}

    @application.get("/api/metrics")
    def metrics(principal: Trusted):
        principal.require("admin")
        return Response(resources()["telemetry"].prometheus(), media_type="text/plain; version=0.0.4")

    @application.get("/api/documents")
    def documents(principal: Trusted):
        principal.require("reader")
        return {"documents": rag_service().list_documents(principal)}

    @application.post("/api/documents", status_code=201)
    async def upload(principal: Trusted, file: Annotated[UploadFile, File()]):
        principal.require("writer")
        policy()
        content = await file.read(MAX_UPLOAD_BYTES + 1)
        await file.close()
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, "PDFs must be no larger than 10 MiB.")
        if not content.startswith(b"%PDF-"):
            raise HTTPException(415, "Choose a valid PDF document.")
        # Basename strips paths; the service still validates and versions the document.
        name = Path((file.filename or "document.pdf").replace("\\", "/")).name[:200]
        lease = resources()["limiter"].acquire(principal, str(uuid4()))
        try:
            return await asyncio.to_thread(rag_service().ingest, principal, content, name)
        finally:
            resources()["limiter"].release(lease)

    @application.get("/api/documents/{document_id}/versions/{version_id}/pdf")
    def pdf(document_id: str, version_id: str, principal: Trusted):
        principal.require("reader")
        payload = rag_service().get_pdf(principal, document_id, version_id)
        return Response(payload, media_type="application/pdf",
                        headers={"Content-Disposition": 'inline; filename="source.pdf"'})

    @application.get("/api/documents/{document_id}/versions/{version_id}/pages/{page_number}")
    def source_page(document_id: str, version_id: str, page_number: int, principal: Trusted):
        principal.require("reader")
        payload = rag_service().get_pdf(principal, document_id, version_id)
        reader = PdfReader(io.BytesIO(payload))
        if not 1 <= page_number <= len(reader.pages):
            raise HTTPException(404, "That page does not exist in this document version.")
        return {"document_id": document_id, "version_id": version_id, "page_number": page_number,
                "page_count": len(reader.pages), "text": reader.pages[page_number - 1].extract_text() or ""}

    @application.delete("/api/documents/{document_id}", status_code=204)
    def delete_document(document_id: str, principal: Trusted):
        principal.require("writer")
        rag_service().delete(principal, document_id)
        return Response(status_code=204)

    def validate_saved(principal: Principal, answer: Answer) -> None:
        for citation in answer.citations:
            result = rag_service().validate_citation(principal, citation)
            if not all(result.get(key) is True for key in ("exists", "span", "support")):
                raise HTTPException(409, "A cited source changed or became unavailable. Start a new question.")

    def protect_answer(answer: Answer) -> Answer:
        if (len(answer.text) > MAX_ANSWER_CHARS or len(answer.citations) > 16
                or len(answer.model_dump_json()) > 131_072):
            raise ValueError("The protected answer exceeds the bounded buffer")
        return answer.model_copy(update={
            "text": policy().filter_output(answer.text),
            "citations": [c.model_copy(update={"quote": policy().filter_output(c.quote),
                                                "claim": policy().filter_output(c.claim)})
                          for c in answer.citations],
            "conflicts": [policy().filter_output(c) for c in answer.conflicts],
            # Internal retrieval/model evidence may contain source text. Public clients use
            # citations and trace IDs; detailed evidence belongs in the controlled evaluator.
            "evidence": {"output_buffered": True, "citation_validation_applied": True,
                         "provider_ttft_ms": None},
        })

    def prepare(principal: Principal, body: ChatRequest):
        principal.require("reader")
        question = policy().validate_input(body.question.strip()).text
        env = resources()
        lease = env["limiter"].acquire(principal, str(uuid4()))
        try:
            claim = env["messages"].claim(principal, body.message_id, body.conversation_id, question)
            return claim, question, lease
        except BaseException:
            env["limiter"].release(lease)
            raise

    def protect_replay(principal: Principal, claim: Claim, lease) -> Claim:
        # Required validators can launch bounded subprocesses. Keep them off the ASGI
        # event loop, and retain admission until the worker finishes even if delivery stops.
        try:
            validate_saved(principal, claim.answer)
            return replace(claim, answer=protect_answer(claim.answer))
        finally:
            resources()["limiter"].release(lease)

    async def prepare_chat(principal: Principal, body: ChatRequest):
        claim, question, lease = prepare(principal, body)
        if claim.answer is None:
            return claim, question, lease
        job = track_job(asyncio.create_task(asyncio.to_thread(protect_replay, principal, claim, lease)))
        protected_claim = await asyncio.shield(job)
        return protected_claim, question, None

    def generate(principal: Principal, body: ChatRequest, claim: Claim, question: str, lease,
                 force_failure: bool = False) -> Answer:
        env = resources()
        heartbeat_stop = threading.Event()
        heartbeat_failures = []
        def heartbeat():
            while not heartbeat_stop.wait(20):
                try:
                    env["limiter"].renew(lease)
                except (RuntimeError, ValueError) as failure:
                    heartbeat_failures.append(type(failure).__name__)
                    return
        heartbeat_thread = threading.Thread(target=heartbeat, daemon=True, name="pais-admission-renewal")
        heartbeat_thread.start()
        try:
            with env["telemetry"].span("api.chat", {"request.id": claim.request_id,
                                                         "profile": active_profile}):
                if force_failure and claim.attempt == 1:
                    raise RuntimeError("Explicit fixture failure injection")
                answer = rag_service().answer(principal, question, request_id=claim.request_id)
                answer = Answer.model_validate(answer)
                if heartbeat_failures:
                    raise RuntimeError("Admission lease renewal failed; result delivery denied")
                validate_saved(principal, answer)
                answer = answer.model_copy(update={"message_id": claim.answer_id})
                protected = protect_answer(answer)
                # Keep exact internal provenance for future validation; only protected copies
                # leave this trust boundary, including every subsequent history/replay response.
                env["messages"].complete(principal, body.message_id, answer)
                return protected
        except BaseException:
            env["messages"].failed(principal, body.message_id, "generation_failed")
            raise
        finally:
            heartbeat_stop.set()
            heartbeat_thread.join(timeout=1)
            env["limiter"].release(lease)

    @application.post("/api/chat")
    async def chat(body: ChatRequest, principal: Trusted):
        claim, question, lease = await prepare_chat(principal, body)
        if claim.answer:
            return claim.answer
        # shield preserves the single durable generation claim if the waiting HTTP request times out.
        job = track_job(asyncio.create_task(asyncio.to_thread(generate, principal, body, claim, question, lease)))
        try:
            return await asyncio.wait_for(asyncio.shield(job), timeout_seconds)
        except TimeoutError:
            raise HTTPException(504, "The answer is taking longer than expected. Retry later with the same message ID.") from None

    @application.post("/api/chat/stream")
    async def chat_stream(body: ChatRequest, principal: Trusted, request: Request):
        claim, question, lease = await prepare_chat(principal, body)
        force_failure = test_faults and request.headers.get("x-pais-test-fault") == "fail-once"

        async def stream():
            started = time.perf_counter()
            job = None
            finished = False
            stream_status = 499
            first_display = None
            try:
                yield event("start", messageId=claim.answer_id,
                            messageMetadata={"profile": active_profile, "buffered": True})
                yield event("data-status", data={"state": "validating", "buffered": True}, transient=True)
                if claim.answer is not None:
                    answer = claim.answer
                else:
                    job = track_job(asyncio.create_task(asyncio.to_thread(generate, principal, body, claim,
                                                                         question, lease, force_failure)))
                    answer = await asyncio.wait_for(asyncio.shield(job), timeout_seconds)
                if await request.is_disconnected():
                    return
                text_id = claim.answer_id + ":text"
                yield event("text-start", id=text_id)
                first_display = time.perf_counter() - started
                for offset in range(0, len(answer.text), 64):
                    if await request.is_disconnected():
                        return
                    yield event("text-delta", id=text_id, delta=answer.text[offset:offset + 64])
                    if delivery_delay:
                        await asyncio.sleep(delivery_delay)
                yield event("text-end", id=text_id)
                yield event("data-citations", id=claim.answer_id + ":citations",
                            data=[citation.model_dump() for citation in answer.citations])
                yield event("finish", finishReason="stop", messageMetadata={
                    **answer_metadata(answer, replayed=claim.answer is not None),
                    "firstDisplayMs": round(first_display * 1000, 3),
                    "providerTTFTMs": None,
                })
                yield DONE
                finished = True
                stream_status = 200
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 -- SSE failures must terminate with a protocol error.
                stream_status = 504 if isinstance(exc, TimeoutError) else 503
                detail = ("The provider timed out. Retry later with the same message."
                          if isinstance(exc, TimeoutError) else "The answer could not finish. You can retry this message.")
                yield event("error", errorText=detail)
                yield DONE
            finally:
                resources()["telemetry"].record_request("/api/chat/stream", stream_status,
                    time.perf_counter() - started, first_display_seconds=first_display)
                if not finished:
                    resources()["messages"].delivery_stopped(principal, body.message_id)
                # The sync RAG interface cannot interrupt its provider. Keep its task alive to
                # record the result and release the shared limiter; retry then replays that result.
                if job is not None:
                    def consume_failure(done):
                        if not done.cancelled():
                            done.exception()
                    job.add_done_callback(consume_failure)
                elif lease is not None:
                    # Cancelled before starting the generation task: no work ran.
                    resources()["messages"].failed(principal, body.message_id, "cancelled_before_generation")
                    resources()["limiter"].release(lease)

        return StreamingResponse(stream(), media_type="text/event-stream", headers={
            "x-vercel-ai-ui-message-stream": "v1", "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no", "Connection": "keep-alive",
        })

    @application.get("/api/messages")
    def messages(principal: Trusted, conversation_id: str = Query(default="workspace", max_length=128)):
        principal.require("reader")
        result = []
        pending = []
        for item in resources()["messages"].list(principal, conversation_id):
            result.append({"id": item["message_id"], "role": "user",
                           "parts": [{"type": "text", "text": item["question"]}]})
            if item["status"] == "completed":
                answer = Answer.model_validate_json(item["answer_json"])
                try:
                    validate_saved(principal, answer)
                except HTTPException:
                    # Never replay historical document-derived text after a citation loses access.
                    result.append({"id": answer.message_id, "role": "assistant", "parts": [{"type": "text",
                        "text": "This answer is unavailable because its source changed or was removed."}]})
                    continue
                answer = protect_answer(answer)
                result.append({"id": answer.message_id, "role": "assistant",
                               "metadata": answer_metadata(answer, replayed=True),
                               "parts": [{"type": "text", "text": answer.text},
                                         {"type": "data-citations", "data": [c.model_dump() for c in answer.citations]}]})
            else:
                pending.append({"message_id": item["message_id"], "status": item["status"],
                                "delivery": item["delivery"]})
        return {"messages": result, "pending": pending}

    def approvals_service():
        from pais.workflows import ApprovalService
        def current_context(principal: Principal, action: Action) -> str:
            context_id = action.arguments.get("context_id")
            if context_id == "workspace":
                return "workspace-v1"
            if not isinstance(context_id, str):
                raise ValueError("An explicit source context is required")  # noqa: TRY004 -- wire validation is a 400.
            current = next((doc for doc in rag_service().list_documents(principal)
                            if doc.document_id == context_id), None)
            if current is None:
                raise FileNotFoundError("Approval source is no longer available")
            return current.version_id
        return ApprovalService(path, context_resolver=current_context)

    @application.get("/api/approvals")
    def approvals(principal: Trusted):
        return {"approvals": approvals_service().list(principal), "external_delivery": False}

    @application.post("/api/approvals", status_code=201)
    def request_approval(body: ApprovalRequest, principal: Trusted):
        policy()
        return approvals_service().request(principal, body.action, body.reviewer, body.ttl_seconds)

    @application.post("/api/approvals/{approval_id}/decision")
    def decide(approval_id: str, body: ApprovalDecision, principal: Trusted):
        if body.decision == "approve":
            policy()
        return approvals_service().decide(principal, approval_id, body.decision,
                                         body.expected_action_hash, body.context_version)

    @application.get("/api/capabilities")
    def capabilities(principal: Trusted):
        principal.require("admin")
        from pais.operations import CapabilityFlags
        return {"capabilities": CapabilityFlags(path).list(principal)}

    @application.put("/api/capabilities/{capability}")
    def set_capability(capability: str, body: CapabilityUpdate, principal: Trusted):
        principal.require("admin")
        from pais.operations import CapabilityFlags
        return CapabilityFlags(path).set(principal, capability, body.enabled,
                                         body.expected_version, body.reason)

    application.add_middleware(RequestBodyLimitMiddleware)
    return application


app = create_app()
