# P06 — Enforced identity, admission, validation and execution boundaries

**Implementation:** server-side credentials, Pydantic argument schemas, Guardrails AI enforcement,
content protection, shared rate/concurrency limits, SSRF controls, and a fail-closed execution
adapter are implemented. **Verified:** custom rules, real Guardrails AI 0.6.8, concurrency and
tenant/tool denial. **Incomplete:** real container file/network/resource-denial acceptance.

The current frozen environment uses Guardrails AI **0.11.0**, LangChain Core **1.6.6**
and LiteLLM **1.103.1**. Guardrails 0.6.8 restricted LangChain Core to `<0.4`, which
excluded the security fix in 1.2.22. The security update preserves the same three
real-framework validation/rejection/failure tests; all three passed on macOS/ARM.
The 0.6.8 result above remains the historical baseline. See the current CI run
for Linux verification; an application test pass does not clear the whole repository's
dependency gate.

## Architecture and threat model

Bearer credentials resolve into `Principal` on the server. The client cannot authorize a tenant
by supplying a header, tool argument, document ID or recalled text. Opaque credentials persist
only as hashes. Demonstration tokens require explicit fixture startup configuration and are
rejected after that flag is disabled, even when the same database is reused.

`SharedLimiter` atomically evaluates principal and tenant token buckets plus concurrency leases.
Different API workers share one SQLite database. Denials consistently carry HTTP 429 semantics
and a positive `Retry-After`. Workers renew their leases; a crash eventually releases concurrency
through expiry. This is a single-host, shared-filesystem design, not a multi-region lock service.

| Untrusted surface | Enforced boundary |
|---|---|
| Input, PDFs, retrieval, memory, tool results | Remain data; injection-risk checks cannot grant permissions |
| Tool name and arguments | Static allowlist, current role check, strict Pydantic schema, no identity arguments |
| Generated text and citation strings | Entire protected response validated before streaming; PII redacted |
| Outbound URL | Exact host allowlist, HTTPS 443, all resolved addresses global, numeric-IP socket pinning and original-host TLS verification |
| Redirects and response bodies | Revalidate/re-pin each redirect, bounded hops/body/network time, no environment proxies or credentials |
| Execution source | Disabled until required rootless Docker, cgroup, seccomp and image checks pass |

The direct Python API is in [security.py](../../packages/pais/security.py); execution is in
[sandbox.py](../../packages/pais/sandbox.py). API middleware buffers the full response before
protecting text. This costs first-display latency. The system reports that delay separately
from provider time-to-first-token instead of claiming unbuffered token streaming.

## Real Guardrails enforcement

The framework uses a project-specific secret-material validator with `on_fail="exception"`.
It is in the enforced output path. Its failure, timeout or malformed result prevents delivery.
Pydantic validates tool schemas outside the model. Custom PII patterns run after framework
validation. Automatic reasks and Guardrails anonymous metrics are disabled.

The dependency environment is isolated from the API. The core API can call a trusted worker
with a fixed interpreter and module path; text crosses that boundary only as JSON on stdin.
This dependency worker does not execute user Python and is not advertised as an execution sandbox.

```bash
uv sync --frozen --project projects/06-security-guardrails --group dev
PYTHONPATH=packages projects/06-security-guardrails/.venv/bin/python -m pytest \
  projects/06-security-guardrails/test_guardrails_real.py -q
PAIS_GUARDRAILS_PYTHON="$PWD/projects/06-security-guardrails/.venv/bin/python" \
  .venv/bin/pais demo 06 --profile local --output artifacts/p06-guardrails-real.json
.venv/bin/python -m pytest tests/test_security.py tests/test_sandbox.py -q
```

In real API profiles, `PAIS_GUARDRAILS_PYTHON` must point to the isolated environment or Guardrails
must be installed directly in a compatible API environment. Missing required validation is a
503 failure, not a fallback to custom-only validation.

The repository's `infra/Dockerfile.api` installs this second frozen environment separately from
the core API dependencies and sets `PAIS_GUARDRAILS_PYTHON` to its interpreter. The image's local
profile therefore reaches the same required validation path at startup. This is a reviewed build
configuration; the actual worker bridge was executed locally, while building and running that
container still requires the deployment prerequisites described in P11.

## Measured behavior and limits

The twelve-case risk corpus produced **5 true positives, 2 missed attacks, 1 benign false
positive, 4 true negatives**. The missed cases include indirect and spaced instructions. A
benign request quoting a dangerous phrase was flagged. These are disclosed observations,
not a broad security accuracy estimate. The PII patterns cover selected email, phone and
identifier formats; names, addresses, multilingual entities and creative encodings remain gaps.

The concurrent test admitted three of twenty-four requests at a concurrency cap of three.
Real Guardrails tests validate a benign output, reject synthetic secret material, and prove a
validator failure does not return protected text. The isolated framework emitted upstream
deprecation warnings; they did not change validation results.

## Execution prerequisites and acceptance

`SandboxRunner()` is disabled by default. Enabling it also requires a local Unix-socket rootless
Docker daemon, Linux, cgroup v2, memory/CPU/PID limit support, seccomp and an audited local Python
image addressed by digest. The runner uses no host mounts, no network, a read-only root,
unprivileged UID, dropped capabilities, no-new-privileges, bounded tmpfs, CPU/memory/process/wall
limits and bounded output. It never pulls an image automatically.

After the operator provisions that boundary and sets the audited image digest and Unix endpoint,
the exact acceptance command is:

```bash
.venv/bin/pais evidence --profile deployment --output artifacts/p06-sandbox-run.json -- \
  .venv/bin/python projects/06-security-guardrails/sandbox_drill.py --enabled \
  --image "${PAIS_SANDBOX_IMAGE:?Set the audited local image digest}" \
  --endpoint "${PAIS_SANDBOX_ENDPOINT:?Set the rootless Docker Unix endpoint}" \
  --output artifacts/p06-sandbox/report.json
```

Without `--enabled`, the drill exits 2 and reports zero executed submissions. A missing runtime,
an unverified limit, or a non-digest image also blocks execution.

The current host's actual Bubblewrap namespace probe failed with `NETLINK_ROUTE socket:
Operation not permitted`; no acceptable execution boundary was established. Ordinary subprocesses
and temporary directories are deliberately unavailable as substitutes. Containers share the host
kernel; hostile public submissions should use a dedicated VM or stronger isolation.

- [x] Framework enforcement, PII handling and failure-before-delivery behavior.
- [x] Server credential, cross-tenant and allowlisted-tool permission checks.
- [x] Shared rate/burst/concurrency admission and Retry-After behavior.
- [x] SSRF policy, DNS-pinned HTTPS adapter, private/metadata-address rejection tests.
- [x] Missing sandbox disables execution before any host submission execution.
- [ ] Real sandbox drill: denied host file/network access, memory/PID/CPU/time/output limits.
- [ ] Adversarial coverage beyond this disclosed corpus and independent security review.

See [case study](case-study.md), [walkthrough](interview.md), and [sandbox drill](sandbox_drill.py).
Official references: [Guardrails API](https://guardrailsai.com/guardrails/docs/api_reference_markdown/guards),
[Docker rootless mode](https://docs.docker.com/engine/security/rootless/),
[Docker seccomp](https://docs.docker.com/engine/security/seccomp/), consulted 2026-09-29.
