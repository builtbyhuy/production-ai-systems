# Interview walkthrough

Start at the API's bearer resolver. Explain why a valid tenant-B UUID is not evidence that
tenant-A may access it. Demonstrate the fixture-auth startup flag and then disable it while
reusing the same database. Show that the old demonstration tokens stop working.

Trace an admission through `SharedLimiter.acquire`. Both tenant and principal token buckets
and both concurrency checks run in one transaction. Demonstrate a lease renewal and expiry.
Explain why an expired lease requires the worker to stop or deny delivery, not continue under
an assumption that it still owns capacity.

Run the actual Guardrails project tests. Change the custom output validator to add a specific
prohibited token format and add a focused benign/attack pair. Keep the framework in the path
and preserve the explicit fail-closed behavior. Do not claim regex coverage for all secrets.

Read `_PinnedHTTPSConnection.connect`. It connects to an already validated numeric IP while
keeping the original hostname for certificate validation. Explain DNS rebinding and why checking
the URL before calling a normal HTTP client is insufficient. Show that redirects are checked again.

Finish at `SandboxRunner.preflight`. Be able to state filesystem, credential, network, privilege,
CPU, memory, PID, output and wall-time boundaries. Explain which are container-runtime controls,
which are host supervision, and which are unverified on the current machine. A subprocess is
only the Docker control client here; user code executes exclusively inside a verified boundary.
