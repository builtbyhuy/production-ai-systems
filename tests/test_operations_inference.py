from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from pais.inference import (
    AdmissionController,
    AdmissionRejected,
    GatewayConfig,
    VLLMProfile,
    create_gateway_app,
)


@pytest.mark.asyncio
async def test_admission_overload_timeout_and_cancel_do_not_leak_capacity():
    controller = AdmissionController(maximum=1, queue=1, timeout=0.02)
    lease = await controller.acquire()
    waiting = asyncio.create_task(controller.acquire())
    await asyncio.sleep(0)
    with pytest.raises(AdmissionRejected, match="queue_full"):
        await controller.acquire()
    with pytest.raises(AdmissionRejected, match="queue_timeout"):
        await waiting
    waiting = asyncio.create_task(controller.acquire())
    await asyncio.sleep(0)
    waiting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiting
    lease.release()
    lease.release()
    assert controller.accepted_or_queued == controller.active == 0
    recovered = await controller.acquire()
    recovered.release()


@pytest.mark.asyncio
async def test_drain_rejects_new_and_previously_queued_work():
    controller = AdmissionController(maximum=1, queue=1, timeout=1)
    lease = await controller.acquire()
    waiting = asyncio.create_task(controller.acquire())
    await asyncio.sleep(0)
    controller.closed = True
    lease.release()
    with pytest.raises(AdmissionRejected, match="draining"):
        await waiting
    with pytest.raises(AdmissionRejected, match="draining"):
        await controller.acquire()
    assert controller.accepted_or_queued == controller.active == 0


def test_hardware_profiles_reject_unsupported_combinations():
    good = {"name": "cpu-test", "evidence_profile": "functional", "backend": "cpu", "model": "tiny"}
    assert "isolated vllm==0.30.0 runtime" in VLLMProfile(**good).prerequisites()
    for change in (
        {"quantization": "awq"},
        {"backend": "cuda", "gpu_compute_capability": 7.0},
        {"backend": "cuda", "gpu_compute_capability": 7.5, "dtype": "bfloat16"},
    ):
        with pytest.raises(ValueError):
            VLLMProfile(**{**good, **change})


def test_backend_urls_cannot_contain_credentials_or_be_client_selected():
    with pytest.raises(ValueError):
        GatewayConfig(model="tiny", backends=["http://secret:token@backend:8000"])
    with pytest.raises(RuntimeError, match="authentication"):
        create_gateway_app(
            GatewayConfig(model="tiny", backends=["http://backend:8000"]),
            gateway_token="short",
            upstream_token="test-upstream",
        )


class BytesStream(httpx.AsyncByteStream):
    def __init__(self, chunks):
        self.chunks = chunks
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk

    async def aclose(self):
        self.closed = True


def _gateway(*, token_count=12, warmup_ok=True, stream_complete=True):
    observed = []
    streams = []

    async def handler(request):
        observed.append((request.url.host, request.url.path))
        assert request.headers["authorization"] == "Bearer upstream-test-token"
        if request.url.path == "/health":
            return httpx.Response(200)
        if request.url.path == "/tokenize":
            return httpx.Response(200, json={"count": token_count})
        payload = json.loads(request.content)
        if not payload.get("stream"):
            return httpx.Response(
                200, json={"choices": [{"message": {"content": "ready" if warmup_ok else ""}}]}
            )
        chunks = [b'data: {"choices":[{"delta":{"content":"hello"}}]}\n\n']
        if stream_complete:
            chunks += [
                b'data: {"choices":[],"usage":{"prompt_tokens":12,"completion_tokens":1}}\n\n',
                b"data: [DONE]\n\n",
            ]
        stream = BytesStream(chunks)
        streams.append(stream)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=stream)

    config = GatewayConfig(
        model="tiny",
        backends=["http://one:8000", "http://two:8000"],
        max_context_tokens=128,
        max_output_tokens=32,
    )
    app = create_gateway_app(
        config,
        gateway_token="gateway-test-token",
        upstream_token="upstream-test-token",
        transport=httpx.MockTransport(handler),
    )
    return app, observed, streams


@pytest.mark.asyncio
async def test_gateway_requires_warmup_and_balances_actual_http_contract():
    app, observed, streams = _gateway()
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://gateway"
        ) as client,
    ):
        assert (await client.get("/ready")).status_code == 200
        assert (await client.post("/v1/chat/completions", json={})).status_code == 401
        headers = {"Authorization": "Bearer gateway-test-token"}
        payload = {
            "model": "tiny",
            "messages": [{"role": "user", "content": "test"}],
            "max_tokens": 8,
        }
        responses = [
            await client.post("/v1/chat/completions", headers=headers, json=payload)
            for _ in range(2)
        ]
        assert all(
            response.status_code == 200 and "[DONE]" in response.text for response in responses
        )
        assert {response.headers["x-inference-backend"] for response in responses} == {
            "backend-0",
            "backend-1",
        }
        assert app.state.admission.active == 0
        assert all(stream.closed for stream in streams)
        assert sum(path == "/tokenize" for _, path in observed) == 2
        await client.post("/drain", headers=headers)
        assert (await client.get("/ready")).status_code == 503
        assert (
            await client.post("/v1/chat/completions", headers=headers, json=payload)
        ).status_code == 503


@pytest.mark.asyncio
async def test_failed_warmup_does_not_mark_server_ready():
    app, _, _ = _gateway(warmup_ok=False)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://gateway"
        ) as client,
    ):
        assert (await client.get("/ready")).status_code == 503


@pytest.mark.asyncio
async def test_actual_tokenizer_budget_prevents_generation_and_releases_admission():
    app, _, streams = _gateway(token_count=125)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://gateway"
        ) as client,
    ):
        response = await client.post(
            "/v1/chat/completions",
            headers={"Authorization": "Bearer gateway-test-token"},
            json={
                "model": "tiny",
                "messages": [{"role": "user", "content": "x"}],
                "max_tokens": 8,
            },
        )
        assert response.status_code == 422
        assert app.state.admission.active == 0
        assert not streams


@pytest.mark.asyncio
async def test_truncated_stream_is_observable_failure_without_retry():
    app, _, streams = _gateway(stream_complete=False)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://gateway"
        ) as client,
    ):
        response = await client.post(
            "/v1/chat/completions",
            headers={"Authorization": "Bearer gateway-test-token"},
            json={
                "model": "tiny",
                "messages": [{"role": "user", "content": "x"}],
                "max_tokens": 8,
            },
        )
        assert "upstream_stream_failed" in response.text
        assert "[DONE]" not in response.text
        assert len(streams) == 1 and streams[0].closed
        assert app.state.backends[0].failures == 1
        assert app.state.admission.active == 0
