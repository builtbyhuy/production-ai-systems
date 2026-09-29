"""Signed webhooks, transactional outbox, durable jobs, and a real Celery adapter."""
from __future__ import annotations

import hashlib
import hmac
import json
import random
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import Field

from pais.contracts import Action, Job, Principal, StrictModel, TraceContext, new_id, utcnow
from pais.db import Database
from pais.workflows import DurableEffectStore, action_digest


class RetryableJobError(RuntimeError):
    pass


class PermanentJobError(RuntimeError):
    pass


class UncertainOutcome(RuntimeError):
    pass


class JobBusy(RuntimeError):
    pass


class WebhookEvent(StrictModel):
    event_id: str = Field(min_length=1, max_length=200)
    tool: str
    arguments: dict[str, Any]
    context_version: str = Field(min_length=1, max_length=200)


def sign_webhook(body: bytes, secret: str, timestamp: int | None = None) -> str:
    timestamp = int(time.time()) if timestamp is None else timestamp
    digest = hmac.new(secret.encode(), str(timestamp).encode() + b"." + body, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={digest}"


def verify_webhook(body: bytes, signature: str, secret: str, now: float, tolerance: int = 300) -> None:
    if not secret or len(body) > 1024 * 1024:
        raise ValueError("Webhook secret missing or body too large")
    try:
        parts = signature.split(",")
        values = dict(part.split("=", 1) for part in parts)
        if len(parts) != 2 or set(values) != {"t", "v1"}:
            raise ValueError
        timestamp = int(values["t"])
    except (ValueError, TypeError) as exc:
        raise PermissionError("Malformed webhook signature") from exc
    if abs(now - timestamp) > tolerance:
        raise PermissionError("Webhook signature is outside its validity window")
    expected = sign_webhook(body, secret, timestamp).split("v1=", 1)[1]
    if not hmac.compare_digest(values["v1"], expected):
        raise PermissionError("Webhook signature mismatch")


class JobService:
    def __init__(
        self, db_path: str | Path,
        authorizer: Callable[[Principal], Principal] | None = None,
        allow_stored_principal: bool = False,
        clock: Callable[[], float] = time.time,
        max_attempts: int = 4,
        lease_seconds: int = 60,
        jitter: Callable[[], float] = random.random,
        telemetry: Any = None,
        capability_flags: Any = None,
    ):
        if not 1 <= max_attempts <= 20 or not 1 <= lease_seconds <= 3600:
            raise ValueError("Invalid retry/lease bounds")
        self.db = Database(db_path)
        self.authorizer = authorizer
        self.allow_stored_principal = allow_stored_principal
        self.clock, self.max_attempts, self.lease_seconds = clock, max_attempts, lease_seconds
        self.jitter, self.telemetry = jitter, telemetry
        from pais.operations import CapabilityFlags
        self.capability_flags = capability_flags or CapabilityFlags(self.db)
        self.effects = DurableEffectStore(str(db_path) + ".job-effects.sqlite")
        self.db.initialize("""
            CREATE TABLE IF NOT EXISTS job_records (
              job_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, subject TEXT NOT NULL,
              principal TEXT NOT NULL, trace TEXT NOT NULL, idempotency_key TEXT NOT NULL,
              payload TEXT NOT NULL, payload_hash TEXT NOT NULL, status TEXT NOT NULL,
              attempts INTEGER NOT NULL DEFAULT 0, next_at REAL NOT NULL,
              lease_until REAL, lease_token TEXT, cancel_requested INTEGER NOT NULL DEFAULT 0,
              error TEXT, receipt TEXT, replay_count INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
              UNIQUE(tenant_id,idempotency_key));
            CREATE TABLE IF NOT EXISTS job_outbox (
              outbox_id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES job_records(job_id),
              tenant_id TEXT NOT NULL, due_at REAL NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
              lease_until REAL, lease_token TEXT, attempts INTEGER NOT NULL DEFAULT 0);
            CREATE INDEX IF NOT EXISTS job_outbox_due ON job_outbox(status,due_at);
            CREATE TABLE IF NOT EXISTS job_audit (
              seq INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL, tenant_id TEXT NOT NULL,
              event TEXT NOT NULL, detail TEXT NOT NULL, timestamp TEXT NOT NULL);
        """)

    @staticmethod
    def _record(conn: Any, job_id: str, tenant: str, event: str, detail: Any) -> None:
        conn.execute(
            "INSERT INTO job_audit(job_id,tenant_id,event,detail,timestamp) VALUES(?,?,?,?,?)",
            (job_id, tenant, event, json.dumps(detail, sort_keys=True), utcnow()),
        )

    @staticmethod
    def _job(row: Any) -> Job:
        return Job(
            job_id=row["job_id"], principal=Principal.model_validate_json(row["principal"]),
            trace=TraceContext.model_validate_json(row["trace"]),
            idempotency_key=row["idempotency_key"], payload=json.loads(row["payload"]),
            status=row["status"], attempts=row["attempts"],
        )

    def _read(self, conn: Any, principal: Principal, job_id: str) -> Any:
        row = conn.execute(
            "SELECT * FROM job_records WHERE tenant_id=? AND job_id=?", (principal.tenant_id, job_id)
        ).fetchone()
        if row is None:
            raise LookupError("Job not found")
        if row["subject"] != principal.subject and "admin" not in principal.roles:
            raise PermissionError("Job access requires owner or tenant admin")
        return row

    def get(self, principal: Principal, job_id: str) -> Job:
        with self.db.transaction(False) as conn:
            return self._job(self._read(conn, principal, job_id))

    def accept_webhook(
        self, principal: Principal, body: bytes, signature: str, secret: str,
        trace: TraceContext | None = None,
    ) -> Job:
        principal.require("writer")
        verify_webhook(body, signature, secret, self.clock())
        event = WebhookEvent.model_validate_json(body)
        if event.tool not in DurableEffectStore.allowed_tools:
            raise PermissionError("Webhook requested an unapproved tool")
        payload = event.model_dump()
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, allow_nan=False).encode()).hexdigest()
        job = Job(principal=principal, trace=trace or TraceContext(),
                  idempotency_key=event.event_id, payload=payload)
        with self.db.transaction() as conn:
            if self.capability_flags:
                self.capability_flags.require_tx(conn, principal, "agent.execute")
            prior = conn.execute(
                "SELECT * FROM job_records WHERE tenant_id=? AND idempotency_key=?",
                (principal.tenant_id, event.event_id),
            ).fetchone()
            if prior:
                if prior["payload_hash"] != digest:
                    raise ValueError("Webhook event ID reused with different payload")
                if prior["subject"] != principal.subject:
                    raise PermissionError("Webhook event belongs to a different principal")
                return self._job(prior)
            conn.execute(
                "INSERT INTO job_records(job_id,tenant_id,subject,principal,trace,idempotency_key,"
                "payload,payload_hash,status,next_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (job.job_id, principal.tenant_id, principal.subject, principal.model_dump_json(),
                 job.trace.model_dump_json(), event.event_id, json.dumps(payload), digest,
                 "pending", self.clock(), utcnow(), utcnow()),
            )
            self._outbox(conn, job.job_id, principal.tenant_id, self.clock())
            self._record(conn, job.job_id, principal.tenant_id, "accepted", {"request_id": job.trace.request_id})
        return job

    @staticmethod
    def _outbox(conn: Any, job_id: str, tenant: str, due_at: float) -> None:
        conn.execute(
            "INSERT INTO job_outbox(outbox_id,job_id,tenant_id,due_at) VALUES(?,?,?,?)",
            (new_id(), job_id, tenant, due_at),
        )

    def dispatch(
        self, publish: Callable[[str, dict[str, str]], None], limit: int = 100,
        after_publish: Callable[[], None] | None = None,
    ) -> int:
        """Durable publisher. Duplicate publishes after a crash are safe at job admission."""
        delivered = 0
        for _ in range(min(limit, 1000)):
            token = new_id()
            with self.db.transaction() as conn:
                row = conn.execute(
                    "SELECT o.*,j.trace,j.status AS job_status FROM job_outbox o JOIN job_records j "
                    "ON o.job_id=j.job_id WHERE o.due_at<=? AND (o.status='pending' OR "
                    "(o.status='publishing' AND o.lease_until<=?)) ORDER BY o.due_at,o.outbox_id LIMIT 1",
                    (self.clock(), self.clock()),
                ).fetchone()
                if row is None:
                    break
                if row["job_status"] in {"cancelled", "succeeded", "dead", "uncertain"}:
                    conn.execute("UPDATE job_outbox SET status='discarded' WHERE outbox_id=?", (row["outbox_id"],))
                    continue
                conn.execute(
                    "UPDATE job_outbox SET status='publishing',lease_until=?,lease_token=?,attempts=attempts+1 "
                    "WHERE outbox_id=?", (self.clock() + self.lease_seconds, token, row["outbox_id"]),
                )
            trace = TraceContext.model_validate_json(row["trace"])
            carrier = {"traceparent": trace.traceparent} if trace.traceparent else {}
            try:
                publish(row["job_id"], carrier)
            except Exception:
                with self.db.transaction() as conn:
                    conn.execute(
                        "UPDATE job_outbox SET status='pending',due_at=?,lease_until=NULL,lease_token=NULL "
                        "WHERE outbox_id=? AND lease_token=?",
                        (self.clock() + 2, row["outbox_id"], token),
                    )
                raise
            if after_publish:
                after_publish()
            with self.db.transaction() as conn:
                conn.execute(
                    "UPDATE job_outbox SET status='published',lease_until=NULL WHERE outbox_id=? AND lease_token=?",
                    (row["outbox_id"], token),
                )
                conn.execute(
                    "UPDATE job_records SET status='queued',updated_at=? WHERE job_id=? AND status IN ('pending','retry')",
                    (utcnow(), row["job_id"]),
                )
                self._record(conn, row["job_id"], row["tenant_id"], "published", {})
            delivered += 1
        return delivered

    def default_handler(self, principal: Principal, payload: dict[str, Any], key: str) -> dict[str, Any]:
        action = Action(tool=payload["tool"], arguments=payload["arguments"],
                        context_version=payload["context_version"], idempotency_key=key)
        return self.effects.apply(principal, action, action_digest(action))

    def execute(
        self, principal: Principal, job_id: str,
        handler: Callable[[Principal, dict[str, Any], str], dict[str, Any]] | None = None,
        *, downstream_idempotent: bool | None = None, after_effect: Callable[[], None] | None = None,
    ) -> Job:
        if downstream_idempotent is None:
            downstream_idempotent = handler is None
        if self.authorizer:
            fresh = self.authorizer(principal)
            if fresh.subject != principal.subject or fresh.tenant_id != principal.tenant_id:
                raise PermissionError("Worker identity changed")
            principal = fresh
        principal.require("writer")
        token = new_id()
        with self.db.transaction() as conn:
            row = self._read(conn, principal, job_id)
            if row["status"] in {"succeeded", "cancelled", "dead", "uncertain"}:
                return self._job(row)
            if self.capability_flags:
                self.capability_flags.require_tx(conn, principal, "agent.execute")
            if row["status"] == "running" and row["lease_until"] > self.clock():
                raise JobBusy("Job already has a live worker lease")
            if row["next_at"] > self.clock():
                raise JobBusy("Job retry is not due")
            if row["attempts"] >= self.max_attempts:
                conn.execute("UPDATE job_records SET status='dead',error='attempts_exhausted' WHERE job_id=?", (job_id,))
                return self._job(self._read(conn, principal, job_id))
            if row["status"] == "running" and not downstream_idempotent:
                conn.execute("UPDATE job_records SET status='uncertain',error='worker_lost' WHERE job_id=?", (job_id,))
                self._record(conn, job_id, principal.tenant_id, "uncertain", {"reason": "worker_lost"})
                return self._job(self._read(conn, principal, job_id))
            conn.execute(
                "UPDATE job_records SET status='running',attempts=attempts+1,lease_until=?,lease_token=?,updated_at=? WHERE job_id=?",
                (self.clock() + self.lease_seconds, token, utcnow(), job_id),
            )
            job = self._job(self._read(conn, principal, job_id))
            self._record(conn, job_id, principal.tenant_id, "running", {"attempt": job.attempts})
        actual_handler = handler or self.default_handler
        try:
            with self.db.transaction(False) as conn:
                before_effect = self._read(conn, principal, job_id)
                if before_effect["cancel_requested"]:
                    raise PermanentJobError("cancelled_before_effect")
            if self.telemetry:
                carrier = {"traceparent": job.trace.traceparent} if job.trace.traceparent else {}
                with self.telemetry.span("job.execute", {"job.attempt": job.attempts}, carrier=carrier):
                    receipt = actual_handler(principal, job.payload, job.idempotency_key)
            else:
                receipt = actual_handler(principal, job.payload, job.idempotency_key)
        except (RetryableJobError, PermanentJobError, UncertainOutcome) as exc:
            self._fail(principal, job, token, exc, downstream_idempotent)
            return self.get(principal, job_id)
        except Exception as exc:  # noqa: BLE001 - persist unknown downstream outcomes at the worker boundary.
            safe_error: Exception = RetryableJobError(type(exc).__name__) if downstream_idempotent else UncertainOutcome(type(exc).__name__)
            self._fail(principal, job, token, safe_error, downstream_idempotent)
            return self.get(principal, job_id)
        if after_effect:
            after_effect()  # a crash leaves a running lease; no fake local completion
        with self.db.transaction() as conn:
            current = self._read(conn, principal, job_id)
            if current["lease_token"] != token:
                raise JobBusy("Lease was replaced before completion; reconcile the receipt")
            conn.execute(
                "UPDATE job_records SET status='succeeded',receipt=?,lease_until=NULL,error=NULL,updated_at=? WHERE job_id=?",
                (json.dumps(receipt, allow_nan=False), utcnow(), job_id),
            )
            self._record(conn, job_id, principal.tenant_id, "succeeded", {"cancel_requested": bool(current["cancel_requested"])})
        return self.get(principal, job_id)

    def _fail(self, principal: Principal, job: Job, token: str, error: Exception, idempotent: bool) -> None:
        with self.db.transaction() as conn:
            row = self._read(conn, principal, job.job_id)
            if row["lease_token"] != token:
                return
            if isinstance(error, UncertainOutcome) or (not idempotent and not isinstance(error, PermanentJobError)):
                status = "uncertain"
            elif row["cancel_requested"]:
                status = "cancelled"
            elif isinstance(error, PermanentJobError) or job.attempts >= self.max_attempts:
                status = "dead"
            else:
                status = "retry"
            delay = min(300, 2 ** job.attempts) * (0.75 + min(1, max(0, self.jitter())) * 0.5)
            due_at = self.clock() + delay
            conn.execute(
                "UPDATE job_records SET status=?,next_at=?,error=?,lease_until=NULL,updated_at=? WHERE job_id=?",
                (status, due_at, type(error).__name__, utcnow(), job.job_id),
            )
            if status == "retry":
                self._outbox(conn, job.job_id, principal.tenant_id, due_at)
            self._record(conn, job.job_id, principal.tenant_id, status, {"error_class": type(error).__name__, "attempt": job.attempts})

    def worker_execute(self, job_id: str) -> Job:
        """Broker-only entrypoint. Production requires a fresh membership resolver."""
        if self.authorizer is None and not self.allow_stored_principal:
            raise PermissionError("Worker requires a configured membership authorizer")
        with self.db.transaction(False) as conn:
            row = conn.execute("SELECT principal FROM job_records WHERE job_id=?", (job_id,)).fetchone()
        if row is None:
            raise LookupError("Job not found")
        return self.execute(Principal.model_validate_json(row["principal"]), job_id)

    def cancel(self, principal: Principal, job_id: str) -> Job:
        with self.db.transaction() as conn:
            row = self._read(conn, principal, job_id)
            if row["status"] in {"succeeded", "dead", "uncertain"}:
                raise ValueError("Completed/uncertain jobs cannot be cancelled")
            status = "running" if row["status"] == "running" else "cancelled"
            conn.execute(
                "UPDATE job_records SET cancel_requested=1,status=?,updated_at=? WHERE job_id=?",
                (status, utcnow(), job_id),
            )
            self._record(conn, job_id, principal.tenant_id, "cancel_requested", {"effect_may_be_in_flight": status == "running"})
        return self.get(principal, job_id)

    def recover_expired(self, downstream_idempotent: bool = True) -> int:
        with self.db.transaction() as conn:
            rows = conn.execute(
                "SELECT * FROM job_records WHERE status='running' AND lease_until<=?", (self.clock(),)
            ).fetchall()
            for row in rows:
                status = "retry" if downstream_idempotent else "uncertain"
                if row["attempts"] >= self.max_attempts:
                    status = "dead" if downstream_idempotent else "uncertain"
                conn.execute(
                    "UPDATE job_records SET status=?,next_at=?,lease_until=NULL,lease_token=NULL,updated_at=? WHERE job_id=?",
                    (status, self.clock(), utcnow(), row["job_id"]),
                )
                if status == "retry":
                    self._outbox(conn, row["job_id"], row["tenant_id"], self.clock())
                self._record(conn, row["job_id"], row["tenant_id"], "lease_recovered", {"status": status})
        return len(rows)

    def replay_dead(self, principal: Principal, job_id: str, reason: str) -> Job:
        principal.require("admin")
        if len(reason.strip()) < 8:
            raise ValueError("Replay requires an explanatory reason")
        with self.db.transaction() as conn:
            row = self._read(conn, principal, job_id)
            if row["status"] != "dead":
                raise ValueError("Only dead-letter jobs can be replayed; uncertain jobs require reconciliation")
            conn.execute(
                "UPDATE job_records SET status='retry',attempts=0,next_at=?,replay_count=replay_count+1,error=NULL,updated_at=? WHERE job_id=?",
                (self.clock(), utcnow(), job_id),
            )
            self._outbox(conn, job_id, principal.tenant_id, self.clock())
            self._record(conn, job_id, principal.tenant_id, "replayed", {"reason": reason})
        return self.get(principal, job_id)

    def history(self, principal: Principal, job_id: str) -> list[dict[str, Any]]:
        self.get(principal, job_id)
        with self.db.transaction(False) as conn:
            rows = conn.execute(
                "SELECT seq,event,detail,timestamp FROM job_audit WHERE tenant_id=? AND job_id=? ORDER BY seq",
                (principal.tenant_id, job_id),
            ).fetchall()
        return [{**dict(r), "detail": json.loads(r["detail"])} for r in rows]


