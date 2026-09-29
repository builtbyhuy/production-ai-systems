"""Tenant memberships, append-only billable units, Supabase RLS and Stripe test mode.

Local membership fixtures are a separate evidence profile from real Supabase users.
Client-supplied tenant IDs select an existing membership; they never create one.
"""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pais.contracts import Principal, new_id, utcnow
from pais.db import Database


class QuotaExceeded(RuntimeError):
    pass


class TenantService:
    valid_roles = frozenset({"admin", "writer", "reader", "reviewer"})

    def __init__(self, db_path: str | Path):
        self.db = Database(db_path)
        self.db.initialize("""
            CREATE TABLE IF NOT EXISTS tenant_settings (
              tenant_id TEXT PRIMARY KEY, unit_limit INTEGER NOT NULL CHECK(unit_limit>=0));
            CREATE TABLE IF NOT EXISTS tenant_members (
              tenant_id TEXT NOT NULL, subject TEXT NOT NULL, roles TEXT NOT NULL,
              active INTEGER NOT NULL DEFAULT 1, PRIMARY KEY(tenant_id,subject));
            CREATE TABLE IF NOT EXISTS tenant_tokens (
              token_hash TEXT PRIMARY KEY, subject TEXT NOT NULL, tenant_id TEXT NOT NULL,
              expires_at REAL NOT NULL, revoked INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS tenant_usage (
              event_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, subject TEXT NOT NULL,
              request_id TEXT NOT NULL, period TEXT NOT NULL, kind TEXT NOT NULL,
              units INTEGER NOT NULL, correction_of TEXT REFERENCES tenant_usage(event_id),
              reason TEXT, occurred_at TEXT NOT NULL, UNIQUE(tenant_id,request_id));
            CREATE TRIGGER IF NOT EXISTS tenant_usage_no_update BEFORE UPDATE ON tenant_usage
              BEGIN SELECT RAISE(ABORT,'usage ledger is append-only'); END;
            CREATE TRIGGER IF NOT EXISTS tenant_usage_no_delete BEFORE DELETE ON tenant_usage
              BEGIN SELECT RAISE(ABORT,'usage ledger is append-only'); END;
            CREATE TABLE IF NOT EXISTS tenant_customers (
              tenant_id TEXT PRIMARY KEY, stripe_customer TEXT UNIQUE NOT NULL);
            CREATE TABLE IF NOT EXISTS tenant_subscriptions (
              tenant_id TEXT PRIMARY KEY, subscription_id TEXT NOT NULL, status TEXT NOT NULL,
              last_created INTEGER NOT NULL, last_event_id TEXT NOT NULL,
              needs_reconciliation INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS tenant_stripe_events (
              event_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, event_type TEXT NOT NULL,
              created INTEGER NOT NULL, payload_hash TEXT NOT NULL, outcome TEXT NOT NULL,
              received_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS tenant_meter_receipts (
              event_id TEXT PRIMARY KEY REFERENCES tenant_usage(event_id), tenant_id TEXT NOT NULL,
              stripe_identifier TEXT NOT NULL, sent_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS tenant_audit (
              seq INTEGER PRIMARY KEY AUTOINCREMENT, tenant_id TEXT NOT NULL,
              actor TEXT NOT NULL, event TEXT NOT NULL, detail TEXT NOT NULL, timestamp TEXT NOT NULL);
        """)

    @staticmethod
    def _audit(conn: Any, principal: Principal, event: str, detail: Any) -> None:
        conn.execute("INSERT INTO tenant_audit(tenant_id,actor,event,detail,timestamp) VALUES(?,?,?,?,?)",
                     (principal.tenant_id, principal.subject, event, json.dumps(detail), utcnow()))

    def bootstrap_local_tenant(self, owner: Principal, unit_limit: int = 100) -> None:
        """Explicit fixture/setup operation, deliberately absent from public APIs."""
        owner.require("admin")
        if unit_limit < 0:
            raise ValueError("Unit limit must be nonnegative")
        with self.db.transaction() as conn:
            conn.execute("INSERT INTO tenant_settings VALUES(?,?)", (owner.tenant_id, unit_limit))
            conn.execute("INSERT INTO tenant_members VALUES(?,?,?,1)",
                         (owner.tenant_id, owner.subject, json.dumps(owner.roles)))
            self._audit(conn, owner, "fixture_tenant_bootstrapped", {"unit_limit": unit_limit})

    def reauthorize(self, principal: Principal) -> Principal:
        with self.db.transaction(False) as conn:
            row = conn.execute("SELECT roles,active FROM tenant_members WHERE tenant_id=? AND subject=?",
                               (principal.tenant_id, principal.subject)).fetchone()
        if row is None or not row["active"]:
            raise PermissionError("Active tenant membership is required")
        return Principal(subject=principal.subject, tenant_id=principal.tenant_id, roles=json.loads(row["roles"]))

    def set_member(self, principal: Principal, subject: str, roles: list[str], active: bool = True) -> None:
        principal = self.reauthorize(principal)
        principal.require("admin")
        if not roles or set(roles) - self.valid_roles:
            raise ValueError("Unsupported membership role")
        with self.db.transaction() as conn:
            conn.execute("INSERT INTO tenant_members VALUES(?,?,?,?) ON CONFLICT(tenant_id,subject) "
                         "DO UPDATE SET roles=excluded.roles,active=excluded.active",
                         (principal.tenant_id, subject, json.dumps(sorted(set(roles))), int(active)))
            self._audit(conn, principal, "membership_changed", {"subject": subject, "roles": roles, "active": active})

    def issue_fixture_token(self, principal: Principal, ttl_seconds: int = 3600) -> str:
        principal = self.reauthorize(principal)
        if not 1 <= ttl_seconds <= 86400:
            raise ValueError("Token expiry out of bounds")
        token = "pais_fixture_" + secrets.token_urlsafe(32)
        with self.db.transaction() as conn:
            conn.execute("INSERT INTO tenant_tokens VALUES(?,?,?,?,0)",
                         (hashlib.sha256(token.encode()).hexdigest(), principal.subject,
                          principal.tenant_id, time.time() + ttl_seconds))
        return token

    def authenticate_fixture(self, token: str, *, allow_fixture: bool = False) -> Principal:
        if not allow_fixture:
            raise PermissionError("Local fixture authentication is not enabled")
        with self.db.transaction(False) as conn:
            row = conn.execute("SELECT * FROM tenant_tokens WHERE token_hash=?",
                               (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
        if row is None or row["revoked"] or row["expires_at"] <= time.time():
            raise PermissionError("Invalid or expired fixture token")
        return self.reauthorize(Principal(subject=row["subject"], tenant_id=row["tenant_id"]))

    @staticmethod
    def _period() -> str:
        return datetime.now(UTC).strftime("%Y-%m")

    def consume(self, principal: Principal, request_id: str, units: int = 1) -> dict[str, Any]:
        principal = self.reauthorize(principal)
        principal.require("writer")
        if type(units) is not int or units <= 0:
            raise ValueError("Billable units must be a positive integer")
        period = self._period()
        with self.db.transaction() as conn:
            prior = conn.execute("SELECT * FROM tenant_usage WHERE tenant_id=? AND request_id=?",
                                 (principal.tenant_id, request_id)).fetchone()
            if prior:
                if prior["units"] != units or prior["subject"] != principal.subject or prior["kind"] != "consumption":
                    raise ValueError("Usage request idempotency mismatch")
                return dict(prior)
            limit = conn.execute("SELECT unit_limit FROM tenant_settings WHERE tenant_id=?",
                                 (principal.tenant_id,)).fetchone()
            used = conn.execute("SELECT COALESCE(SUM(units),0) FROM tenant_usage WHERE tenant_id=? AND period=?",
                                (principal.tenant_id, period)).fetchone()[0]
            if limit is None or used + units > limit["unit_limit"]:
                raise QuotaExceeded("Tenant billable-unit quota exceeded")
            event_id = new_id()
            conn.execute("INSERT INTO tenant_usage VALUES(?,?,?,?,?,'consumption',?,NULL,NULL,?)",
                         (event_id, principal.tenant_id, principal.subject, request_id, period, units, utcnow()))
            return dict(conn.execute("SELECT * FROM tenant_usage WHERE event_id=?", (event_id,)).fetchone())

    def correct(self, principal: Principal, event_id: str, delta: int, request_id: str, reason: str) -> dict[str, Any]:
        principal = self.reauthorize(principal)
        principal.require("admin")
        if type(delta) is not int or delta == 0 or len(reason.strip()) < 8:
            raise ValueError("Correction needs nonzero integer delta and a useful reason")
        with self.db.transaction() as conn:
            original = conn.execute("SELECT * FROM tenant_usage WHERE tenant_id=? AND event_id=? AND kind='consumption'",
                                    (principal.tenant_id, event_id)).fetchone()
            if original is None:
                raise LookupError("Original usage event not found")
            prior = conn.execute("SELECT * FROM tenant_usage WHERE tenant_id=? AND request_id=?",
                                 (principal.tenant_id, request_id)).fetchone()
            if prior:
                if prior["correction_of"] != event_id or prior["units"] != delta or prior["reason"] != reason:
                    raise ValueError("Correction idempotency mismatch")
                return dict(prior)
            corrected = original["units"] + conn.execute(
                "SELECT COALESCE(SUM(units),0) FROM tenant_usage WHERE tenant_id=? AND correction_of=?",
                (principal.tenant_id, event_id)).fetchone()[0]
            if corrected + delta < 0:
                raise ValueError("Correction would make the original event negative")
            if delta > 0:
                total = conn.execute("SELECT COALESCE(SUM(units),0) FROM tenant_usage WHERE tenant_id=? AND period=?",
                                     (principal.tenant_id, original["period"])).fetchone()[0]
                limit = conn.execute("SELECT unit_limit FROM tenant_settings WHERE tenant_id=?",
                                     (principal.tenant_id,)).fetchone()["unit_limit"]
                if total + delta > limit:
                    raise QuotaExceeded("Positive correction exceeds tenant quota")
            new_event = new_id()
            conn.execute("INSERT INTO tenant_usage VALUES(?,?,?,?,?,'correction',?,?,?,?)",
                         (new_event, principal.tenant_id, principal.subject, request_id, original["period"],
                          delta, event_id, reason, utcnow()))
            self._audit(conn, principal, "usage_corrected", {"original": event_id, "delta": delta})
            return dict(conn.execute("SELECT * FROM tenant_usage WHERE event_id=?", (new_event,)).fetchone())

    def usage(self, principal: Principal, period: str | None = None) -> dict[str, Any]:
        principal = self.reauthorize(principal)
        with self.db.transaction(False) as conn:
            rows = conn.execute("SELECT * FROM tenant_usage WHERE tenant_id=? AND period=? ORDER BY occurred_at,event_id",
                                (principal.tenant_id, period or self._period())).fetchall()
        return {"unit": "accepted_application_request", "provider_cost_is_separate": True,
                "units": sum(row["units"] for row in rows), "events": [dict(row) for row in rows]}

    def map_stripe_customer(self, principal: Principal, customer_id: str) -> None:
        principal = self.reauthorize(principal)
        principal.require("admin")
        if not customer_id.startswith("cus_"):
            raise ValueError("Invalid Stripe customer ID")
        with self.db.transaction() as conn:
            prior = conn.execute("SELECT stripe_customer FROM tenant_customers WHERE tenant_id=?",
                                 (principal.tenant_id,)).fetchone()
            if prior and prior["stripe_customer"] != customer_id:
                raise ValueError("Customer remapping requires an explicit migration")
            conn.execute("INSERT OR IGNORE INTO tenant_customers VALUES(?,?)", (principal.tenant_id, customer_id))

    def stripe_webhook(self, payload: bytes, signature: str, webhook_secret: str) -> dict[str, Any]:
        import stripe
        if not webhook_secret.startswith("whsec_"):
            raise ValueError("A Stripe webhook endpoint secret is required")
        event = stripe.Webhook.construct_event(payload, signature, webhook_secret, tolerance=300).to_dict()
        if event.get("livemode") is not False:
            raise PermissionError("This adapter only accepts Stripe test-mode events")
        digest = hashlib.sha256(payload).hexdigest()
        event_id, kind, created = str(event["id"]), str(event["type"]), int(event["created"])
        obj = event["data"]["object"]
        supported = {"customer.subscription.created", "customer.subscription.updated", "customer.subscription.deleted"}
        if kind not in supported:
            return {"event_id": event_id, "outcome": "ignored_unsupported_type"}
        customer = obj.get("customer")
        if isinstance(customer, dict):
            customer = customer.get("id")
        with self.db.transaction() as conn:
            prior = conn.execute("SELECT * FROM tenant_stripe_events WHERE event_id=?", (event_id,)).fetchone()
            if prior:
                if prior["payload_hash"] != digest:
                    raise ValueError("Stripe event ID reused with different content")
                return {"event_id": event_id, "outcome": "duplicate", "prior_outcome": prior["outcome"]}
            binding = conn.execute("SELECT tenant_id FROM tenant_customers WHERE stripe_customer=?", (customer,)).fetchone()
            if binding is None:
                raise PermissionError("Stripe customer is not mapped to a tenant")
            tenant = binding["tenant_id"]
            previous = conn.execute("SELECT * FROM tenant_subscriptions WHERE tenant_id=?", (tenant,)).fetchone()
            status = "canceled" if kind.endswith("deleted") else str(obj["status"])
            if previous and created < previous["last_created"]:
                outcome = "stale_ignored"
            elif previous and created == previous["last_created"] and previous["last_event_id"] != event_id:
                # Stripe timestamps do not provide a total event order. Do not invent one.
                outcome = "needs_reconciliation"
                conn.execute("UPDATE tenant_subscriptions SET needs_reconciliation=1 WHERE tenant_id=?", (tenant,))
            else:
                outcome = "applied"
                conn.execute("INSERT INTO tenant_subscriptions VALUES(?,?,?,?,?,0) ON CONFLICT(tenant_id) DO UPDATE "
                             "SET subscription_id=excluded.subscription_id,status=excluded.status,last_created=excluded.last_created,"
                             "last_event_id=excluded.last_event_id,needs_reconciliation=0",
                             (tenant, str(obj["id"]), status, created, event_id))
            conn.execute("INSERT INTO tenant_stripe_events VALUES(?,?,?,?,?,?,?)",
                         (event_id, tenant, kind, created, digest, outcome, utcnow()))
        return {"event_id": event_id, "outcome": outcome}

    def subscription(self, principal: Principal) -> dict[str, Any] | None:
        principal = self.reauthorize(principal)
        with self.db.transaction(False) as conn:
            row = conn.execute("SELECT * FROM tenant_subscriptions WHERE tenant_id=?", (principal.tenant_id,)).fetchone()
        return dict(row) if row else None


class SupabaseTenantAdapter:
    """Uses an anon/publishable key plus each user's verified access token, never service-role auth."""
    def __init__(self, url: str, public_key: str):
        if not url.startswith("https://") or not public_key:
            raise ValueError("Supabase HTTPS URL and public key are required")
        if public_key.startswith("sb_secret_"):
            raise PermissionError("A Supabase service key may bypass RLS; use a publishable key")
        if public_key.count(".") == 2:
            try:
                claims = json.loads(base64.urlsafe_b64decode(public_key.split(".")[1] + "=="))
            except (ValueError, TypeError) as exc:
                raise ValueError("Invalid legacy public key") from exc
            if claims.get("role") != "anon":
                raise PermissionError("Only anon legacy keys are allowed")
        self.url, self.public_key = url, public_key

    def _client(self, access_token: str) -> Any:
        from supabase import create_client
        from supabase.lib.client_options import SyncClientOptions
        client = create_client(self.url, self.public_key, options=SyncClientOptions(
            headers={"Authorization": "Bearer " + access_token},
            auto_refresh_token=False, persist_session=False,
        ))
        client.postgrest.auth(access_token)
        return client

    def resolve(self, access_token: str, selected_tenant: str) -> Principal:
        client = self._client(access_token)
        user = client.auth.get_user(access_token).user
        if user is None:
            raise PermissionError("Supabase authentication failed")
        rows = client.table("tenant_members").select("tenant_id,role").eq("tenant_id", selected_tenant).eq("user_id", user.id).execute().data
        if len(rows) != 1:
            raise PermissionError("Authenticated user is not a member of the selected tenant")
        return Principal(subject=user.id, tenant_id=rows[0]["tenant_id"], roles=[rows[0]["role"]])

    def get_resource(self, access_token: str, selected_tenant: str, resource_id: str) -> dict[str, Any]:
        principal = self.resolve(access_token, selected_tenant)
        result = self._client(access_token).table("tenant_resources").select("*").eq("tenant_id", principal.tenant_id).eq("id", resource_id).execute().data
        if len(result) != 1:
            raise LookupError("Resource not found")
        return result[0]

    def put_resource(self, access_token: str, selected_tenant: str, resource_id: str,
                     kind: str, data: dict[str, Any]) -> dict[str, Any]:
        principal = self.resolve(access_token, selected_tenant)
        principal.require("writer")
        result = self._client(access_token).table("tenant_resources").upsert({
            "id": resource_id, "tenant_id": principal.tenant_id, "kind": kind, "data": data,
        }, on_conflict="tenant_id,id").execute().data
        if len(result) != 1:
            raise RuntimeError("Supabase resource write returned no row")
        return result[0]

    def signed_storage_url(self, access_token: str, selected_tenant: str, object_path: str) -> dict[str, Any]:
        principal = self.resolve(access_token, selected_tenant)
        parts = object_path.split("/")
        if len(parts) < 2 or parts[0] != principal.tenant_id or any(x in {"", ".", ".."} for x in parts):
            raise PermissionError("Storage object path is outside the current tenant")
        return self._client(access_token).storage.from_("tenant-documents").create_signed_url(object_path, 60)


class StripeTestBilling:
    def __init__(self, tenants: TenantService, api_key: str, event_name: str = "pais_units"):
        import stripe
        if not api_key.startswith(("sk_test_", "rk_test_")):
            raise PermissionError("Only Stripe test-mode keys are allowed")
        self.tenants, self.event_name = tenants, event_name
        self.client = stripe.StripeClient(api_key, max_network_retries=2)

    def send_usage(self, principal: Principal, event_id: str) -> dict[str, Any]:
        principal = self.tenants.reauthorize(principal)
        principal.require("admin")
        with self.tenants.db.transaction(False) as conn:
            row = conn.execute("SELECT u.*,c.stripe_customer FROM tenant_usage u JOIN tenant_customers c "
                               "ON u.tenant_id=c.tenant_id WHERE u.tenant_id=? AND u.event_id=?",
                               (principal.tenant_id, event_id)).fetchone()
            if row is None:
                raise LookupError("Mapped usage event not found")
            prior = conn.execute("SELECT * FROM tenant_meter_receipts WHERE tenant_id=? AND event_id=?",
                                 (principal.tenant_id, event_id)).fetchone()
            if prior:
                return dict(prior)
        timestamp = int(datetime.fromisoformat(row["occurred_at"]).timestamp())
        # Identifier and transport idempotency key survive a crash before receipt persistence.
        remote = self.client.v1.billing.meter_events.create({
            "event_name": self.event_name, "identifier": event_id, "timestamp": timestamp,
            "payload": {"stripe_customer_id": row["stripe_customer"], "value": str(row["units"])},
        }, options={"idempotency_key": f"pais-meter-{event_id}"})
        identifier = str(remote.identifier)
        with self.tenants.db.transaction() as conn:
            conn.execute("INSERT OR IGNORE INTO tenant_meter_receipts VALUES(?,?,?,?)",
                         (event_id, principal.tenant_id, identifier, utcnow()))
        return {"event_id": event_id, "stripe_identifier": identifier, "integration": "Stripe test mode"}

    def reconcile_subscription(self, principal: Principal) -> dict[str, Any]:
        principal = self.tenants.reauthorize(principal)
        principal.require("admin")
        subscription = self.tenants.subscription(principal)
        if subscription is None:
            raise LookupError("Subscription not found")
        remote = self.client.v1.subscriptions.retrieve(subscription["subscription_id"])
        if remote.livemode:
            raise PermissionError("Received a live-mode subscription")
        with self.tenants.db.transaction() as conn:
            mapped = conn.execute("SELECT stripe_customer FROM tenant_customers WHERE tenant_id=?",
                                  (principal.tenant_id,)).fetchone()
            customer = remote.customer.id if hasattr(remote.customer, "id") else remote.customer
            if mapped is None or customer != mapped["stripe_customer"]:
                raise PermissionError("Remote subscription customer is outside tenant mapping")
            conn.execute("UPDATE tenant_subscriptions SET status=?,needs_reconciliation=0 WHERE tenant_id=?",
                         (remote.status, principal.tenant_id))
            self.tenants._audit(conn, principal, "stripe_reconciled", {"subscription_id": remote.id})
        return self.tenants.subscription(principal) or {}

    def reconcile_usage(self, principal: Principal, meter_id: str, start: int, end: int) -> dict[str, Any]:
        principal = self.tenants.reauthorize(principal)
        principal.require("admin")
        if end <= start:
            raise ValueError("Reconciliation interval must be nonempty")
        with self.tenants.db.transaction(False) as conn:
            customer = conn.execute("SELECT stripe_customer FROM tenant_customers WHERE tenant_id=?",
                                   (principal.tenant_id,)).fetchone()
            rows = conn.execute("SELECT units,occurred_at FROM tenant_usage WHERE tenant_id=?",
                                (principal.tenant_id,)).fetchall()
        if customer is None:
            raise LookupError("Tenant Stripe customer is not mapped")
        local = sum(row["units"] for row in rows if start <= datetime.fromisoformat(row["occurred_at"]).timestamp() < end)
        remote = self.client.v1.billing.meters.event_summaries.list(meter_id, params={
            "customer": customer["stripe_customer"], "start_time": start, "end_time": end,
        })
        observed = sum(float(item.aggregated_value) for item in remote.auto_paging_iter())
        return {"local_units": local, "stripe_units": observed, "difference": observed - local,
                "matches": observed == local, "aggregation_may_lag": True}


def demo(db_path: str | Path, profile: str = "fixture") -> dict[str, Any]:
    if profile != "fixture":
        raise RuntimeError("Connected tenancy requires two Supabase user tokens, applied RLS migration, and Stripe test credentials")
    service = TenantService(db_path)
    suffix = new_id()[:8]
    principals = [Principal(subject=f"owner-{x}", tenant_id=f"tenant-{x}-{suffix}", roles=["admin"]) for x in ("a", "b")]
    for principal in principals:
        service.bootstrap_local_tenant(principal, unit_limit=2)
    first = service.consume(principals[0], "req-1")
    service.consume(principals[0], "req-2")
    quota_blocked = False
    try:
        service.consume(principals[0], "req-3")
    except QuotaExceeded:
        quota_blocked = True
    service.correct(principals[0], first["event_id"], -1, "correction-1", "duplicate business request refunded")
    return {"profile": profile, "quota_blocked": quota_blocked, "tenant_a_units": service.usage(principals[0])["units"],
            "tenant_b_units": service.usage(principals[1])["units"], "supabase_authenticated_users": "unverified",
            "stripe_test_mode_reconciliation": "unverified", "billable_unit": "accepted_application_request"}
