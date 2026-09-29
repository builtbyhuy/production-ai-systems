import asyncio
from concurrent.futures import ThreadPoolExecutor

import pytest
from pais.contracts import ModelRequest, ModelResponse, Principal
from pais.reliability import (
    BudgetExceeded,
    BudgetLedger,
    CircuitBreaker,
    ModelRouter,
    ModelSpec,
    Price,
    ProviderFailure,
    ProviderResult,
    RequestConflict,
    RouterUnavailable,
)

ADMIN = Principal(subject="alice", tenant_id="a", roles=["admin"])
CHEAP = ModelSpec("cheap", "fixture-cheap", Price(1000, 2000, "fixture-v1"))
EXPENSIVE = ModelSpec("expensive", "fixture-expensive", Price(10000, 20000, "fixture-v1"),
                      high_quality=True, capabilities=frozenset({"text", "json"}))


def request(request_id="r1", **kwargs):
    return ModelRequest(request_id=request_id, principal=ADMIN,
                        messages=[{"role": "user", "content": "hello"}],
                        max_output_tokens=10, budget_microusd=20000, **kwargs)


class WorkingProvider:
    def __init__(self):
        self.calls = []

    async def generate(self, spec, request):
        self.calls.append(spec.name)
        return ProviderResult(ModelResponse(text="Fixture output", model=spec.model,
                                            input_tokens=5, output_tokens=2, finish_reason="stop"))


def setup(tmp_path, cap=1_000_000):
    ledger = BudgetLedger(str(tmp_path/"budget.sqlite"))
    ledger.configure_budget(ADMIN, cap)
    return ledger


def test_atomic_budget_reservations_across_concurrent_ledger_instances(tmp_path):
    ledger = setup(tmp_path, cap=CHEAP.reservation(request())*3)
    path = str(tmp_path/"budget.sqlite")
    ledgers = [BudgetLedger(path) for _ in range(8)]

    def attempt(i):
        local, req = ledgers[i % 8], request(f"r{i}")
        local.start_request(req, str(i), {})
        try:
            return local.reserve(req, CHEAP, 1)
        except BudgetExceeded:
            return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        admitted = [x for x in pool.map(attempt, range(24)) if x]
    assert len(admitted) == 3
    assert ledger.snapshot(ADMIN)["committed"] == ledger.snapshot(ADMIN)["cap"]
    assert BudgetLedger(path).snapshot(ADMIN)["reserved"] == ledger.snapshot(ADMIN)["cap"]


@pytest.mark.asyncio
async def test_router_quality_capability_baselines_and_cache_scope(tmp_path):
    ledger = setup(tmp_path)
    provider = WorkingProvider()
    router = ModelRouter(ledger, [CHEAP, EXPENSIVE], provider)
    simple = await router.complete(request())
    assert simple.decision["selected_model"] == "cheap" and not simple.cache_hit
    replay = await router.complete(request())
    assert replay.cache_hit and len(provider.calls) == 1
    cached = await router.complete(request("r2"))
    assert cached.cache_hit and len(provider.calls) == 1
    high = await router.complete(request("r3", quality="high"))
    assert high.decision["selected_model"] == "expensive"
    json_result = await router.complete(request("r4", required_capabilities=["json"]))
    assert json_result.response.model == "fixture-expensive"
    assert router.route(request(), "always-cheap")[0] == [CHEAP]
    assert router.route(request(), "always-expensive")[0] == [EXPENSIVE]
    other = request("r5").model_copy(update={"principal": Principal(subject="bob", tenant_id="a")})
    result = await router.complete(other)
    assert not result.cache_hit  # same tenant is insufficient: owner-scoped cache
    assert not ledger.events(Principal(subject="bob", tenant_id="b", roles=["admin"]))
    assert len([e for e in ledger.events(ADMIN) if e["kind"] == "cache"]) == 2