def create_celery_app(service: JobService, broker_url: str, *, eager: bool = False) -> Any:
    """Real Celery tasks. Eager execution is contract evidence, not broker durability."""
    from celery import Celery

    if not eager and not broker_url.startswith(("redis://", "rediss://", "amqp://", "amqps://")):
        raise ValueError("A persistent Redis/RabbitMQ broker is required outside eager tests")
    app = Celery("pais_jobs", broker=broker_url)
    app.conf.update(
        task_serializer="json", result_serializer="json", accept_content=["json"],
        task_acks_late=True, task_reject_on_worker_lost=True, worker_prefetch_multiplier=1,
        task_default_delivery_mode="persistent", broker_connection_retry_on_startup=True,
        broker_transport_options={"visibility_timeout": 60}, task_always_eager=eager,
        task_eager_propagates=True, task_ignore_result=True, task_publish_retry=True,
    )

    @app.task(name="pais.execute_job", bind=True, max_retries=0)
    def execute_job(task: Any, job_id: str) -> dict[str, Any]:
        try:
            return service.worker_execute(job_id).model_dump()
        except JobBusy:
            return {"job_id": job_id, "status": "lease_owned_elsewhere"}

    return app


def publish_outbox(service: JobService, app: Any, limit: int = 100) -> int:
    return service.dispatch(
        lambda job_id, carrier: app.tasks["pais.execute_job"].apply_async(
            args=[job_id], task_id=job_id, headers=carrier,
        ), limit=limit,
    )


