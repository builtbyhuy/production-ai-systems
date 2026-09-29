"""A persistent admission ledger and bounded, inspectable model-routing policy.

All costs are integer micro-USD. Provider usage priced by a versioned rate card is
distinct from invoice reconciliation. Unknown post-dispatch outcomes retain their
reservation, including on cancellation. Retries never share a reservation.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import sqlite3
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol
from urllib.parse import urlsplit

from pais.contracts import ModelRequest, ModelResponse, Principal, new_id
from pais.db import Database
from pais.observability import Telemetry, get_telemetry


class BudgetExceeded(RuntimeError):
    status_code = 429
    retry_after = 60


class RequestConflict(RuntimeError):
    status_code = 409


class ProviderFailure(RuntimeError):
    def __init__(self, message: str = "Provider failed", *, no_charge: bool = False,
                 retryable: bool = True):
        super().__init__(message)
        self.no_charge = no_charge
        self.retryable = retryable


class RouterUnavailable(RuntimeError):
    status_code = 503


@dataclass(frozen=True)
class Price:
    input_microusd_per_1k: int
    output_microusd_per_1k: int
    version: str
    basis: str = "simulation"

    def __post_init__(self):
        if self.input_microusd_per_1k < 0 or self.output_microusd_per_1k < 0:
            raise ValueError("Prices cannot be negative")
        if self.basis not in {"simulation", "local-zero", "provider-table"} or not self.version:
            raise ValueError("Price basis and version are required")

    def cost(self, input_tokens: int, output_tokens: int) -> int:
        if input_tokens < 0 or output_tokens < 0:
            raise ValueError("Token counts cannot be negative")
        # Ceil in integer arithmetic: no float rounding opens a quota race.
        return (input_tokens*self.input_microusd_per_1k
                + output_tokens*self.output_microusd_per_1k + 999)//1000


@dataclass(frozen=True)
class ModelSpec:
    name: str
    model: str
    price: Price
    max_context_tokens: int = 8192
    high_quality: bool = False
    capabilities: frozenset[str] = field(default_factory=lambda: frozenset({"text"}))
    timeout_seconds: float = 20

    def __post_init__(self):
        if not self.name or not self.model or self.max_context_tokens < 1:
            raise ValueError("A named model with a context limit is required")
        if not 0 < self.timeout_seconds <= 120:
            raise ValueError("Provider timeout must be bounded at 120 seconds")

    def upper_input_tokens(self, request: ModelRequest) -> int:
        # Server-derived conservative bound for text/BPE profiles, not a user claim.
        # Deployment must validate tokenizer/protocol overhead and provider billing semantics.
        byte_bound = sum(len(m.get("content", "").encode()) + 64 for m in request.messages) + 64
        return max(byte_bound, request.context_tokens)

    def reservation(self, request: ModelRequest) -> int:
        return self.price.cost(self.upper_input_tokens(request), request.max_output_tokens)


@dataclass
class ProviderResult:
    response: ModelResponse
    provider_reported_microusd: int | None = None


class Provider(Protocol):
    async def generate(self, spec: ModelSpec, request: ModelRequest) -> ProviderResult: ...


_SCHEMA = """
CREATE TABLE IF NOT EXISTS router_budgets(
  tenant_id TEXT PRIMARY KEY, cap_microusd INTEGER NOT NULL CHECK(cap_microusd>=0)
);
CREATE TABLE IF NOT EXISTS router_requests(
  tenant_id TEXT NOT NULL, request_id TEXT NOT NULL, subject TEXT NOT NULL,
  fingerprint TEXT NOT NULL, parent_request_id TEXT, budget_microusd INTEGER NOT NULL,
  status TEXT NOT NULL, decision_json TEXT NOT NULL, response_json TEXT,
  created_at REAL NOT NULL, PRIMARY KEY(tenant_id,request_id)
);
CREATE TABLE IF NOT EXISTS router_attempts(
  attempt_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, subject TEXT NOT NULL,
  request_id TEXT NOT NULL, model TEXT NOT NULL, attempt_number INTEGER NOT NULL,
  pricing_version TEXT NOT NULL, price_basis TEXT NOT NULL,
  estimated_microusd INTEGER NOT NULL, hold_microusd INTEGER NOT NULL,
  accounted_microusd INTEGER NOT NULL DEFAULT 0, input_tokens INTEGER, output_tokens INTEGER,
  provider_reported_microusd INTEGER, status TEXT NOT NULL, created_at REAL NOT NULL,
  UNIQUE(tenant_id,request_id,attempt_number),
  FOREIGN KEY(tenant_id,request_id) REFERENCES router_requests(tenant_id,request_id)
);
CREATE TABLE IF NOT EXISTS router_events(
  event_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, subject TEXT NOT NULL,
  request_id TEXT NOT NULL, parent_request_id TEXT, attempt_id TEXT NOT NULL,
  kind TEXT NOT NULL, microusd INTEGER, input_tokens INTEGER, output_tokens INTEGER,
  pricing_version TEXT NOT NULL, detail TEXT NOT NULL, timestamp REAL NOT NULL
);
CREATE TRIGGER IF NOT EXISTS router_events_no_update BEFORE UPDATE ON router_events
BEGIN SELECT RAISE(ABORT,'usage events are append only'); END;
CREATE TRIGGER IF NOT EXISTS router_events_no_delete BEFORE DELETE ON router_events
BEGIN SELECT RAISE(ABORT,'usage events are append only'); END;
CREATE INDEX IF NOT EXISTS router_attempts_budget ON router_attempts(tenant_id,status);
CREATE INDEX IF NOT EXISTS router_events_request ON router_events(tenant_id,request_id,timestamp);
CREATE TABLE IF NOT EXISTS router_cache(
  tenant_id TEXT NOT NULL, subject TEXT NOT NULL, fingerprint TEXT NOT NULL,
  response_json TEXT NOT NULL, expires_at REAL NOT NULL,
  PRIMARY KEY(tenant_id,subject,fingerprint)
);
CREATE TABLE IF NOT EXISTS router_circuits(
  model TEXT PRIMARY KEY, failures INTEGER NOT NULL DEFAULT 0,
  open_until REAL NOT NULL DEFAULT 0, probe_until REAL NOT NULL DEFAULT 0
);
"""


class BudgetLedger:
    def __init__(self, db_path: str, clock: Callable[[], float] = time.time):
        self.db = Database(db_path)
        self.clock = clock
        self.db.initialize(_SCHEMA)

    def configure_budget(self, principal: Principal, cap_microusd: int) -> None:
        principal.require("admin")
        if not isinstance(cap_microusd, int) or cap_microusd < 0:
            raise ValueError("Budget cap must be a nonnegative integer")
        with self.db.transaction() as conn:
            conn.execute("""INSERT INTO router_budgets VALUES(?,?) ON CONFLICT(tenant_id)
                            DO UPDATE SET cap_microusd=excluded.cap_microusd""",
                         (principal.tenant_id, cap_microusd))

    def start_request(self, request: ModelRequest, fingerprint: str, decision: dict,
                      parent_request_id: str | None = None) -> ModelResponse | None:
        p = request.principal
        with self.db.transaction() as conn:
            old = conn.execute("SELECT * FROM router_requests WHERE tenant_id=? AND request_id=?",
                               (p.tenant_id, request.request_id)).fetchone()
            if old:
                if (old["subject"] != p.subject or old["fingerprint"] != fingerprint
                        or old["budget_microusd"] != request.budget_microusd):
                    raise RequestConflict("Request identity is already bound to different content or owner")
                if old["status"] == "completed" and old["response_json"]:
                    return ModelResponse.model_validate_json(old["response_json"])
                raise RequestConflict("Request already exists; reconcile or retry with a fresh request ID")
            conn.execute("INSERT INTO router_requests VALUES(?,?,?,?,?,?,?,?,?,?)",
                         (p.tenant_id, request.request_id, p.subject, fingerprint, parent_request_id,
                          request.budget_microusd, "running", json.dumps(decision), None, self.clock()))
        return None

    def _event(self, conn, row, kind: str, microusd: int | None,
               detail: str, input_tokens=None, output_tokens=None) -> None:
        parent = conn.execute("SELECT parent_request_id FROM router_requests WHERE tenant_id=? AND request_id=?",
                              (row["tenant_id"], row["request_id"])).fetchone()
        conn.execute("INSERT INTO router_events VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (new_id(), row["tenant_id"], row["subject"], row["request_id"],
                      parent[0] if parent else None, row["attempt_id"], kind, microusd,
                      input_tokens, output_tokens, row["pricing_version"], detail, self.clock()))

    def reserve(self, request: ModelRequest, spec: ModelSpec, attempt_number: int) -> str:
        estimated = spec.reservation(request)
        p = request.principal
        attempt_id = new_id()
        with self.db.transaction() as conn:
            req = conn.execute("SELECT * FROM router_requests WHERE tenant_id=? AND request_id=?",
                               (p.tenant_id, request.request_id)).fetchone()
            if not req or req["subject"] != p.subject or req["status"] != "running":
                raise RequestConflict("An owned active parent request is required")
            cap = conn.execute("SELECT cap_microusd FROM router_budgets WHERE tenant_id=?",
                               (p.tenant_id,)).fetchone()
            if cap is None:
                raise BudgetExceeded("Tenant budget is not configured")
            committed = conn.execute("""SELECT coalesce(sum(hold_microusd+accounted_microusd),0)
                                        FROM router_attempts WHERE tenant_id=?""", (p.tenant_id,)).fetchone()[0]
            req_used = conn.execute("""SELECT coalesce(sum(hold_microusd+accounted_microusd),0)
                                       FROM router_attempts WHERE tenant_id=? AND request_id=?""",
                                    (p.tenant_id, request.request_id)).fetchone()[0]
            if committed+estimated > cap[0] or req_used+estimated > req["budget_microusd"]:
                raise BudgetExceeded("Atomic tenant or request budget reservation rejected")
            conn.execute("""INSERT INTO router_attempts(attempt_id,tenant_id,subject,request_id,model,
                            attempt_number,pricing_version,price_basis,estimated_microusd,hold_microusd,
                            status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                         (attempt_id, p.tenant_id, p.subject, request.request_id, spec.name,
                          attempt_number, spec.price.version, spec.price.basis, estimated, estimated,
                          "reserved", self.clock()))
            row = conn.execute("SELECT * FROM router_attempts WHERE attempt_id=?", (attempt_id,)).fetchone()
            self._event(conn, row, "reserved", estimated, "atomic pre-dispatch upper-bound hold")
            self._event(conn, row, "estimated", estimated, f"basis={spec.price.basis}")
        return attempt_id

    @staticmethod
    def _owned_attempt(conn, principal: Principal, attempt_id: str):
        row = conn.execute("SELECT * FROM router_attempts WHERE attempt_id=? AND tenant_id=?",
                           (attempt_id, principal.tenant_id)).fetchone()
        if row is None or (row["subject"] != principal.subject and "admin" not in principal.roles):
            raise PermissionError("Attempt not available to this principal")
        return row

    def dispatch(self, principal: Principal, attempt_id: str) -> None:
        with self.db.transaction() as conn:
            row = self._owned_attempt(conn, principal, attempt_id)
            if row["status"] != "reserved":
                raise RequestConflict("Attempt cannot be dispatched twice")
            conn.execute("UPDATE router_attempts SET status='dispatched' WHERE attempt_id=?", (attempt_id,))

    def settle(self, principal: Principal, attempt_id: str, spec: ModelSpec,
               result: ProviderResult) -> None:
        response = result.response
        input_tokens, output_tokens = response.input_tokens, response.output_tokens
        if input_tokens is None or output_tokens is None:
            self.unknown(principal, attempt_id, "provider omitted final usage")
            return
        if not isinstance(input_tokens, int) or not isinstance(output_tokens, int):
            raise TypeError("Reported usage must use integer tokens")
        cost = spec.price.cost(input_tokens, output_tokens)
        with self.db.transaction() as conn:
            row = self._owned_attempt(conn, principal, attempt_id)
            if row["status"] != "dispatched" or row["pricing_version"] != spec.price.version:
                raise RequestConflict("Attempt state or pricing version changed")
            conn.execute("""UPDATE router_attempts SET status='reported',hold_microusd=0,
                            accounted_microusd=?,input_tokens=?,output_tokens=?,
                            provider_reported_microusd=? WHERE attempt_id=?""",
                         (cost, input_tokens, output_tokens, result.provider_reported_microusd, attempt_id))
            self._event(conn, row, "reported", cost, "reported tokens priced; not invoice reconciled",
                        input_tokens, output_tokens)
            self._event(conn, row, "released", row["hold_microusd"], "replaced hold with priced usage")

    def unknown(self, principal: Principal, attempt_id: str, reason: str) -> None:
        with self.db.transaction() as conn:
            row = self._owned_attempt(conn, principal, attempt_id)
            if row["status"] == "unknown":
                return
            if row["status"] not in {"reserved", "dispatched"}:
                raise RequestConflict("Settled attempt cannot become unknown")
            conn.execute("UPDATE router_attempts SET status='unknown' WHERE attempt_id=?", (attempt_id,))
            self._event(conn, row, "unknown", None, reason[:120])

    def release_no_charge(self, principal: Principal, attempt_id: str, reason: str) -> None:
        with self.db.transaction() as conn:
            row = self._owned_attempt(conn, principal, attempt_id)
            if row["status"] == "released":
                return
            if row["status"] not in {"reserved", "dispatched"}:
                raise RequestConflict("Use an auditable correction to resolve uncertain or settled usage")
            conn.execute("UPDATE router_attempts SET status='released',hold_microusd=0 WHERE attempt_id=?",
                         (attempt_id,))
            self._event(conn, row, "released", row["hold_microusd"], reason[:120])

    def reconcile(self, principal: Principal, attempt_id: str, microusd: int,
                  evidence_reference: str) -> None:
        principal.require("admin")
        if not isinstance(microusd, int) or microusd < 0 or not evidence_reference.strip():
            raise ValueError("Reconciliation requires nonnegative cost and an evidence reference")
        with self.db.transaction() as conn:
            row = self._owned_attempt(conn, principal, attempt_id)
            if row["status"] in {"reserved", "dispatched"}:
                raise RequestConflict("Cannot reconcile an in-flight attempt")
            conn.execute("UPDATE router_attempts SET status='reconciled',hold_microusd=0,accounted_microusd=? WHERE attempt_id=?",
                         (microusd, attempt_id))
            self._event(conn, row, "correction", microusd-row["accounted_microusd"],
                        "reconciliation evidence="+hashlib.sha256(evidence_reference.encode()).hexdigest())
            self._event(conn, row, "reconciled", microusd, "authoritative reconciliation applied")
            if row["hold_microusd"]:
                self._event(conn, row, "released", row["hold_microusd"], "unknown hold reconciled")

    def finish_request(self, principal: Principal, request_id: str, status: str,
                       response: ModelResponse | None = None) -> None:
        if status not in {"completed", "failed", "cancelled"}:
            raise ValueError("Unknown request completion state")
        with self.db.transaction() as conn:
            changed = conn.execute("""UPDATE router_requests SET status=?,response_json=?
                                      WHERE tenant_id=? AND subject=? AND request_id=? AND status='running'""",
                                   (status, response.model_dump_json() if response else None,
                                    principal.tenant_id, principal.subject, request_id)).rowcount
            if not changed:
                raise RequestConflict("Parent request not owned or no longer running")

    def cache_get(self, principal: Principal, fingerprint: str) -> ModelResponse | None:
        with self.db.transaction(immediate=False) as conn:
            row = conn.execute("""SELECT response_json FROM router_cache WHERE tenant_id=? AND subject=?
                                  AND fingerprint=? AND expires_at>?""",
                               (principal.tenant_id, principal.subject, fingerprint, self.clock())).fetchone()
        return ModelResponse.model_validate_json(row[0]) if row else None

    def cache_put(self, principal: Principal, fingerprint: str, response: ModelResponse, ttl: float) -> None:
        with self.db.transaction() as conn:
            conn.execute("""INSERT INTO router_cache VALUES(?,?,?,?,?) ON CONFLICT(tenant_id,subject,fingerprint)
                            DO UPDATE SET response_json=excluded.response_json,expires_at=excluded.expires_at""",
                         (principal.tenant_id, principal.subject, fingerprint,
                          response.model_dump_json(), self.clock()+ttl))

    def record_cache(self, principal: Principal, request_id: str, source: str) -> None:
        with self.db.transaction() as conn:
            row = {"tenant_id": principal.tenant_id, "subject": principal.subject,
                   "request_id": request_id, "attempt_id": new_id(), "pricing_version": "cache-v1"}
            self._event(conn, row, "cache", 0, source)

    def snapshot(self, principal: Principal) -> dict[str, int]:
        # Budget totals are tenant-admin data, not another user's request history.
        principal.require("admin")
        with self.db.transaction(immediate=False) as conn:
            cap = conn.execute("SELECT cap_microusd FROM router_budgets WHERE tenant_id=?",
                               (principal.tenant_id,)).fetchone()
            rows = conn.execute("SELECT * FROM router_attempts WHERE tenant_id=?", (principal.tenant_id,)).fetchall()
        return {
            "cap": cap[0] if cap else 0, "attempts": len(rows),
            "reserved": sum(r["hold_microusd"] for r in rows),
            "estimated": sum(r["estimated_microusd"] for r in rows),
            "reported": sum(r["accounted_microusd"] for r in rows if r["status"] == "reported"),
            "reconciled": sum(r["accounted_microusd"] for r in rows if r["status"] == "reconciled"),
            "unknown_hold": sum(r["hold_microusd"] for r in rows if r["status"] == "unknown"),
            "unknown_attempts": sum(r["status"] == "unknown" for r in rows),
            "committed": sum(r["hold_microusd"]+r["accounted_microusd"] for r in rows),
        }

    def events(self, principal: Principal, request_id: str | None = None) -> list[dict]:
        clauses, args = ["tenant_id=?"], [principal.tenant_id]
        if "admin" not in principal.roles:
            clauses.append("subject=?")
            args.append(principal.subject)
        if request_id:
            clauses.append("request_id=?")
            args.append(request_id)
        with self.db.transaction(immediate=False) as conn:
            rows = conn.execute("SELECT * FROM router_events WHERE "+" AND ".join(clauses)+
                                " ORDER BY timestamp,rowid", args).fetchall()
        return [dict(row) for row in rows]