@pytest.mark.asyncio
async def test_retry_accounting_unknown_hold_and_authoritative_reconciliation(tmp_path):
    ledger = setup(tmp_path)

    class FailingOnce(WorkingProvider):
        async def generate(self, spec, req):
            if not self.calls:
                self.calls.append("failure")
                raise ProviderFailure("ambiguous transport failure")
            return await super().generate(spec, req)

    router = ModelRouter(ledger, [CHEAP], FailingOnce(), cache_ttl_seconds=0)
    result = await router.complete(request())
    assert len(result.attempts) == 2
    snap = ledger.snapshot(ADMIN)
    assert snap["unknown_attempts"] == 1
    assert snap["unknown_hold"] == CHEAP.reservation(request())
    assert snap["reported"] == 9
    assert snap["reconciled"] == 0  # token-priced usage is not an invoice
    events = ledger.events(ADMIN)
    unknown = next(e for e in events if e["kind"] == "unknown")
    assert unknown["microusd"] is None
    ledger.reconcile(ADMIN, unknown["attempt_id"], 17, "fixture invoice record 17 (simulation)")
    snap = ledger.snapshot(ADMIN)
    assert snap["unknown_attempts"] == 0 and snap["reconciled"] == 17
    assert snap["committed"] == 26
    assert len([e for e in ledger.events(ADMIN) if e["kind"] == "reserved"]) == 2


@pytest.mark.asyncio
async def test_cancellation_keeps_hold_and_cancels_provider(tmp_path):
    ledger = setup(tmp_path)
    started, stopped = asyncio.Event(), asyncio.Event()

    class SlowProvider:
        async def generate(self, spec, req):
            started.set()
            try:
                await asyncio.sleep(20)
            finally:
                stopped.set()

    router = ModelRouter(ledger, [CHEAP], SlowProvider())
    task = asyncio.create_task(router.complete(request()))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert stopped.is_set()
    assert ledger.snapshot(ADMIN)["unknown_hold"] == CHEAP.reservation(request())
    with pytest.raises(RequestConflict):
        await router.complete(request())


@pytest.mark.asyncio
async def test_provider_rejection_releases_only_proven_no_charge(tmp_path):
    ledger = setup(tmp_path)

    class DeniedProvider:
        async def generate(self, spec, req):
            raise ProviderFailure("validation rejection", no_charge=True, retryable=False)

    with pytest.raises(RouterUnavailable, match="permanently"):
        await ModelRouter(ledger, [CHEAP], DeniedProvider()).complete(request())
    snap = ledger.snapshot(ADMIN)
    assert snap["committed"] == 0 and snap["attempts"] == 1


def test_circuit_breaker_single_durable_half_open_probe(tmp_path):
    now = [100.0]
    ledger = BudgetLedger(str(tmp_path/"circuits.sqlite"), clock=lambda: now[0])
    breaker = CircuitBreaker(ledger, failure_threshold=2, cooldown_seconds=10)
    assert breaker.acquire(CHEAP)
    breaker.outcome(CHEAP, False)
    assert breaker.acquire(CHEAP)
    breaker.outcome(CHEAP, False)
    assert not breaker.acquire(CHEAP)
    now[0] += 11
    assert breaker.acquire(CHEAP)
    assert not CircuitBreaker(ledger).acquire(CHEAP)
    breaker.outcome(CHEAP, True)
    assert breaker.acquire(CHEAP)


def test_ledger_append_only_and_cross_tenant_attempt_rejected(tmp_path):
    ledger = setup(tmp_path)
    req = request()
    ledger.start_request(req, "x", {})
    attempt = ledger.reserve(req, CHEAP, 1)
    other = Principal(subject="alice", tenant_id="b", roles=["admin"])
    with pytest.raises(PermissionError):
        ledger.dispatch(other, attempt)
    import sqlite3
    with pytest.raises(sqlite3.IntegrityError, match="append only"), ledger.db.transaction() as conn:
        conn.execute("DELETE FROM router_events")


@pytest.mark.asyncio
async def test_missing_usage_is_unknown_not_zero(tmp_path):
    ledger = setup(tmp_path)

    class MissingUsage:
        async def generate(self, spec, req):
            return ProviderResult(ModelResponse(text="fixture", model=spec.model, finish_reason="stop"))

    result = await ModelRouter(ledger, [CHEAP], MissingUsage()).complete(request())
    assert result.response.input_tokens is None
    snap = ledger.snapshot(ADMIN)
    assert snap["unknown_attempts"] == 1 and snap["reported"] == 0 and snap["reserved"] > 0
