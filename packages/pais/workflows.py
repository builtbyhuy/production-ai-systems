"""Exact-action approvals backed by real LangGraph SQLite interrupts.

The graph is a durable orchestration cursor, never an authorization boundary. Every
read and transition first scopes the approval to a trusted Principal. Local effects
have a separate durable idempotency database so a crash after the effect can be
recovered without creating it twice. A remote adapter must offer the same contract.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import math
import threading
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, Protocol, TypedDict

from pais.contracts import Action, Approval, Principal, utcnow
from pais.db import Database


class ApprovalConflict(ValueError):
    """The reviewed action or its current context no longer matches."""


def action_digest(action: Action) -> str:
    body = json.dumps(action.model_dump(), sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(body.encode()).hexdigest()


class EffectStore(Protocol):
    """Downstream contract: immutable payload per tenant/key and durable receipts."""

    def apply(self, principal: Principal, action: Action, digest: str) -> dict[str, Any]: ...

    def receipt(self, principal: Principal, key: str, digest: str) -> dict[str, Any] | None: ...


class DurableEffectStore:
    """A real local downstream system. It does not send or publish outside this app."""

    allowed_tools = frozenset({"record_note", "publish_report"})

    def __init__(self, db_path: str | Path):
        self.db = Database(db_path)
        self.db.initialize("""
            CREATE TABLE IF NOT EXISTS wf_effects (
              tenant_id TEXT NOT NULL, effect_key TEXT NOT NULL, action_hash TEXT NOT NULL,
              body TEXT NOT NULL, receipt TEXT NOT NULL, created_at TEXT NOT NULL,
              PRIMARY KEY(tenant_id, effect_key));
        """)

    def receipt(self, principal: Principal, key: str, digest: str) -> dict[str, Any] | None:
        with self.db.transaction(False) as conn:
            row = conn.execute(
                "SELECT action_hash,receipt FROM wf_effects WHERE tenant_id=? AND effect_key=?",
                (principal.tenant_id, key),
            ).fetchone()
        if row is None:
            return None
        if row["action_hash"] != digest:
            raise ApprovalConflict("Idempotency key was already used for a different action")
        return json.loads(row["receipt"])

    def apply(self, principal: Principal, action: Action, digest: str) -> dict[str, Any]:
        if action.tool not in self.allowed_tools:
            raise PermissionError("Tool is not in the local effect allowlist")
        if action_digest(action) != digest:
            raise ApprovalConflict("Effect payload does not match approved hash")
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT action_hash,receipt FROM wf_effects WHERE tenant_id=? AND effect_key=?",
                (principal.tenant_id, action.idempotency_key),
            ).fetchone()
            if row is not None:
                if row["action_hash"] != digest:
                    raise ApprovalConflict("Idempotency key payload mismatch")
                return json.loads(row["receipt"])
            receipt = {
                "effect_id": hashlib.sha256(
                    f"{principal.tenant_id}:{action.idempotency_key}".encode()
                ).hexdigest(),
                "action_hash": digest,
                "adapter": "durable-local-effect-store",
                "external_delivery": False,
            }
            conn.execute(
                "INSERT INTO wf_effects VALUES(?,?,?,?,?,?)",
                (principal.tenant_id, action.idempotency_key, digest,
                 action.model_dump_json(), json.dumps(receipt), utcnow()),
            )
        return receipt

    def count(self, principal: Principal) -> int:
        with self.db.transaction(False) as conn:
            return int(conn.execute(
                "SELECT count(*) FROM wf_effects WHERE tenant_id=?", (principal.tenant_id,)
            ).fetchone()[0])


class ApprovalGraphState(TypedDict, total=False):
    approval_id: str
    decision: str
    status: str
    receipt: dict[str, Any]


_thread_locks: dict[str, threading.RLock] = {}
_lock_guard = threading.Lock()


@contextlib.contextmanager
def _graph_lock(path: str) -> Iterator[None]:
    """Serialize a graph thread across threads/processes on the supported Unix host."""
    with _lock_guard:
        lock = _thread_locks.setdefault(path, threading.RLock())
    with lock:
        import fcntl

        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class ApprovalService:
    def __init__(
        self,
        db_path: str | Path,
        context_resolver: Callable[[Principal, Action], str] | None = None,
        effect_store: EffectStore | None = None,
        authorizer: Callable[[Principal], Principal] | None = None,
        clock: Callable[[], float] = time.time,
        after_effect: Callable[[], None] | None = None,
    ):
        self.db = Database(db_path)
        self.checkpoint_path = str(db_path) + ".approvals.sqlite"
        self.effects = effect_store or DurableEffectStore(str(db_path) + ".effects.sqlite")
        self.context_resolver = context_resolver
        self.authorizer = authorizer
        self.clock = clock
        self.after_effect = after_effect
        from pais.operations import CapabilityFlags
        self.capability_flags = CapabilityFlags(self.db)
        self.db.initialize("""
            CREATE TABLE IF NOT EXISTS wf_approvals (
              approval_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, requester TEXT NOT NULL,
              reviewer TEXT NOT NULL, action TEXT NOT NULL, action_hash TEXT NOT NULL,
              expires_at TEXT NOT NULL, status TEXT NOT NULL, decision_by TEXT,
              effect_receipt TEXT, created_at TEXT NOT NULL,
              UNIQUE(tenant_id, action_hash));
            CREATE INDEX IF NOT EXISTS wf_approval_tenant ON wf_approvals(tenant_id,status);
            CREATE TABLE IF NOT EXISTS wf_context (
              tenant_id TEXT NOT NULL, context_key TEXT NOT NULL, version TEXT NOT NULL,
              PRIMARY KEY(tenant_id,context_key));
            CREATE TABLE IF NOT EXISTS wf_audit (
              seq INTEGER PRIMARY KEY AUTOINCREMENT, tenant_id TEXT NOT NULL,
              approval_id TEXT NOT NULL, actor TEXT NOT NULL, event TEXT NOT NULL,
              detail TEXT NOT NULL, occurred_at TEXT NOT NULL);
        """)

    @staticmethod
    def _context_key(action: Action) -> str:
        return str(action.arguments.get("context_id", "default"))

    def update_context(self, principal: Principal, context_key: str, version: str) -> None:
        principal.require("writer")
        if not context_key or not version:
            raise ValueError("Context key and version must be nonempty")
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO wf_context VALUES(?,?,?) ON CONFLICT(tenant_id,context_key) "
                "DO UPDATE SET version=excluded.version",
                (principal.tenant_id, context_key, version),
            )

    def _current_context(self, principal: Principal, action: Action) -> str:
        if self.context_resolver:
            return self.context_resolver(principal, action)
        with self.db.transaction(False) as conn:
            row = conn.execute(
                "SELECT version FROM wf_context WHERE tenant_id=? AND context_key=?",
                (principal.tenant_id, self._context_key(action)),
            ).fetchone()
        if row is None:
            raise ApprovalConflict("Current context is unavailable; execution fails closed")
        return str(row["version"])

    @staticmethod
    def _model(row: Any) -> Approval:
        return Approval(
            approval_id=row["approval_id"], tenant_id=row["tenant_id"],
            requester=row["requester"], reviewer=row["reviewer"],
            action=Action.model_validate_json(row["action"]), action_hash=row["action_hash"],
            expires_at=row["expires_at"], status=row["status"],
        )

    @staticmethod
    def _audit(conn: Any, approval: Approval, actor: str, event: str, detail: Any) -> None:
        conn.execute(
            "INSERT INTO wf_audit(tenant_id,approval_id,actor,event,detail,occurred_at) "
            "VALUES(?,?,?,?,?,?)",
            (approval.tenant_id, approval.approval_id, actor, event,
             json.dumps(detail, sort_keys=True), utcnow()),
        )

    def _read(self, conn: Any, principal: Principal, approval_id: str) -> Approval:
        row = conn.execute(
            "SELECT * FROM wf_approvals WHERE tenant_id=? AND approval_id=?",
            (principal.tenant_id, approval_id),
        ).fetchone()
        if row is None:
            raise LookupError("Approval not found")
        result = self._model(row)
        if principal.subject not in {result.requester, result.reviewer} and "admin" not in principal.roles:
            raise PermissionError("Principal cannot access this approval")
        return result

    def get(self, principal: Principal, approval_id: str) -> Approval:
        with self.db.transaction(False) as conn:
            return self._read(conn, principal, approval_id)

    def list(self, principal: Principal, status: str | None = None) -> list[Approval]:
        sql = "SELECT * FROM wf_approvals WHERE tenant_id=?"
        params: list[Any] = [principal.tenant_id]
        if "admin" not in principal.roles:
            sql += " AND (requester=? OR reviewer=?)"
            params.extend([principal.subject, principal.subject])
        if status:
            sql += " AND status=?"
            params.append(status)
        sql += " ORDER BY created_at DESC,approval_id LIMIT 1000"
        with self.db.transaction(False) as conn:
            return [self._model(r) for r in conn.execute(sql, params).fetchall()]

    def request(
        self, principal: Principal, action: Action, reviewer: str, ttl_seconds: int = 900
    ) -> Approval:
        principal.require("writer")
        if action.tool not in DurableEffectStore.allowed_tools:
            raise PermissionError("Action tool is not allowed")
        if not reviewer.strip() or not action.context_version or not action.idempotency_key:
            raise ValueError("Reviewer, context version and idempotency key are required")
        if not isinstance(ttl_seconds, int) or not 1 <= ttl_seconds <= 86400:
            raise ValueError("Approval TTL must be 1..86400 seconds")
        digest = action_digest(action)
        expires = datetime.fromtimestamp(self.clock(), UTC) + timedelta(seconds=ttl_seconds)
        result = Approval(
            tenant_id=principal.tenant_id, requester=principal.subject, reviewer=reviewer,
            action=action, action_hash=digest, expires_at=expires.isoformat(),
        )
        with self.db.transaction() as conn:
            rows = conn.execute(
                "SELECT * FROM wf_approvals WHERE tenant_id=?",
                (principal.tenant_id,),
            ).fetchall()
            for row in rows:
                previous = self._model(row)
                if previous.action.idempotency_key != action.idempotency_key:
                    continue
                if previous.action_hash != digest or previous.reviewer != reviewer:
                    raise ApprovalConflict("Idempotency key is already bound to another review")
                result = previous
                break
            else:
                conn.execute(
                    "INSERT OR IGNORE INTO wf_context VALUES(?,?,?)",
                    (principal.tenant_id, self._context_key(action), action.context_version),
                )
                conn.execute(
                    "INSERT INTO wf_approvals VALUES(?,?,?,?,?,?,?,?,NULL,NULL,?)",
                    (result.approval_id, result.tenant_id, result.requester, result.reviewer,
                     action.model_dump_json(), digest, result.expires_at, "pending", utcnow()),
                )
                self._audit(conn, result, principal.subject, "requested", {"action_hash": digest})
        self._drive(principal, result.approval_id)
        return self.get(principal, result.approval_id)

    def _reviewer(self, principal: Principal, approval: Approval) -> Principal:
        resolved = self.authorizer(principal) if self.authorizer else principal
        if resolved.subject != principal.subject or resolved.tenant_id != approval.tenant_id:
            raise PermissionError("Reviewer identity or tenant changed")
        resolved.require("reviewer")
        if resolved.subject != approval.reviewer:
            raise PermissionError("Only the designated reviewer can decide")
        return resolved

    def decide(
        self, principal: Principal, approval_id: str,
        decision: Literal["approve", "reject", "cancel"],
        expected_action_hash: str, context_version: str,
    ) -> Approval:
        if decision not in {"approve", "reject", "cancel"}:
            raise ValueError("Decision must be approve, reject, or cancel")
        approval = self.get(principal, approval_id)
        if expected_action_hash != approval.action_hash or action_digest(approval.action) != expected_action_hash:
            raise ApprovalConflict("Action changed after the reviewer loaded it")
        if context_version != approval.action.context_version:
            raise ApprovalConflict("Reviewed source version does not match the action")
        if decision == "cancel":
            if principal.subject != approval.requester and "admin" not in principal.roles:
                raise PermissionError("Only requester or tenant admin may cancel")
        else:
            principal = self._reviewer(principal, approval)
        if decision == "approve" and self._current_context(principal, approval.action) != context_version:
            raise ApprovalConflict("Source context changed; a new approval is required")
        expired = False
        with self.db.transaction() as conn:
            approval = self._read(conn, principal, approval_id)
            if expected_action_hash != approval.action_hash:
                raise ApprovalConflict("Concurrent action edit")
            desired = {"approve": "approved", "reject": "rejected", "cancel": "cancelled"}[decision]
            if approval.status in {desired, "executed"}:
                if approval.status == "executed" and decision != "approve":
                    raise ApprovalConflict("An executed action cannot be reversed by a decision")
            elif approval.status != "pending":
                raise ApprovalConflict(f"Approval is already {approval.status}")
            elif datetime.fromisoformat(approval.expires_at).timestamp() <= self.clock():
                conn.execute("UPDATE wf_approvals SET status='expired' WHERE approval_id=?", (approval_id,))
                self._audit(conn, approval, principal.subject, "expired", {})
                expired = True
            else:
                conn.execute(
                    "UPDATE wf_approvals SET status=?,decision_by=? WHERE approval_id=? AND status='pending'",
                    (desired, principal.subject, approval_id),
                )
                self._audit(conn, approval, principal.subject, desired, {"action_hash": expected_action_hash})
        if expired:
            raise ApprovalConflict("Approval expired")
        self._drive(principal, approval_id)
        return self.get(principal, approval_id)

    def edit_and_reapprove(
        self, principal: Principal, approval_id: str, new_action: Action, expected_action_hash: str,
    ) -> Approval:
        previous = self.get(principal, approval_id)
        if new_action.idempotency_key == previous.action.idempotency_key:
            raise ApprovalConflict("An edited action requires a new idempotency key")
        if principal.subject != previous.requester and "admin" not in principal.roles:
            raise PermissionError("Only requester or admin can edit the proposed action")
        self.decide(principal, approval_id, "cancel", expected_action_hash, previous.action.context_version)
        result = self.request(principal, new_action, previous.reviewer)
        with self.db.transaction() as conn:
            self._audit(conn, result, principal.subject, "replaces", {"approval_id": approval_id})
        return result

    def _execute(self, principal: Principal, approval_id: str) -> dict[str, Any]:
        approval = self.get(principal, approval_id)
        principal = self._reviewer(principal, approval)
        if approval.status not in {"approved", "executed"}:
            raise ApprovalConflict("Execution requires an approved exact action")
        if action_digest(approval.action) != approval.action_hash:
            raise ApprovalConflict("Stored action was modified")
        with self.db.transaction() as conn:
            current = self._read(conn, principal, approval_id)
            if current.status not in {"approved", "executed"}:
                raise ApprovalConflict("Decision changed before completion")
            receipt = self.effects.receipt(principal, approval.action.idempotency_key, approval.action_hash)
            if receipt is None:
                self.capability_flags.require_tx(conn, principal, "agent.execute")
                if datetime.fromisoformat(approval.expires_at).timestamp() <= self.clock():
                    raise ApprovalConflict("Approval expired before effect execution")
                if self.context_resolver:
                    version = self.context_resolver(principal, approval.action)
                else:
                    source = conn.execute(
                        "SELECT version FROM wf_context WHERE tenant_id=? AND context_key=?",
                        (principal.tenant_id, self._context_key(approval.action)),
                    ).fetchone()
                    version = source["version"] if source else None
                if version != approval.action.context_version:
                    raise ApprovalConflict("Context changed before execution")
                receipt = self.effects.apply(principal, approval.action, approval.action_hash)
                if self.after_effect:
                    self.after_effect()  # downstream committed; local admission rolls back on a fault
            if current.status != "executed":
                conn.execute(
                    "UPDATE wf_approvals SET status='executed',effect_receipt=? WHERE approval_id=?",
                    (json.dumps(receipt), approval_id),
                )
                self._audit(conn, approval, principal.subject, "executed", receipt)
        return receipt

    def _drive(self, principal: Principal, approval_id: str) -> None:
        from langgraph.checkpoint.sqlite import SqliteSaver
        from langgraph.graph import END, START, StateGraph
        from langgraph.types import Command, interrupt

        self.get(principal, approval_id)  # authorize before any checkpoint lookup
        lock_file = self.checkpoint_path + ".locks/" + approval_id + ".lock"
        with _graph_lock(lock_file), SqliteSaver.from_conn_string(self.checkpoint_path) as saver:
            def review(state: ApprovalGraphState) -> dict[str, Any]:
                item = self.get(principal, state["approval_id"])
                interrupt({"approval_id": item.approval_id, "action_hash": item.action_hash,
                           "action": item.action.model_dump(), "expires_at": item.expires_at})
                item = self.get(principal, state["approval_id"])
                return {"decision": item.status, "status": item.status}

            def effect(state: ApprovalGraphState) -> dict[str, Any]:
                receipt = self._execute(principal, state["approval_id"])
                return {"status": "executed", "receipt": receipt}

            graph = StateGraph(ApprovalGraphState)
            graph.add_node("review", review)
            graph.add_node("effect", effect)
            graph.add_edge(START, "review")
            graph.add_conditional_edges(
                "review", lambda state: "effect" if state["decision"] in {"approved", "executed"} else END,
                {"effect": "effect", END: END},
            )
            graph.add_edge("effect", END)
            compiled = graph.compile(checkpointer=saver)
            config = {"configurable": {"thread_id": f"{principal.tenant_id}:{approval_id}"}}
            current = compiled.get_state(config)
            if not current.values:
                compiled.invoke({"approval_id": approval_id}, config)
                current = compiled.get_state(config)
            item = self.get(principal, approval_id)
            if item.status == "pending":
                return
            if current.next:
                if any(task.interrupts for task in current.tasks):
                    compiled.invoke(Command(resume={"decision_recorded": True}), config)
                else:
                    compiled.invoke(None, config)  # retry an effect node interrupted by a process fault

    def resume(self, principal: Principal, approval_id: str) -> Approval:
        item = self.get(principal, approval_id)
        if item.status in {"approved", "executed"}:
            self._reviewer(principal, item)
        self._drive(principal, approval_id)
        return self.get(principal, approval_id)

    def history(self, principal: Principal, approval_id: str) -> list[dict[str, Any]]:
        self.get(principal, approval_id)
        with self.db.transaction(False) as conn:
            rows = conn.execute(
                "SELECT seq,actor,event,detail,occurred_at FROM wf_audit "
                "WHERE tenant_id=? AND approval_id=? ORDER BY seq",
                (principal.tenant_id, approval_id),
            ).fetchall()
        return [{**dict(r), "detail": json.loads(r["detail"])} for r in rows]


def review_signals(grounding: float, conflicts: list[str], sensitive_action: bool) -> list[str]:
    """Transparent development rule, not a claimed calibrated uncertainty model."""
    if not math.isfinite(grounding) or not 0 <= grounding <= 1:
        raise ValueError("Grounding signal must be a finite proportion")
    reasons = []
    if grounding < 0.85:
        reasons.append("grounding_below_development_threshold")
    if conflicts:
        reasons.append("unresolved_conflicts")
    if sensitive_action:
        reasons.append("policy_requires_human_review")
    return reasons


def demo(db_path: str | Path, profile: str = "fixture") -> dict[str, Any]:
    if profile not in {"fixture", "local"}:
        raise RuntimeError("Connected approval demonstration requires a configured downstream adapter")
    principal = Principal(subject="reviewer-a", tenant_id="tenant-a", roles=["admin"])
    service = ApprovalService(db_path)
    service.capability_flags.set(principal, "agent.execute", True, reason="fixture demo setup")
    key = f"approval-demo-{time.time_ns()}"
    item = service.request(principal, Action(tool="record_note", arguments={"note": "Reviewed locally"},
                          context_version="demo-v1", idempotency_key=key), principal.subject)
    restarted = ApprovalService(db_path)
    done = restarted.decide(principal, item.approval_id, "approve", item.action_hash, "demo-v1")
    restarted.resume(principal, item.approval_id)
    return {"profile": profile, "langgraph_executed": True, "durable_restart": True,
            "status": done.status, "history": restarted.history(principal, item.approval_id),
            "external_delivery": False, "uncertainty_calibration": "unverified"}