class CircuitBreaker:
    def __init__(self, ledger: BudgetLedger, failure_threshold: int = 2, cooldown_seconds: float = 30):
        if failure_threshold < 1 or cooldown_seconds <= 0:
            raise ValueError("Invalid circuit breaker configuration")
        self.ledger, self.threshold, self.cooldown = ledger, failure_threshold, cooldown_seconds

    def acquire(self, spec: ModelSpec) -> bool:
        now = self.ledger.clock()
        with self.ledger.db.transaction() as conn:
            row = conn.execute("SELECT * FROM router_circuits WHERE model=?", (spec.name,)).fetchone()
            if row is None:
                conn.execute("INSERT INTO router_circuits(model) VALUES(?)", (spec.name,))
                return True
            if row["open_until"] > now or row["probe_until"] > now:
                return False
            if row["failures"] >= self.threshold:
                conn.execute("UPDATE router_circuits SET probe_until=? WHERE model=?",
                             (now+spec.timeout_seconds+5, spec.name))
            return True

    def outcome(self, spec: ModelSpec, succeeded: bool | None) -> None:
        now = self.ledger.clock()
        with self.ledger.db.transaction() as conn:
            if succeeded is True:
                conn.execute("UPDATE router_circuits SET failures=0,open_until=0,probe_until=0 WHERE model=?", (spec.name,))
            elif succeeded is None:
                conn.execute("UPDATE router_circuits SET probe_until=0 WHERE model=?", (spec.name,))
            else:
                row = conn.execute("SELECT failures FROM router_circuits WHERE model=?", (spec.name,)).fetchone()
                failures = row[0]+1 if row else 1
                conn.execute("UPDATE router_circuits SET failures=?,open_until=?,probe_until=0 WHERE model=?",
                             (failures, now+self.cooldown if failures >= self.threshold else 0, spec.name))


