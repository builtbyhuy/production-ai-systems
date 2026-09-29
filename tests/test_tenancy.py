import hashlib
import hmac
import json
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from pais.contracts import Principal
from pais.tenancy import QuotaExceeded, StripeTestBilling, SupabaseTenantAdapter, TenantService


@pytest.fixture
def setup(tmp_path):
    service = TenantService(tmp_path / "tenants.db")
    a = Principal(subject="owner-a", tenant_id="tenant-a", roles=["admin"])
    b = Principal(subject="owner-b", tenant_id="tenant-b", roles=["admin"])
    service.bootstrap_local_tenant(a, unit_limit=10)
    service.bootstrap_local_tenant(b, unit_limit=10)
    return service, a, b


def signed_event(event_id="evt_1", created=100, status="active", customer="cus_a", live=False):
    event = {"id": event_id, "object": "event", "type": "customer.subscription.updated", "created": created,
             "livemode": live, "data": {"object": {"id": "sub_fixture", "object": "subscription",
                       "customer": customer, "status": status}}}
    body = json.dumps(event).encode()
    timestamp = int(time.time())
    signature = hmac.new(b"whsec_fixture", str(timestamp).encode() + b"." + body, hashlib.sha256).hexdigest()
    return body, f"t={timestamp},v1={signature}"


def test_fixture_authentication_requires_optin_and_fresh_membership(setup):
    service, a, _b = setup
    token = service.issue_fixture_token(a)
    with pytest.raises(PermissionError):
        service.authenticate_fixture(token)
    assert service.authenticate_fixture(token, allow_fixture=True).tenant_id == a.tenant_id
    service.set_member(a, a.subject, ["reader"])
    assert service.authenticate_fixture(token, allow_fixture=True).roles == ["reader"]
    with pytest.raises(PermissionError):
        service.consume(a, "request-after-demotion")


def test_atomic_quota_and_idempotency_under_concurrency(setup):
    service, a, b = setup
    def consume(i):
        try:
            service.consume(a, f"req-{i}")
            return True
        except QuotaExceeded:
            return False
    with ThreadPoolExecutor(8) as pool:
        accepted = list(pool.map(consume, range(30)))
    assert sum(accepted) == 10
    assert service.usage(a)["units"] == 10
    assert service.usage(b)["units"] == 0
    for event in service.usage(a)["events"]:
        service.consume(a, event["request_id"])
    assert service.usage(a)["units"] == 10


def test_corrections_append_ledger_and_cannot_cross_tenants(setup):
    service, a, b = setup
    original = service.consume(a, "req", units=4)
    correction = service.correct(a, original["event_id"], -2, "correct", "partial request cancellation")
    assert correction["kind"] == "correction"
    assert service.usage(a)["units"] == 2
    assert len(service.usage(a)["events"]) == 2
    with pytest.raises(LookupError):
        service.correct(b, original["event_id"], -1, "theft", "cross tenant correction")
    with pytest.raises(ValueError, match="negative"):
        service.correct(a, original["event_id"], -3, "over-refund", "invalid excessive refund")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"), service.db.transaction() as conn:
        conn.execute("UPDATE tenant_usage SET units=0 WHERE event_id=?", (original["event_id"],))


def test_real_stripe_signature_replay_stale_and_tied_events(setup):
    service, a, b = setup
    service.map_stripe_customer(a, "cus_a")
    body, signature = signed_event()
    assert service.stripe_webhook(body, signature, "whsec_fixture")["outcome"] == "applied"
    assert service.stripe_webhook(body, signature, "whsec_fixture")["outcome"] == "duplicate"
    older, older_sig = signed_event("evt_old", 99, "canceled")
    assert service.stripe_webhook(older, older_sig, "whsec_fixture")["outcome"] == "stale_ignored"
    assert service.subscription(a)["status"] == "active"
    tied, tied_sig = signed_event("evt_tied", 100, "past_due")
    assert service.stripe_webhook(tied, tied_sig, "whsec_fixture")["outcome"] == "needs_reconciliation"
    assert service.subscription(a)["needs_reconciliation"] == 1
    assert service.subscription(b) is None
    newer, newer_sig = signed_event("evt_new", 101, "past_due")
    service.stripe_webhook(newer, newer_sig, "whsec_fixture")
    assert service.subscription(a)["status"] == "past_due"


def test_webhook_wrong_signature_customer_live_mode_and_event_mutation(setup):
    import stripe
    service, a, _b = setup
    service.map_stripe_customer(a, "cus_a")
    body, signature = signed_event()
    with pytest.raises(stripe.SignatureVerificationError):
        service.stripe_webhook(body + b" ", signature, "whsec_fixture")
    unknown, unknown_sig = signed_event(customer="cus_unknown")
    with pytest.raises(PermissionError, match="mapped"):
        service.stripe_webhook(unknown, unknown_sig, "whsec_fixture")
    live, live_sig = signed_event(live=True)
    with pytest.raises(PermissionError, match="test-mode"):
        service.stripe_webhook(live, live_sig, "whsec_fixture")
    service.stripe_webhook(body, signature, "whsec_fixture")
    changed, changed_sig = signed_event(status="past_due")
    with pytest.raises(ValueError, match="different content"):
        service.stripe_webhook(changed, changed_sig, "whsec_fixture")


def test_real_sdk_adapters_reject_privileged_or_live_keys(setup):
    service, _a, _b = setup
    with pytest.raises(PermissionError, match="service key"):
        SupabaseTenantAdapter("https://fixture.supabase.co", "sb_secret_fixture")
    with pytest.raises(PermissionError, match="test-mode"):
        StripeTestBilling(service, "sk_live_fixture")
    adapter = SupabaseTenantAdapter("https://fixture.supabase.co", "sb_publishable_fixture")
    assert adapter._client("user-fixture-token").postgrest is not None