def webhook_router(service: JobService, resolve_token: Callable[[str], Principal],
                   secret_for_principal: Callable[[Principal], str]) -> Any:
    """Mount on FastAPI with server-owned credential and signing-secret resolvers."""
    from fastapi import APIRouter, HTTPException, Request
    from pydantic import ValidationError

    router = APIRouter()

    async def ingest(request: Request) -> dict[str, Any]:
        authorization = request.headers.get("authorization", "")
        if not authorization.startswith("Bearer "):
            raise HTTPException(401, "Bearer authentication required")
        try:
            principal = resolve_token(authorization[7:])
            job = service.accept_webhook(principal, await request.body(),
                request.headers.get("x-webhook-signature", ""), secret_for_principal(principal),
                TraceContext(traceparent=request.headers.get("traceparent")))
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc
        except (ValueError, ValidationError) as exc:
            raise HTTPException(422, "Invalid webhook payload or idempotency conflict") from exc
        return {"job_id": job.job_id, "status": job.status, "durably_accepted": True}

    # Request is imported lazily; supply the resolved annotation for FastAPI introspection.
    ingest.__annotations__["request"] = Request
    router.add_api_route("/webhooks", ingest, methods=["POST"], status_code=202)
    return router


def demo(db_path: str | Path, profile: str = "fixture") -> dict[str, Any]:
    if profile == "local":
        return native_demo(db_path)
    if profile != "fixture":
        raise RuntimeError("Local broker demo requires projects/16-automation/demo.py --broker-url and a persistent Redis broker")
    principal = Principal(subject="operator", tenant_id="demo", roles=["admin"])
    service = JobService(db_path, allow_stored_principal=True)
    service.capability_flags.set(principal, "agent.execute", True, reason="fixture demo setup")
    body = json.dumps({"event_id": f"demo-{time.time_ns()}", "tool": "record_note",
                       "arguments": {"note": "outbox delivery"}, "context_version": "v1"}).encode()
    signature = sign_webhook(body, "fixture-secret")
    job = service.accept_webhook(principal, body, signature, "fixture-secret")
    duplicate = service.accept_webhook(principal, body, signature, "fixture-secret")
    app = create_celery_app(service, "memory://", eager=True)
    publish_outbox(service, app)
    return {"profile": profile, "celery_executed": True, "broker_durability": "unverified",
            "duplicate_same_job": job.job_id == duplicate.job_id,
            "status": service.get(principal, job.job_id).status,
            "history": service.history(principal, job.job_id), "external_delivery": False}