@dataclass
class RoutingResult:
    response: ModelResponse
    decision: dict[str, Any]
    attempts: list[str]
    cache_hit: bool
    routing_overhead_seconds: float
    total_seconds: float
    cost_basis: str


class ModelRouter:
    def __init__(self, ledger: BudgetLedger, models: list[ModelSpec], provider: Provider,
                 max_attempts: int = 3, retries_per_model: int = 1, cache_ttl_seconds: float = 300,
                 telemetry: Telemetry | None = None, breaker: CircuitBreaker | None = None):
        if not models or len({s.name for s in models}) != len(models):
            raise ValueError("Unique configured model names required")
        if not 1 <= max_attempts <= 5 or not 0 <= retries_per_model <= 2:
            raise ValueError("Retries and attempts must be explicitly bounded")
        self.ledger, self.models, self.provider = ledger, models, provider
        self.max_attempts, self.retries_per_model = max_attempts, retries_per_model
        self.cache_ttl = cache_ttl_seconds
        self.telemetry = telemetry or get_telemetry()
        self.breaker = breaker or CircuitBreaker(ledger)

    def route(self, request: ModelRequest, policy: str = "routed") -> tuple[list[ModelSpec], dict]:
        if policy not in {"routed", "always-cheap", "always-expensive"}:
            raise ValueError("Unknown routing policy")
        required = set(request.required_capabilities)
        eligible = [s for s in self.models if required.issubset(s.capabilities)
                    and s.upper_input_tokens(request)+request.max_output_tokens <= s.max_context_tokens
                    and s.reservation(request) <= request.budget_microusd]
        if not eligible:
            raise RouterUnavailable("No model satisfies capability, context, and request budget constraints")
        eligible.sort(key=lambda s: s.reservation(request))
        reason = "cheap_default"
        server_input_bound = max(s.upper_input_tokens(request) for s in eligible)
        high = request.quality == "high" or request.task_type in {"research", "code"} or server_input_bound > 4096
        if policy == "always-expensive":
            eligible = [eligible[-1]]
            reason = "comparison_expensive"
        elif policy == "always-cheap":
            eligible = [eligible[0]]
            reason = "comparison_cheap"
        elif high:
            preferred = [s for s in eligible if s.high_quality]
            if not preferred:
                raise RouterUnavailable("Required quality escalation cannot be satisfied within budget")
            eligible = preferred + [s for s in eligible if s not in preferred]
            # A fallback cannot silently violate a requested high-quality requirement.
            if request.quality == "high":
                eligible = preferred
            reason = "quality_or_complexity_escalation"
        decision = {"policy": policy, "reason": reason, "preferred_model": eligible[0].name,
                    "candidates": [s.name for s in eligible], "task_type": request.task_type,
                    "context_tokens": request.context_tokens, "required_capabilities": sorted(required),
                    "server_input_token_bound": server_input_bound,
                    "max_attempts": self.max_attempts}
        return eligible, decision

    def _fingerprint(self, request: ModelRequest, policy: str) -> str:
        data = request.model_dump(exclude={"request_id", "principal", "budget_microusd"})
        data["policy"] = policy
        data["models"] = [asdict(s) | {"capabilities": sorted(s.capabilities)} for s in self.models]
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()

    async def complete(self, request: ModelRequest, policy: str = "routed",
                       parent_request_id: str | None = None) -> RoutingResult:
        start = time.perf_counter()
        with self.telemetry.span("router.route", {"request.id": request.request_id}), self.telemetry.stage("routing"):
            candidates, decision = self.route(request, policy)
            fingerprint = self._fingerprint(request, policy)
            old = self.ledger.start_request(request, fingerprint, decision, parent_request_id)
            overhead = time.perf_counter()-start
        if old is not None:
            self.ledger.record_cache(request.principal, request.request_id, "idempotent response replay")
            self.telemetry.record_cache()
            return RoutingResult(old, decision, [], True, overhead, time.perf_counter()-start, "cache-zero")
        cached = self.ledger.cache_get(request.principal, fingerprint) if self.cache_ttl > 0 else None
        if cached:
            self.ledger.record_cache(request.principal, request.request_id, "tenant-and-owner scoped response cache")
            self.ledger.finish_request(request.principal, request.request_id, "completed", cached)
            self.telemetry.record_cache()
            return RoutingResult(cached, decision, [], True, overhead, time.perf_counter()-start, "cache-zero")
        attempts: list[str] = []
        last_error: BaseException | None = None
        try:
            for spec in candidates:
                for _ in range(self.retries_per_model+1):
                    if len(attempts) >= self.max_attempts:
                        break
                    if not self.breaker.acquire(spec):
                        continue
                    try:
                        attempt_id = self.ledger.reserve(request, spec, len(attempts)+1)
                    except BaseException:
                        self.breaker.outcome(spec, None)
                        raise
                    attempts.append(attempt_id)
                    if len(attempts) > 1:
                        self.telemetry.record_retry()
                    self.ledger.dispatch(request.principal, attempt_id)
                    provider_start = time.perf_counter()
                    try:
                        with self.telemetry.span("model.call", {
                            "request.id": request.request_id, "model.name": spec.name,
                            "model.attempt": len(attempts), "routing.reason": decision["reason"],
                        }):
                            result = await asyncio.wait_for(self.provider.generate(spec, request), spec.timeout_seconds)
                        self.ledger.settle(request.principal, attempt_id, spec, result)
                    except asyncio.CancelledError:
                        self.ledger.unknown(request.principal, attempt_id, "cancelled after dispatch; provider billing unknown")
                        self.breaker.outcome(spec, None)
                        self.telemetry.record_model(spec.name, "cancelled", time.perf_counter()-provider_start)
                        raise
                    except Exception as exc:
                        no_charge = isinstance(exc, ProviderFailure) and exc.no_charge
                        if no_charge:
                            self.ledger.release_no_charge(request.principal, attempt_id, "provider adapter proved no charge")
                        else:
                            self.ledger.unknown(request.principal, attempt_id,
                                                "timeout after dispatch" if isinstance(exc, TimeoutError)
                                                else "failed after dispatch; usage unknown")
                        self.breaker.outcome(spec, False)
                        self.telemetry.record_model(spec.name, "timeout" if isinstance(exc, TimeoutError)
                                                    else "error", time.perf_counter()-provider_start)
                        last_error = exc
                        if isinstance(exc, ProviderFailure) and not exc.retryable:
                            raise RouterUnavailable("Provider rejected the request permanently") from exc
                        continue
                    self.breaker.outcome(spec, True)
                    self.telemetry.record_model(spec.name, "success", time.perf_counter()-provider_start,
                                                result.response.input_tokens, result.response.output_tokens)
                    self.ledger.finish_request(request.principal, request.request_id, "completed", result.response)
                    if self.cache_ttl > 0:
                        try:
                            self.ledger.cache_put(request.principal, fingerprint, result.response, self.cache_ttl)
                        except sqlite3.Error:
                            # Optional derived cache failure cannot erase a durable completed result.
                            pass
                    decision["selected_model"] = spec.name
                    return RoutingResult(result.response, decision, attempts, False, overhead,
                                         time.perf_counter()-start, spec.price.basis)
            raise RouterUnavailable("No provider completed within bounded attempts or circuit state") from last_error
        except BaseException as exc:
            self.ledger.finish_request(request.principal, request.request_id,
                                       "cancelled" if isinstance(exc, asyncio.CancelledError) else "failed")
            raise

    async def acomplete(self, request: ModelRequest, **kwargs) -> RoutingResult:
        return await self.complete(request, **kwargs)


