# Case study — A timeout is an accounting event

The failure worth defending against was not a wrong model choice. It was admitting concurrent
calls from an in-memory balance, then releasing every reservation after a timeout. That design
can both overspend at admission and hide spending that happened remotely.

The implementation uses `BEGIN IMMEDIATE` and a shared SQLite file. Each attempt adds one hold;
the admission query includes all held and accounted amounts for that tenant and the parent
request. A cancellation stops waiting and propagates cancellation to a cooperative provider,
but the ledger retains the hold. Only a trusted provider adapter's definite no-charge outcome,
or an auditable reconciliation, can remove that uncertainty.

The fault drill produced three distinct attempts before successful fallback. The first two
were explicit fixture no-charge failures. A separate cancellation produced one unknown hold.
The concurrency drill admitted exactly three of twenty-four contenders against a three-call
budget. Unit tests repeat this across separate ledger instances and verify state after restart.
These results establish local accounting behavior; they do not establish external billing
accuracy, a universal provider token bound, or a security boundary against someone who can edit
the underlying database file.

Alternatives rejected: relying on LiteLLM's internal retry loop would hide attempt boundaries;
floating-point counters would invite rounding errors; automatically expiring uncertain holds
would invent knowledge about a remote outcome. SQLite is a useful single-host implementation
with explicit lock contention. A multi-host service should port the transaction contract to a
shared transactional database, preserve event identities, and rerun concurrency tests.

Quality and economics are kept separate. The twelve-task comparison measures actual local
strings only in the local profile. A fixture provider never sees the answer key and receives
no quality score. Applying illustrative cloud prices to those responses would describe a
simulation. Neither that simulation nor a zero-rate local run is evidence of paid-model savings.

The actual local comparison made this separation useful. Always-cheap passed 4/12 exact-match
cases at 0.801 seconds mean latency; always-expensive passed 6/12 at 2.084 seconds; routing passed
4/12 at 1.054 seconds. Each policy made twelve real LiteLLM/Ollama calls without provider errors.
Routing overhead averaged 2.746 ms for the routed policy, but its selected models did not improve
this workload's measured quality. The result supports revisiting the policy using a separate
development set before claiming a benefit. It does not justify changing the test's expected
answers or declaring savings from a local-zero rate card. Full evidence is retained in
`artifacts/p02-router-local.json`.