def _native_worker(db_path: str, broker_url: str, crash_marker: str, repair_marker: str, log_path: str) -> None:
    """Only used by the explicit native acceptance drill, never by production dispatch."""
    import os
    with open(log_path, "a", encoding="utf-8") as log:
        os.dup2(log.fileno(), 1)
        os.dup2(log.fileno(), 2)

        class DrillService(JobService):
            def worker_execute(self, job_id: str) -> Job:
                with self.db.transaction(False) as conn:
                    row = conn.execute("SELECT principal FROM job_records WHERE job_id=?", (job_id,)).fetchone()
                if row is None:
                    raise LookupError("Missing drill job")
                principal = Principal.model_validate_json(row["principal"])

                def handler(identity: Principal, payload: dict[str, Any], key: str) -> dict[str, Any]:
                    mode = payload["arguments"].get("drill")
                    if mode == "poison" and not Path(repair_marker).exists():
                        raise PermanentJobError("fixture provider rejected a record")
                    if mode == "transient" and self.get(identity, job_id).attempts == 1:
                        raise RetryableJobError("fixture provider temporarily unavailable")
                    receipt = self.default_handler(identity, payload, key)
                    if mode == "crash" and not Path(crash_marker).exists():
                        with open(crash_marker, "x", encoding="utf-8") as marker:
                            marker.write("downstream committed before worker exit")
                            marker.flush()
                            os.fsync(marker.fileno())
                        os._exit(71)  # deliberate actual worker death after a separate durable effect
                    return receipt

                return self.execute(principal, job_id, handler, downstream_idempotent=True)

        service = DrillService(db_path, allow_stored_principal=True, max_attempts=2, lease_seconds=2,
                               jitter=lambda: 0.5)
        app = create_celery_app(service, broker_url)
        app.worker_main(["worker", "--pool=solo", "--concurrency=1", "--without-gossip",
                         "--without-mingle", "--without-heartbeat", "--loglevel=WARNING"])