class LiteLLMProvider:
    """Real LiteLLM acompletion adapter. Both SDK and LiteLLM internal retries are disabled.

    HTTP/provider retries belong to ModelRouter so every dispatch gets a separate ledger
    attempt. Provider cancellation does not establish that the provider stopped billing.
    """

    def __init__(self, api_base: str | None = None, allow_paid: bool = False):
        import os

        # Pricing is supplied by our versioned ledger. Use the installed SDK's
        # bundled model metadata instead of a hidden network fetch on import.
        os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
        try:
            import litellm
        except ImportError as exc:
            raise RouterUnavailable("LiteLLM required: uv sync --extra router") from exc
        self.litellm, self.api_base, self.allow_paid = litellm, api_base, allow_paid
        self.litellm.telemetry = False

    async def generate(self, spec: ModelSpec, request: ModelRequest) -> ProviderResult:
        local = (self.api_base and urlsplit(self.api_base).hostname in {"localhost", "127.0.0.1", "::1"}
                 and spec.model.startswith(("ollama/", "ollama_chat/")))
        if not self.allow_paid and not local:
            raise ProviderFailure("Connected provider spend is not enabled", no_charge=True, retryable=False)
        try:
            response = await self.litellm.acompletion(
                model=spec.model, messages=request.messages, max_tokens=request.max_output_tokens,
                api_base=self.api_base, timeout=spec.timeout_seconds,
                max_retries=0, num_retries=0, caching=False, stream=False,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            status = getattr(exc, "status_code", None)
            # Transport failures remain unknown. Known pre-generation 4xx can release the hold.
            raise ProviderFailure("LiteLLM request failed", no_charge=status in {400, 401, 403, 404, 422},
                                  retryable=status not in {400, 401, 403, 404, 422}) from exc
        usage = getattr(response, "usage", None)
        message = response.choices[0].message
        if not isinstance(message.content, str):
            raise ProviderFailure("Provider returned an unsupported response schema")
        return ProviderResult(ModelResponse(
            text=message.content, model=spec.model,
            input_tokens=getattr(usage, "prompt_tokens", None),
            output_tokens=getattr(usage, "completion_tokens", None),
            finish_reason=response.choices[0].finish_reason or "unknown"))


def demo(profile: str = "fixture", db_path: str | None = None,
         output_dir: str | None = None) -> dict:
    """Compare identical tasks, then exercise accounting failure paths without paid calls.

    The fixture provider does not consult the answer key, and receives no quality score.
    Local quality is scored from actual model strings. Zero local rates cannot establish
    dollar savings; a connected comparison requires an explicitly supplied live rate card.
    """
    import os
    import statistics
    from concurrent.futures import ThreadPoolExecutor
    from pathlib import Path
    from tempfile import TemporaryDirectory

    if profile not in {"fixture", "local"}:
        raise RouterUnavailable("This demo authorizes no paid calls; use a separately configured connected rate-card run")
    cheap_model = os.environ.get("PAIS_ROUTER_CHEAP_MODEL")
    expensive_model = os.environ.get("PAIS_ROUTER_EXPENSIVE_MODEL")
    if profile == "local" and (not cheap_model or not expensive_model or cheap_model == expensive_model):
        raise RouterUnavailable("Configure two distinct installed Ollama models with PAIS_ROUTER_CHEAP_MODEL and PAIS_ROUTER_EXPENSIVE_MODEL")
    if profile == "local":
        import httpx
        endpoint = os.environ.get("PAIS_OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
        if urlsplit(endpoint).hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise RouterUnavailable("Local comparison requires a loopback Ollama endpoint")
        try:
            response = httpx.get(endpoint+"/api/tags", timeout=5, trust_env=False)
            response.raise_for_status()
            installed = {m["name"] for m in response.json()["models"]}
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            raise RouterUnavailable("Ollama model inventory unavailable; local comparison prerequisites not met") from exc
        if any(name.split("/", 1)[-1] not in installed for name in (cheap_model, expensive_model)):
            raise RouterUnavailable("Both configured local models must already be installed; this demo never downloads models")
    corpus = [
        ("timeout", "A service's documented timeout is 30 seconds. Return only the integer timeout.", "30", "extract", "standard"),
        ("workers", "A queue uses four workers. Return only the integer worker count.", "4", "extract", "standard"),
        ("status", "The health check status is READY. Return only the status token.", "READY", "extract", "standard"),
        ("owner", "The tenant is cobalt; the deployment owner is Maya. Return only the owner's name.", "Maya", "extract", "standard"),
        ("retention", "Trace retention is 24 hours. Return the equivalent number of minutes as an integer.", "1440", "answer", "standard"),
        ("capacity", "Three workers each process 40 jobs per hour. Return total jobs per hour as an integer.", "120", "answer", "standard"),
        ("conflict", "Policy A says timeout 30 seconds; equally authoritative policy B says 60 seconds. Output CONFLICT if the values disagree, otherwise CONSISTENT.", "CONFLICT", "research", "high"),
        ("abstain", "No information about the database password is available. Output only INSUFFICIENT_EVIDENCE.", "INSUFFICIENT_EVIDENCE", "research", "high"),
        ("race", "A balance is 10. Two concurrent callers each read 10 then independently approve spending 7. Does a read-then-write check guarantee the cap? Return YES or NO.", "NO", "code", "high"),
        ("retry", "A provider timeout occurs after dispatch and returns no usage. Is the spend certainly zero? Return YES or NO.", "NO", "code", "high"),
        ("identity", "Tenant A supplies tenant B's valid document UUID but lacks membership in B. Should access be granted? Return YES or NO.", "NO", "research", "high"),
        ("cache", "A response is served entirely from the application's local cache without a provider call. How many provider attempts occurred for that access? Return an integer.", "0", "answer", "standard"),
    ]

    class FixtureProvider:
        async def generate(self, spec, req):
            return ProviderResult(ModelResponse(text="Fixture routing response; model quality unmeasured.",
                                                model=spec.model, input_tokens=20, output_tokens=10,
                                                finish_reason="stop"))

    provider = (LiteLLMProvider(api_base=os.environ.get("PAIS_OLLAMA_URL", "http://127.0.0.1:11434"))
                if profile == "local" else FixtureProvider())
    basis = "local-zero" if profile == "local" else "simulation"
    rates = (0, 0, 0, 0) if profile == "local" else (1000, 2000, 10000, 20000)
    models = [ModelSpec("cheap", cheap_model or "fixture-cheap",
                        Price(rates[0], rates[1], "demo-rate-v1", basis), max_context_tokens=32768),
              ModelSpec("expensive", expensive_model or "fixture-expensive",
                        Price(rates[2], rates[3], "demo-rate-v1", basis),
                        max_context_tokens=32768, high_quality=True)]

    async def compare(ledger):
        results = {}
        raw = []
        for policy in ("always-cheap", "always-expensive", "routed"):
            p = Principal(subject="router-demo", tenant_id=new_id(), roles=["admin"])
            ledger.configure_budget(p, 10_000_000)
            router = ModelRouter(ledger, models, provider, max_attempts=1,
                                 retries_per_model=0, cache_ttl_seconds=0)
            latencies, overheads, passed, errors = [], [], 0, 0
            for case_id, prompt, expected, task, quality in corpus:
                req = ModelRequest(request_id=f"{policy}:{case_id}", principal=p,
                                   messages=[{"role": "user", "content": prompt}], task_type=task,
                                   quality=quality, max_output_tokens=64, budget_microusd=100_000)
                try:
                    result = await router.complete(req, policy=policy)
                    actual = result.response.text.strip().strip("\"'. ").casefold()
                    correct = actual == expected.casefold()
                    passed += correct
                    latencies.append(result.total_seconds)
                    overheads.append(result.routing_overhead_seconds)
                    raw.append({"policy": policy, "case_id": case_id,
                                "model": result.response.model, "output": result.response.text,
                                "quality_passed": correct if profile == "local" else None,
                                "seconds": result.total_seconds,
                                "routing_overhead_seconds": result.routing_overhead_seconds})
                except (RouterUnavailable, BudgetExceeded) as exc:
                    errors += 1
                    raw.append({"policy": policy, "case_id": case_id, "error": type(exc).__name__})
            ordered = sorted(latencies)
            results[policy] = {"cases": len(corpus), "errors": errors,
                               "quality_passes": passed if profile == "local" else None,
                               "quality_accuracy": passed/len(corpus) if profile == "local" else None,
                               "mean_seconds": statistics.mean(latencies) if latencies else None,
                               "p95_seconds": ordered[min(len(ordered)-1, math.ceil(len(ordered)*0.95)-1)] if ordered else None,
                               "mean_routing_overhead_seconds": statistics.mean(overheads) if overheads else None,
                               "ledger": ledger.snapshot(p)}
        if output_dir:
            Path(output_dir).mkdir(parents=True, exist_ok=True)
            (Path(output_dir)/"router-runs.json").write_text(json.dumps(raw, indent=2))
        return results

    async def failure_drills(ledger):
        # Always fixture-injected operational failures, separately labeled from model quality.
        p = Principal(subject="drill", tenant_id=new_id(), roles=["admin"])
        ledger.configure_budget(p, 100_000)
        failures = []

        drill_models = [ModelSpec("cheap-drill", "fixture-cheap", Price(1000, 2000, "drill-v1")),
                        ModelSpec("expensive-drill", "fixture-expensive", Price(10000, 20000, "drill-v1"), high_quality=True)]
        # This provider keys its injected behavior to the configured cheap model, never answers.
        class RetryDrillProvider(FixtureProvider):
            async def generate(self, spec, req):
                if spec.name == "cheap-drill":
                    failures.append(spec.name)
                    raise ProviderFailure("fixture pre-generation failure", no_charge=True)
                return await super().generate(spec, req)

        req = ModelRequest(principal=p, messages=[{"role": "user", "content": "fixture failure drill"}],
                           max_output_tokens=10, budget_microusd=10000)
        result = await ModelRouter(ledger, drill_models, RetryDrillProvider(), cache_ttl_seconds=0).complete(req)
        started = asyncio.Event()
        class CancellationProvider:
            async def generate(self, spec, req):
                started.set()
                await asyncio.sleep(60)
        cancel_req = req.model_copy(update={"request_id": new_id()})
        # Different model alias avoids sharing the intentionally opened circuit from the retry drill.
        cancel_model = ModelSpec("cancel-drill", "fixture", Price(1000, 2000, "drill-v1"))
        task = asyncio.create_task(ModelRouter(ledger, [cancel_model], CancellationProvider()).complete(cancel_req))
        await started.wait()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        return {"scope": "fixture fault injection", "retry_attempts": len(result.attempts),
                "fallback_model": result.response.model, "cancelled_usage_retains_hold": ledger.snapshot(p)["unknown_hold"] > 0,
                "ledger": ledger.snapshot(p)}

    with TemporaryDirectory(prefix="pais-router-") as temp:
        ledger = BudgetLedger(db_path or str(Path(temp)/"router.sqlite"))
        results = asyncio.run(compare(ledger))
        faults = asyncio.run(failure_drills(ledger))
        p = Principal(subject="quota-drill", tenant_id=new_id(), roles=["admin"])
        quota_model = ModelSpec("quota", "fixture", Price(1000, 1000, "drill-v1"))
        req = ModelRequest(principal=p, messages=[{"role": "user", "content": "quota"}],
                           max_output_tokens=10, budget_microusd=1000)
        ledger.configure_budget(p, quota_model.reservation(req)*3)
        def reserve(i):
            item = req.model_copy(update={"request_id": f"quota-{i}"})
            ledger.start_request(item, str(i), {})
            try:
                ledger.reserve(item, quota_model, 1)
                return True
            except BudgetExceeded:
                return False
        with ThreadPoolExecutor(max_workers=8) as pool:
            admitted = sum(pool.map(reserve, range(24)))
        quota = ledger.snapshot(p)
    return {"project": "P02", "profile": profile, "status": "partial", "price_basis": basis,
            "dataset_sha256": hashlib.sha256(json.dumps(corpus, sort_keys=True).encode()).hexdigest(),
            "dataset_scope": "12 synthetic release-comparison cases; development exposure disclosed in source",
            "comparison": results, "fault_drills": faults,
            "concurrent_budget_drill": {"attempted": 24, "admitted": admitted, "cap": quota["cap"],
                                       "committed": quota["committed"]},
            "actual_dollar_savings": None,
            "limits": ["Fixture responses are not scored for model quality",
                       "Local-zero rates establish no savings over a paid baseline",
                       "Provider invoice reconciliation and connected comparable runs not executed"]}
