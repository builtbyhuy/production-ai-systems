"""HTTP contract proof across two API app instances sharing SQLite admission state."""
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient
from pais.contracts import Answer, Profile
from pais.security import SharedLimiter

from services.api.app import create_app


def test_two_api_workers_return_consistent_429_and_retry_after(tmp_path):
    release = threading.Event()

    class BlockingRAG:
        def answer(self, principal, question, request_id=None):
            release.wait(timeout=10)
            return Answer(request_id=request_id, text="Fixture response", profile=Profile.FIXTURE,
                          model="fixture")

    path = str(tmp_path/"shared.sqlite")
    apps = [create_app(db_path=path, profile="fixture", rag=BlockingRAG(), allow_fixture_auth=True)
            for _ in range(2)]
    for app in apps:
        app.state.resources()["limiter"] = SharedLimiter(
            path, principal_rate=1000, tenant_rate=1000, principal_concurrency=3, tenant_concurrency=3)
    clients = [TestClient(app) for app in apps]
    headers = {"Authorization": "Bearer fixture-admin"}

    def post(i):
        return clients[i % 2].post("/api/chat", headers=headers,
                                   json={"question": "Explain retry limits", "message_id": f"request-{i}"})

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(post, i) for i in range(24)]
        deadline = time.monotonic()+8
        try:
            while sum(future.done() for future in futures) < 21 and time.monotonic() < deadline:
                time.sleep(0.01)
        finally:
            release.set()
        responses = [future.result(timeout=10) for future in futures]
    for client in clients:
        client.close()
    assert sum(response.status_code == 200 for response in responses) == 3
    rejected = [response for response in responses if response.status_code == 429]
    assert len(rejected) == 21
    assert all(int(response.headers["retry-after"]) >= 1 for response in rejected)