def native_demo(db_path: str | Path) -> dict[str, Any]:
    """Real Redis AOF + separate Celery workers with an actual after-effect crash."""
    import multiprocessing

    from pais.memory import local_redis

    directory = Path(str(db_path) + ".native")
    directory.mkdir(parents=True, exist_ok=True)
    principal = Principal(subject="native-operator", tenant_id="native-drill", roles=["admin"])
    service = JobService(db_path, allow_stored_principal=True, max_attempts=2, lease_seconds=2,
                         jitter=lambda: 0.5)
    service.capability_flags.set(principal, "agent.execute", True, reason="explicit native pipeline drill")

    def accept(mode: str) -> Job:
        body = json.dumps({"event_id": f"{mode}-{time.time_ns()}", "tool": "record_note",
                           "arguments": {"drill": mode}, "context_version": "native-v1"}).encode()
        item = service.accept_webhook(principal, body, sign_webhook(body, "native-secret"), "native-secret")
        again = service.accept_webhook(principal, body, sign_webhook(body, "native-secret"), "native-secret")
        if again.job_id != item.job_id:
            raise AssertionError("Duplicate event created another job")
        return item

    def until(predicate: Callable[[], bool], seconds: float = 25) -> None:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.05)
        raise RuntimeError("Native Celery drill timed out; inspect worker logs")

    processes: list[Any] = []
    with local_redis(directory / "redis") as broker:
        try:
            producer = create_celery_app(service, broker.url)
            crash = accept("crash")
            publish_outbox(service, producer)
            import redis
            client = redis.Redis.from_url(broker.url)
            queued_before = client.llen("celery")
            client.close()
            broker.stop(kill=True)
            broker.start()
            client = redis.Redis.from_url(broker.url)
            queued_after = client.llen("celery")
            client.close()
            context = multiprocessing.get_context("spawn")

            def worker(log_name: str) -> Any:
                process = context.Process(target=_native_worker, args=(
                    str(db_path), broker.url, str(directory / "crashed-once"), str(directory / "provider-repaired"),
                    str(directory / log_name)))
                process.start()
                processes.append(process)
                return process

            first_worker = worker("worker-before-crash.log")
            until(lambda: first_worker.exitcode is not None)
            first_worker.join()
            if first_worker.exitcode != 71:
                raise RuntimeError(f"Expected after-effect worker exit 71, observed {first_worker.exitcode}")
            effects_after_crash = service.effects.count(principal)
            until(lambda: service.recover_expired() == 1)
            second_worker = worker("worker-recovered.log")
            publish_outbox(service, producer)
            until(lambda: service.get(principal, crash.job_id).status == "succeeded")
            effects_after_recovery = service.effects.count(principal)
            poison, healthy, transient = accept("poison"), accept("healthy"), accept("transient")
            publish_outbox(service, producer)
            until(lambda: service.get(principal, poison.job_id).status == "dead")
            until(lambda: service.get(principal, healthy.job_id).status == "succeeded")
            until(lambda: service.get(principal, transient.job_id).status == "retry")

            def transient_done() -> bool:
                publish_outbox(service, producer)
                return service.get(principal, transient.job_id).status == "succeeded"

            until(transient_done)
            before_replay = service.get(principal, poison.job_id).status
            (directory / "provider-repaired").write_text("test provider configuration repaired", encoding="utf-8")
            service.replay_dead(principal, poison.job_id, "provider input contract repaired and replay reviewed")
            publish_outbox(service, producer)
            until(lambda: service.get(principal, poison.job_id).status == "succeeded")
            second_worker.terminate()
            second_worker.join(timeout=10)
            return {"profile": "local", "inference_profile": "no model required", "real_celery_worker": True,
                "redis_aof_restarted": True, "queue_before_restart": queued_before, "queue_after_restart": queued_after,
                "worker_crash_exit": first_worker.exitcode, "effects_after_crash": effects_after_crash,
                "effects_after_recovery": effects_after_recovery, "crash_job_attempts": service.get(principal, crash.job_id).attempts,
                "dead_before_replay": before_replay, "dead_replay_status": service.get(principal, poison.job_id).status,
                "unrelated_job_status": service.get(principal, healthy.job_id).status,
                "transient_attempts": service.get(principal, transient.job_id).attempts,
                "visible_effects_total": service.effects.count(principal),
                "history": service.history(principal, crash.job_id),
                "dead_letter_history": service.history(principal, poison.job_id),
                "transient_history": service.history(principal, transient.job_id),
                "downstream": "separate durable local effect database", "external_delivery": False}
        finally:
            for process in processes:
                if process.is_alive():
                    process.terminate()
                process.join(timeout=10)
                if process.is_alive():
                    process.kill()
                    process.join(timeout=3)
