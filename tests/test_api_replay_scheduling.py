"""Cached validation must not monopolize ASGI's event loop or escape admission."""
import asyncio
import threading

import pytest
from pais.contracts import Answer, Principal, Profile
from pais.security import SecurityViolation

from services.api.app import ChatRequest, create_app


class StreamRequest:
    def __init__(self):
        self.headers = {}

    async def is_disconnected(self):
        return False


def prepared_replay(tmp_path, monkeypatch, path):
    monkeypatch.delenv("PAIS_AUTH_TOKENS", raising=False)
    monkeypatch.delenv("PAIS_OTLP_ENDPOINT", raising=False)
    app = create_app(tmp_path / "state.db", profile="fixture", allow_fixture_auth=True)
    principal = Principal(subject="alice", tenant_id="a", roles=["reader"])
    body = ChatRequest(question="What is the maintenance interval?", message_id="stable")
    resources = app.state.resources()
    claim = resources["messages"].claim(principal, body.message_id, body.conversation_id, body.question)
    resources["messages"].complete(principal, body.message_id, Answer(
        message_id=claim.answer_id, request_id=claim.request_id, text="A checked cached answer.",
        profile=Profile.FIXTURE, model="fixture",
    ))
    endpoint = next(route.endpoint for route in app.routes if getattr(route, "path", None) == path)

    async def invoke():
        if path.endswith("/stream"):
            return await endpoint(body, principal, StreamRequest())
        return await endpoint(body, principal)

    return app, resources, principal, invoke


def lease_count(resources):
    with resources["limiter"].db.transaction(False) as conn:
        return conn.execute("SELECT count(*) FROM sec_leases").fetchone()[0]


@pytest.mark.parametrize("path", ["/api/chat", "/api/chat/stream"])
def test_cached_output_validation_yields_event_loop_and_retains_lease(tmp_path, monkeypatch, path):
    app, resources, principal, invoke = prepared_replay(tmp_path, monkeypatch, path)
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    original = resources["policy"].filter_output

    def blocked_filter(text):
        entered.set()
        release.wait(timeout=2)
        finished.set()
        return original(text)

    monkeypatch.setattr(resources["policy"], "filter_output", blocked_filter)

    async def run():
        task = asyncio.create_task(invoke())
        try:
            assert await asyncio.to_thread(entered.wait, 1)
            # An async health handler can run while required replay validation is blocked.
            # Before the fix the validator ran on this event loop, so it finished first.
            assert not finished.is_set()
            health = next(route.endpoint for route in app.routes
                          if getattr(route, "path", None) == "/api/health")
            assert health()["required_validator_ready"]
            assert lease_count(resources) == 1
        finally:
            release.set()
        response = await task
        if path.endswith("/stream"):
            chunks = [chunk async for chunk in response.body_iterator]
            assert any(b"A checked cached answer." in chunk for chunk in chunks)
        else:
            assert response.text == "A checked cached answer."
        assert lease_count(resources) == 0
        assert resources["messages"].list(principal, "workspace")[0]["status"] == "completed"

    asyncio.run(run())


@pytest.mark.parametrize("path", ["/api/chat", "/api/chat/stream"])
def test_cancelled_cached_delivery_keeps_validator_admitted_until_it_finishes(tmp_path, monkeypatch, path):
    app, resources, _principal, invoke = prepared_replay(tmp_path, monkeypatch, path)
    entered, release = threading.Event(), threading.Event()
    original = resources["policy"].filter_output

    def blocked_filter(text):
        entered.set()
        release.wait(timeout=2)
        return original(text)

    monkeypatch.setattr(resources["policy"], "filter_output", blocked_filter)

    async def run():
        task = asyncio.create_task(invoke())
        try:
            assert await asyncio.to_thread(entered.wait, 1)
            assert not task.done()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert lease_count(resources) == 1
        finally:
            release.set()
        await asyncio.gather(*app.state.background_tasks)
        assert lease_count(resources) == 0

    asyncio.run(run())


@pytest.mark.parametrize("path", ["/api/chat", "/api/chat/stream"])
def test_cached_validator_failure_denies_delivery_and_releases_lease(tmp_path, monkeypatch, path):
    _app, resources, principal, invoke = prepared_replay(tmp_path, monkeypatch, path)

    def denied(_text):
        raise SecurityViolation("Required validator rejected cached output", 422)

    monkeypatch.setattr(resources["policy"], "filter_output", denied)
    with pytest.raises(SecurityViolation):
        asyncio.run(invoke())
    assert lease_count(resources) == 0
    assert resources["messages"].list(principal, "workspace")[0]["status"] == "completed"
