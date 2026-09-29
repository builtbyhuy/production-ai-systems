# P10 — Tenant identity and billing boundaries

**Implemented adapters/policies. Local membership/quota and actual Stripe signature SDK verified. Remote Supabase RLS/users and Stripe test-account reconciliation are unverified.**

## Architecture

packages/pais/tenancy.py separates authentication, active membership, billable application units and provider costs. Fixture tokens are random, stored as hashes, expire, require explicit opt-in and re-read current membership. Each accepted application request consumes integer units in an immediate transaction. Corrections append signed deltas referring to original consumption; database triggers reject ledger mutation.

SupabaseTenantAdapter verifies the user token, resolves membership and uses the user's JWT for database/storage access. It rejects privileged keys. The migration defines tenant/membership/resource/private-storage policies with fixed-search-path membership functions. Queries retain explicit tenant filters.

StripeTestBilling accepts test keys only. Raw webhook signatures run through Stripe 15.6.1. Customer-to-tenant mapping is server-owned. Duplicate events persist; older events are ignored; equal timestamps with differing IDs require reconciliation instead of fabricated ordering.

## Setup and commands

~~~bash
.venv/bin/python -m pais demo 10 --profile fixture --output artifacts/stateful/p10-fixture.json
.venv/bin/python -m pytest tests/test_tenancy.py -q
~~~

For connected acceptance, select a Supabase test project and review/apply [migration.sql](migration.sql). Create two real users and memberships. Supply their JWTs and the public project key. Create a Stripe test customer/subscription and a meter named pais_units; map its customer ID to the tenant. Execute send_usage, reconcile_subscription and reconcile_usage using the test key. Fixture mode provisions no remote accounts and charges nothing. [Evidence](../../artifacts/stateful/p10-fixture.json).

## Acceptance checklist

- [x] Fixture auth, fresh roles, storage-path guard, privileged-key rejection.
- [x] Thirty concurrent requests against quota ten admit ten; other tenant stays at zero.
- [x] Append-only corrections and cross-tenant denial.
- [x] Actual Stripe signature/replay/stale/tied event tests; live mode rejected.
- [x] Concrete Supabase and Stripe metering/reconciliation adapters.
- [ ] Applied remote migration and two real authenticated user isolation drills.
- [ ] Real storage URL and privileged-worker boundary tests.
- [ ] Real Stripe subscription/meter reconciliation.

## Case study and limitations

Six local tests passed. Actual SDK execution exposed and fixed two compatibility differences: Stripe resources require to_dict for dictionary operations; Supabase storage authorization comes from SyncClientOptions headers.

A migration file does not prove deployed RLS. Owners/service-role credentials can bypass policies; workers must preserve scoped identity. Resource-kind fixtures do not establish end-to-end isolation of unrelated external services. Stripe aggregates meter events asynchronously, and idempotency retention/reconciliation still require a real test-account run.

## Interview walkthrough

Trace identity → membership → tenant query → quota ledger. Explain why a tenant header or administrative key cannot grant arbitrary access. Show correction history and same-second webhook ambiguity. Add a resource family to both policy tests and adapter checks.

References: [RLS](https://supabase.com/docs/guides/database/postgres/row-level-security), [get user](https://supabase.com/docs/reference/python/auth-getuser), [webhooks](https://docs.stripe.com/webhooks), [usage API](https://docs.stripe.com/billing/subscriptions/usage-based/recording-usage-api).
