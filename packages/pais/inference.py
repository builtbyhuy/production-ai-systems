"""Bounded admission and streaming gateway for explicitly provisioned vLLM servers.

The gateway is one process. Its concurrency limit is per process and its backend list is
operator configuration, never request data. HTTP contract tests do not establish vLLM
inference quality or accelerator performance.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import hmac
import importlib.metadata
import itertools
import json
import math
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections import Counter
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class VLLMProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    evidence_profile: Literal["functional", "deployment"]
    backend: Literal["cpu", "cuda"]
    vllm_version: str = "0.30.0"
    model: str
    model_directory: str | None = None
    model_revision: str | None = None
    image_digest: str | None = None
    dtype: Literal["float16", "bfloat16", "float32"] = "bfloat16"
    quantization: Literal["awq"] | None = None
    max_model_len: int = Field(default=1024, ge=128, le=32768)
    max_num_seqs: int = Field(default=2, ge=1, le=128)
    max_num_batched_tokens: int = Field(default=1024, ge=128, le=65536)
    prefix_caching: bool = True
    cpu_kv_cache_gib: int = Field(default=1, ge=1, le=16)
    gpu_memory_utilization: float = Field(default=0.8, gt=0.1, lt=0.95)
    minimum_host_ram_gib: int = Field(default=8, ge=4)
    minimum_gpu_ram_gib: int = Field(default=0, ge=0)
    gpu_compute_capability: float | None = None
    replicas: int = Field(default=1, ge=1, le=8)

    @model_validator(mode="after")
    def compatible(self):
        if self.backend == "cpu" and self.quantization is not None:
            raise ValueError("This CPU profile has no verified quantization backend")
        if self.backend == "cuda" and (
            self.gpu_compute_capability is None or self.gpu_compute_capability < 7.5
        ):
            raise ValueError("Current CUDA vLLM profile requires compute capability >=7.5")
        if self.backend == "cuda" and self.dtype == "bfloat16" and self.gpu_compute_capability < 8:
            raise ValueError("Use float16 for the T4 compute-capability 7.5 profile")
        if self.quantization == "awq" and self.dtype != "float16":
            raise ValueError("AWQ comparison profile explicitly uses float16 activations")
        if self.max_num_batched_tokens < self.max_model_len:
            raise ValueError("Declared batch token budget must fit the functional context")
        return self

    def prerequisites(self, *, deployment: bool = False) -> list[str]:
        missing = []
        if platform.system() != "Linux":
            missing.append("Linux runtime for these declared CPU/CUDA profiles")
        try:
            version = importlib.metadata.version("vllm")
            if version != self.vllm_version:
                missing.append(f"vllm=={self.vllm_version}; installed {version}")
        except importlib.metadata.PackageNotFoundError:
            missing.append(f"isolated vllm=={self.vllm_version} runtime")
        directory = Path(self.model_directory or "/__pais_unprovisioned__")
        if not directory.is_dir() or not (directory / "config.json").is_file():
            missing.append("provisioned local model directory containing config.json")
        if not self.model_revision or not re.fullmatch(r"[a-f0-9]{40,64}", self.model_revision):
            missing.append("immutable model revision or locally trained model SHA256")
        if self.backend == "cuda" and shutil.which("nvidia-smi") is None:
            missing.append(
                "NVIDIA device/driver access; declared GPU capacity must also be checked"
            )
        if deployment:
            if not self.image_digest or not re.fullmatch(r"sha256:[a-f0-9]{64}", self.image_digest):
                missing.append("verified vLLM image manifest digest")
            if shutil.which("kubectl") is None:
                missing.append("kubectl and an authorized test cluster with device plugin")
        return missing

    def serve_command(self) -> list[str]:
        if not self.model_directory:
            raise ValueError("Provision model_directory before generating a serve command")
        args = [
            "vllm",
            "serve",
            self.model_directory,
            "--served-model-name",
            self.model,
            "--host",
            "0.0.0.0",
            "--port",
            "8000",
            "--dtype",
            self.dtype,
            "--max-model-len",
            str(self.max_model_len),
            "--max-num-seqs",
            str(self.max_num_seqs),
            "--max-num-batched-tokens",
            str(self.max_num_batched_tokens),
            "--enable-prefix-caching" if self.prefix_caching else "--no-enable-prefix-caching",
        ]
        if self.backend == "cuda":
            args.extend(["--gpu-memory-utilization", str(self.gpu_memory_utilization)])
        if self.quantization:
            args.extend(["--quantization", self.quantization])
        return args


class GatewayConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str
    backends: list[str] = Field(min_length=1, max_length=8)
    max_inflight: int = Field(default=4, ge=1, le=128)
    max_queue: int = Field(default=8, ge=0, le=1024)
    queue_timeout_seconds: float = Field(default=2, gt=0, le=60)
    request_timeout_seconds: float = Field(default=120, gt=0, le=600)
    health_interval_seconds: float = Field(default=5, ge=1, le=60)
    max_context_tokens: int = Field(default=2048, ge=128, le=32768)
    max_output_tokens: int = Field(default=256, ge=1, le=8192)
    max_body_bytes: int = Field(default=65536, ge=1024, le=1048576)

    @field_validator("backends")
    @classmethod
    def configured_urls(cls, values: list[str]) -> list[str]:
        for value in values:
            url = urlsplit(value)
            if url.scheme not in {"http", "https"} or not url.hostname:
                raise ValueError("Backends require explicit http(s) endpoints")
            if (
                url.username
                or url.password
                or url.query
                or url.fragment
                or url.path not in {"", "/"}
            ):
                raise ValueError("Backend credentials, query, and path must not be in the URL")
        normalized = [value.rstrip("/") for value in values]
        if len(set(normalized)) != len(normalized):
            raise ValueError("Backend URLs must be distinct")
        return normalized


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1, max_length=32768)


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str
    messages: list[ChatMessage] = Field(min_length=1, max_length=32)
    max_tokens: int = Field(default=128, ge=1, le=8192)
    stream: Literal[True] = True
    temperature: float = Field(default=0, ge=0, le=2)
    stream_options: dict[str, bool] = Field(default_factory=lambda: {"include_usage": True})


class AdmissionRejected(RuntimeError):
    pass


@dataclass
class AdmissionLease:
    owner: AdmissionController
    wait_seconds: float
    released: bool = False

    def release(self) -> None:
        if not self.released:
            self.released = True
            self.owner.active -= 1
            self.owner.accepted_or_queued -= 1
            self.owner.semaphore.release()


class AdmissionController:
    def __init__(self, maximum: int, queue: int, timeout: float):
        if maximum < 1 or queue < 0 or timeout <= 0:
            raise ValueError("Invalid admission bounds")
        self.maximum, self.queue, self.timeout = maximum, queue, timeout
        self.semaphore = asyncio.Semaphore(maximum)
        self.active = 0
        self.accepted_or_queued = 0
        self.rejected = 0
        self.closed = False

    async def acquire(self) -> AdmissionLease:
        # No await between inspecting and reserving a ticket in this single event loop.
        if self.closed or self.accepted_or_queued >= self.maximum + self.queue:
            self.rejected += 1
            raise AdmissionRejected("server_draining" if self.closed else "queue_full")
        self.accepted_or_queued += 1
        started = time.perf_counter()
        try:
            await asyncio.wait_for(self.semaphore.acquire(), timeout=self.timeout)
        except BaseException as exc:
            self.accepted_or_queued -= 1
            if isinstance(exc, TimeoutError):
                self.rejected += 1
                raise AdmissionRejected("queue_timeout") from exc
            raise
        if self.closed:
            self.semaphore.release()
            self.accepted_or_queued -= 1
            self.rejected += 1
            raise AdmissionRejected("server_draining")
        self.active += 1
        return AdmissionLease(self, time.perf_counter() - started)


@dataclass
class Backend:
    identifier: str
    url: str
    ready: bool = False
    active: int = 0
    completed: int = 0
    failures: int = 0


def create_gateway_app(
    config: GatewayConfig | None = None,
    *,
    gateway_token: str | None = None,
    upstream_token: str | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    """Uvicorn factory; environment configuration is mandatory outside explicit tests."""
    if config is None:
        path = os.environ.get("PAIS_INFERENCE_GATEWAY_CONFIG")
        if not path:
            raise RuntimeError("Set PAIS_INFERENCE_GATEWAY_CONFIG to a reviewed JSON config")
        config = GatewayConfig.model_validate_json(Path(path).read_text())
    gateway_token = gateway_token or os.environ.get("PAIS_INFERENCE_GATEWAY_TOKEN")
    upstream_token = upstream_token or os.environ.get("VLLM_API_KEY")
    if not gateway_token or len(gateway_token) < 16 or not upstream_token:
        raise RuntimeError("Provision gateway and upstream authentication tokens")
    admission = AdmissionController(
        config.max_inflight, config.max_queue, config.queue_timeout_seconds
    )
    backends = [Backend(f"backend-{i}", url) for i, url in enumerate(config.backends)]
    counts: Counter[str] = Counter()

    async def refresh_backend(client: httpx.AsyncClient, backend: Backend) -> None:
        try:
            health = await client.get(backend.url + "/health", timeout=5)
            health.raise_for_status()
            if not backend.ready:
                warmup = await client.post(
                    backend.url + "/v1/chat/completions",
                    json={
                        "model": config.model,
                        "messages": [{"role": "user", "content": "Say ready."}],
                        "max_tokens": 2,
                        "temperature": 0,
                        "stream": False,
                    },
                )
                warmup.raise_for_status()
                choices = warmup.json().get("choices", [])
                if not choices or not choices[0].get("message", {}).get("content"):
                    raise ValueError("Warmup returned no generated content")
                backend.ready = True
        except (httpx.HTTPError, ValueError, KeyError):
            backend.ready = False
            counts["warmup_or_health_failure"] += 1

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        headers = {"Authorization": f"Bearer {upstream_token}"}
        async with httpx.AsyncClient(
            headers=headers,
            timeout=config.request_timeout_seconds,
            transport=transport,
            follow_redirects=False,
            trust_env=False,
        ) as client:
            app.state.client = client
            await asyncio.gather(*(refresh_backend(client, backend) for backend in backends))

            async def monitor():
                while True:
                    await asyncio.sleep(config.health_interval_seconds)
                    await asyncio.gather(
                        *(refresh_backend(client, backend) for backend in backends)
                    )

            task = asyncio.create_task(monitor())
            try:
                yield
            finally:
                admission.closed = True
                for backend in backends:
                    backend.ready = False
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

    app = FastAPI(title="PAIS bounded inference gateway", lifespan=lifespan)
    app.state.admission, app.state.backends, app.state.counts = admission, backends, counts

    def authorize(request: Request):
        supplied = request.headers.get("authorization", "")
        if not hmac.compare_digest(supplied.encode(), f"Bearer {gateway_token}".encode()):
            raise HTTPException(401, "Invalid inference gateway credential")

    @app.get("/health")
    async def health():
        return {"live": True}

    @app.get("/ready")
    async def ready():
        available = sum(backend.ready for backend in backends)
        return JSONResponse(
            {"ready_backends": available, "draining": admission.closed},
            status_code=200 if available and not admission.closed else 503,
        )

    @app.post("/drain")
    async def drain(request: Request):
        authorize(request)
        admission.closed = True
        return {"draining": True, "active": admission.active}

    @app.get("/metrics")
    async def metrics():
        lines = [
            f"pais_inference_active {admission.active}",
            f"pais_inference_queued {admission.accepted_or_queued - admission.active}",
            f"pais_inference_rejected_total {admission.rejected}",
        ]
        for backend in backends:
            label = f'{{backend="{backend.identifier}"}}'
            lines += [
                f"pais_inference_backend_ready{label} {int(backend.ready)}",
                f"pais_inference_backend_completed_total{label} {backend.completed}",
                f"pais_inference_backend_failures_total{label} {backend.failures}",
            ]
        return PlainTextResponse("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")

    @app.post("/v1/chat/completions")
    async def completions(request: Request):
        authorize(request)
        chunks, size = [], 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > config.max_body_bytes:
                raise HTTPException(413, "Request body exceeds admission limit")
            chunks.append(chunk)
        try:
            body = ChatRequest.model_validate_json(b"".join(chunks))
        except ValueError as exc:
            raise HTTPException(422, "Invalid bounded chat request") from exc
        if body.model != config.model or body.max_tokens > config.max_output_tokens:
            raise HTTPException(422, "Model or output limit is outside the configured profile")
        try:
            lease = await admission.acquire()
        except AdmissionRejected as exc:
            raise HTTPException(503, str(exc), headers={"Retry-After": "1"}) from exc
        backend: Backend | None = None
        response: httpx.Response | None = None
        try:
            candidates = [item for item in backends if item.ready]
            if not candidates:
                raise HTTPException(503, "No warmed healthy inference backend")
            backend = min(
                candidates, key=lambda item: (item.active, item.completed, item.identifier)
            )
            backend.active += 1
            payload = body.model_dump()
            # Actual tokenizer count includes the chat template; characters are not tokens.
            tokenized = await app.state.client.post(
                backend.url + "/tokenize",
                json={
                    "model": config.model,
                    "messages": payload["messages"],
                    "add_generation_prompt": True,
                },
            )
            tokenized.raise_for_status()
            count = tokenized.json().get("count")
            if type(count) is not int or count < 1:
                raise ValueError("Tokenizer did not provide a valid count")
            if count + body.max_tokens > config.max_context_tokens:
                raise HTTPException(422, "Input plus output tokens exceed the context budget")
            payload["stream_options"] = {"include_usage": True}
            upstream_request = app.state.client.build_request(
                "POST", backend.url + "/v1/chat/completions", json=payload
            )
            response = await app.state.client.send(upstream_request, stream=True)
            response.raise_for_status()
            if "text/event-stream" not in response.headers.get("content-type", ""):
                raise ValueError("Backend did not return an event stream")
        except BaseException as exc:
            if response is not None:
                await response.aclose()
            if backend is not None:
                backend.active -= 1
                if not isinstance(exc, HTTPException):
                    backend.ready = False
                    backend.failures += 1
            lease.release()
            if isinstance(exc, (httpx.HTTPError, ValueError)):
                raise HTTPException(502, "Inference backend failed before streaming") from exc
            raise

        async def stream():
            end_marker = False
            tail = b""
            try:
                async for chunk in response.aiter_bytes():
                    tail = (tail + chunk)[-4096:]
                    end_marker = end_marker or b"data: [DONE]\n" in tail.replace(b"\r\n", b"\n")
                    yield chunk
                if not end_marker:
                    raise httpx.ReadError("Backend stream ended without DONE marker")
                backend.completed += 1
            except asyncio.CancelledError:
                counts["client_cancelled"] += 1
                raise
            except httpx.HTTPError:
                backend.ready = False
                backend.failures += 1
                # Once headers were sent, a truncated stream is an error, never a fresh retry.
                yield b'event: error\ndata: {"error":"upstream_stream_failed"}\n\n'
            finally:
                try:
                    await response.aclose()
                finally:
                    backend.active -= 1
                    lease.release()

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={
                "X-Inference-Backend": backend.identifier,
                "X-Queue-Wait-Seconds": f"{lease.wait_seconds:.6f}",
                "Cache-Control": "no-store",
                "X-Accel-Buffering": "no",
            },
        )

    return app


def percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = (len(ordered) - 1) * quantile
    lower, upper = math.floor(index), math.ceil(index)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)


async def load_test(
    endpoint: str,
    model: str,
    token: str,
    prompts: list[str],
    *,
    concurrency: int,
    max_tokens: int,
    timeout: float = 120,
    cancel_every: int = 0,
) -> dict[str, Any]:
    """Record actual wire timing/usage; chunk gaps are not claimed as token intervals."""
    if not prompts or concurrency < 1 or concurrency > 128 or max_tokens < 1:
        raise ValueError("Invalid declared workload")
    semaphore = asyncio.Semaphore(concurrency)
    started = time.perf_counter()
    records: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:

        async def run(index: int, prompt: str):
            async with semaphore:
                begin = time.perf_counter()
                row: dict[str, Any] = {
                    "index": index,
                    "status": "error",
                    "input_chars": len(prompt),
                }
                arrival: list[float] = []
                usage: dict = {}
                done = False
                try:
                    async with client.stream(
                        "POST",
                        endpoint.rstrip("/") + "/v1/chat/completions",
                        headers={"Authorization": f"Bearer {token}"},
                        json={
                            "model": model,
                            "messages": [{"role": "user", "content": prompt}],
                            "max_tokens": max_tokens,
                            "temperature": 0,
                            "stream": True,
                            "stream_options": {"include_usage": True},
                        },
                    ) as response:
                        row["http_status"] = response.status_code
                        row["backend"] = response.headers.get("x-inference-backend")
                        row["gateway_queue_seconds"] = response.headers.get("x-queue-wait-seconds")
                        response.raise_for_status()
                        async for line in response.aiter_lines():
                            if not line.startswith("data:"):
                                continue
                            data = line[5:].strip()
                            if data == "[DONE]":
                                done = True
                                break
                            event = json.loads(data)
                            if event.get("error"):
                                raise ValueError("Upstream reported stream error")
                            if event.get("usage"):
                                usage = event["usage"]
                            content = [
                                choice.get("delta", {}).get("content")
                                for choice in event.get("choices", [])
                            ]
                            if any(content):
                                arrival.append(time.perf_counter())
                                if cancel_every and (index + 1) % cancel_every == 0:
                                    row["status"] = "cancelled"
                                    break
                        if row["status"] != "cancelled":
                            if not done or not arrival:
                                raise ValueError("Truncated or empty completion")
                            if (
                                type(usage.get("completion_tokens")) is not int
                                or usage["completion_tokens"] < 1
                                or type(usage.get("prompt_tokens")) is not int
                            ):
                                raise ValueError("Missing actual usage token counts")
                            row["status"] = "ok"
                except (httpx.HTTPError, ValueError) as exc:
                    row["error_type"] = type(exc).__name__
                row["latency_seconds"] = time.perf_counter() - begin
                row["ttft_seconds"] = arrival[0] - begin if arrival else None
                row["inter_chunk_seconds"] = [b - a for a, b in itertools.pairwise(arrival)]
                row["usage"] = usage
                records.append(row)

        await asyncio.gather(*(run(index, prompt) for index, prompt in enumerate(prompts)))
    elapsed = time.perf_counter() - started
    good = [row for row in records if row["status"] == "ok"]
    latency = [row["latency_seconds"] for row in good]
    ttft = [row["ttft_seconds"] for row in good if row["ttft_seconds"] is not None]
    output_tokens = sum(row["usage"]["completion_tokens"] for row in good)
    return {
        "evidence": "actual_http_endpoint",
        "inference_identity_verified": False,
        "workload": {
            "requests": len(prompts),
            "concurrency": concurrency,
            "max_output_tokens": max_tokens,
            "cancel_every": cancel_every,
            "prompts_sha256": hashlib.sha256(json.dumps(prompts).encode()).hexdigest(),
        },
        "elapsed_seconds": elapsed,
        "successful": len(good),
        "cancelled": sum(row["status"] == "cancelled" for row in records),
        "errors": sum(row["status"] == "error" for row in records),
        "latency_p50_seconds": percentile(latency, 0.5),
        "latency_p95_seconds": percentile(latency, 0.95),
        "latency_p99_seconds": percentile(latency, 0.99),
        "ttft_p50_seconds": percentile(ttft, 0.5),
        "ttft_p95_seconds": percentile(ttft, 0.95),
        "completion_tokens_per_second": output_tokens / elapsed,
        "intertoken_latency": "collect vllm:inter_token_latency_seconds from backend metrics",
        "records": sorted(records, key=lambda row: row["index"]),
    }


def demo(profile: str = "fixture", output_dir: str | Path | None = None) -> dict[str, Any]:
    """Exercise real admission state or explicitly launch the isolated CPU smoke supervisor."""
    if profile == "fixture":

        async def admission_checks() -> dict[str, bool]:
            controller = AdmissionController(maximum=1, queue=0, timeout=0.1)
            first = await controller.acquire()
            rejected = False
            try:
                await controller.acquire()
            except AdmissionRejected:
                rejected = True
            first.release()
            first.release()
            recovered = await controller.acquire()
            recovered.release()
            controller.closed = True
            drained = False
            try:
                await controller.acquire()
            except AdmissionRejected:
                drained = True
            return {
                "overflow_rejected": rejected,
                "capacity_recovered": controller.active == controller.accepted_or_queued == 0,
                "drain_rejected": drained,
                "rejections_recorded": controller.rejected == 2,
            }

        checks = asyncio.run(admission_checks())
        return {
            "status": "passed" if all(checks.values()) else "failed",
            "profile": "fixture",
            "evidence": "actual_admission_controller_without_model_or_network",
            "inference_identity_verified": False,
            "model_requests": 0,
            "checks": checks,
        }
    if profile != "local":
        return {
            "status": "blocked",
            "profile": profile,
            "missing": [
                "Provision and authorize the declared cluster/model/image for deployment evidence"
            ],
            "inference_identity_verified": False,
        }
    root = Path(__file__).resolve().parents[2]
    runtime = Path(os.environ.get("PAIS_VLLM_PYTHON", ""))
    if not os.environ.get("PAIS_VLLM_PYTHON"):
        candidates = [
            root / "projects/14-inference-server/.venv/bin/python",
            root.parent / "vllm-runtime/.venv/bin/python",
        ]
        runtime = next((path for path in candidates if path.is_file()), candidates[0])
    source_model = Path(
        os.environ.get("PAIS_P14_SOURCE_MODEL", str(root / "artifacts/p09-smoke/base-model"))
    )
    missing = []
    if not runtime.is_file():
        missing.append("Set PAIS_VLLM_PYTHON to an isolated vllm==0.30.0+cpu interpreter")
    if not (source_model / "manifest.json").is_file():
        missing.append(
            "Run the genuine P09 tiny local smoke to create its approved random base-model artifact"
        )
    if missing:
        return {
            "status": "blocked",
            "profile": "local",
            "missing": missing,
            "inference_identity_verified": False,
        }
    parent = Path(output_dir or root / "artifacts/p14-outputs").absolute()
    parent.mkdir(parents=True, exist_ok=True)
    # Reserve a unique run name, then let the supervisor exclusively create its evidence directory.
    reserved = Path(tempfile.mkdtemp(prefix="cpu-functional-", dir=parent))
    reserved.rmdir()
    command = [
        sys.executable,
        str(root / "projects/14-inference-server/run_cpu_smoke.py"),
        "--runtime-python",
        str(runtime.absolute()),
        "--source-model",
        str(source_model.absolute()),
        "--output",
        str(reserved),
    ]
    result = subprocess.run(
        command, cwd=root, capture_output=True, text=True, timeout=280, check=False
    )
    report_file = reserved / "report.json"
    if not report_file.is_file():
        return {
            "status": "failed",
            "profile": "local",
            "inference_identity_verified": False,
            "error": "CPU supervisor exited without a report",
            "exit_code": result.returncode,
            "supervisor_output": (result.stdout + result.stderr)[-4000:],
        }
    report = json.loads(report_file.read_text())
    report["report_file"] = str(report_file)
    report["supervisor_exit_code"] = result.returncode
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("doctor")
    check.add_argument("profile", type=Path)
    check.add_argument("--deployment", action="store_true")
    load = sub.add_parser("load")
    load.add_argument("--endpoint", required=True)
    load.add_argument("--model", required=True)
    load.add_argument("--prompts", required=True, type=Path, help="JSON array of prompts")
    load.add_argument("--concurrency", type=int, default=2)
    load.add_argument("--max-tokens", type=int, default=128)
    load.add_argument("--cancel-every", type=int, default=0)
    load.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.command == "doctor":
            profile = VLLMProfile.model_validate_json(args.profile.read_text())
            missing = profile.prerequisites(deployment=args.deployment)
            print(
                json.dumps(
                    {
                        "profile": profile.model_dump(),
                        "missing": missing,
                        "runtime_verified": False,
                        "config_valid": True,
                    },
                    indent=2,
                )
            )
            return 2 if missing else 0
        token = os.environ.get("PAIS_INFERENCE_GATEWAY_TOKEN")
        if not token:
            raise RuntimeError("Set PAIS_INFERENCE_GATEWAY_TOKEN")
        report = asyncio.run(
            load_test(
                args.endpoint,
                args.model,
                token,
                json.loads(args.prompts.read_text()),
                concurrency=args.concurrency,
                max_tokens=args.max_tokens,
                cancel_every=args.cancel_every,
            )
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2))
        print(
            json.dumps({key: value for key, value in report.items() if key != "records"}, indent=2)
        )
        return 1 if report["errors"] else 0
    except (ValueError, OSError, RuntimeError) as exc:
        print(json.dumps({"error": str(exc), "runtime_verified": False}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
