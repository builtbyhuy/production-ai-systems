# P14 — Bounded inference gateway and vLLM profiles

This project provides a bounded streaming gateway, a measured HTTP load harness, and explicit
vLLM hardware profiles. Admission and HTTP contract tests have passed. An isolated CPU vLLM
environment was installed, and an actual server launch failed before readiness because this
execution host denies the Unix-domain sockets required by the runtime's ZeroMQ IPC path.
**Actual serving acceptance is BLOCKED. No successful vLLM generation, container deployment,
cluster recovery, or accelerator performance result is claimed.**

| Component | Current state |
| --- | --- |
| Admission controller and gateway | Implemented; mocked HTTP/async contract tests passed |
| Workload measurement harness | Implemented; not run against a verified vLLM server |
| CPU vLLM dependencies | Installed in a separate scratch environment; package metadata inspected |
| CPU model serving | BLOCKED: actual launch exited 1 before readiness; final prerequisite check exits 2 without starting a server |
| CUDA functional/deployment profiles | JSON profiles prepared; hardware/model/digest provisioning incomplete |
| Kubernetes inference workload | CPU template prepared and YAML parsed; schema/cluster validation NOT RUN |
| Batching/cache/quantization performance experiments | NOT RUN |
| Root project-14 `demo()` entrypoint | Implemented; fixture admission demonstration passed |

See [acceptance](ACCEPTANCE.md), [case study](CASE_STUDY.md),
[interview walkthrough](INTERVIEW.md), and the [evidence index](EVIDENCE.json).
Update these states only with new executed evidence.

## Problem and scope

A model server can be healthy while callers overwhelm its queue or receive incomplete streams.
The gateway places explicit limits ahead of generation, checks the true tokenized context size,
waits for a real warmup response, and releases its admission reservation when streaming ends.
Backend addresses are operator configuration; clients cannot select arbitrary destinations.

This is an internal gateway with separately provisioned gateway and upstream credentials. It
does not replace the copilot API's tenant authentication or authorization. Its current control
limits are per gateway process. The documented launch uses one worker; multiple gateway
processes would multiply these limits and require a separate global admission design.

## Architecture

`packages/pais/inference.py` contains four main pieces:

1. `VLLMProfile` describes the exact backend, runtime version, model identity, context and batch
   limits, caching settings, and declared resource requirements. Its `prerequisites()` method
   reports missing runtime/model/cluster inputs without silently downloading them.
2. `AdmissionController` bounds active requests and waiting requests. Queue overflow, timeout,
   and draining are explicit rejections. A cancelled waiter returns its reservation.
3. `create_gateway_app()` checks configured backends and performs a small generation warmup
   before marking one ready. It selects a warmed backend, invokes its tokenizer, rejects a
   context overflow, and proxies the completion stream. It does not restart a failed stream
   from another backend after content has already reached the client.
4. `load_test()` submits a declared prompt workload and records wire timing, actual usage,
   response status, cancellation, and backend assignment when the gateway supplies that header.

The readiness endpoint reports whether a warmed backend is available and whether the gateway
is draining. The separate health endpoint reports process liveness. A periodic health loop
removes unhealthy backends and requires warmup again before a previously unhealthy backend
returns to service. This recovery path has not yet been verified against an actual vLLM process.

### Streaming and cancellation

The gateway requests usage information and forwards SSE data. It treats a stream ending without
the `[DONE]` marker as a failure, makes that failure visible, and releases its admission lease.
Once response headers have been sent, an upstream failure cannot be converted into a successful
new HTTP response. The caller must recognize the stream failure and decide what to do next.

The code closes the upstream response in its stream finalizer. Queue cancellation and stream
cleanup have contract-test coverage. Actual client-disconnect propagation, engine request
reclamation, and GPU/KV-memory recovery still require a real serving test.

## Declared profiles

These are explicit proposed profiles, not measured hardware performance claims.

| Profile | Backend and intended use | Configuration |
| --- | --- | --- |
| `profiles/cpu-functional.json` | Linux x86 CPU, tiny GPT-2 functional exercise | vLLM `0.30.0+cpu`, float32, context 128, max sequences 2, one replica |
| `profiles/t4-functional.json` | Linux NVIDIA T4 functional exercise | CUDA, compute capability 7.5, float16, context 2048, max sequences 2 |
| `profiles/l4-deployment.json` | Two NVIDIA L4 serving replicas | CUDA, compute capability 8.9, float16, context 4096, max sequences 8 |

The CUDA profiles use a proposed `Qwen/Qwen2.5-0.5B-Instruct` model. Their local model directory,
immutable model revision, and image digest remain unprovisioned. The CPU profile likewise needs
a complete local model artifact and a recorded immutable model identity. Do not fill those
fields with invented hashes.

The P09 owner supplied a 39,456-parameter random GPT-2 artifact at
`artifacts/p09-smoke/base-model` (vocabulary 309, embedding width 32, two heads, 128 positions).
Its original head size is 16. Inspection of the installed vLLM CPU attention backend found that
16 is outside its advertised supported head sizes. The functional trial therefore uses an
explicitly recorded derivative with one head and head size 32, while preserving the original
P09 files. Unchanged tensor shapes do not make this the same model: the attention configuration
changes and must have its own configuration/model identity. It is a random functional model,
not evidence of serving the SFT/DPO result or producing useful answers.

Current official vLLM documentation distinguishes Linux CPU, NVIDIA CUDA, AMD ROCm, Intel XPU,
and Apple Silicon plugin paths. The chosen CUDA requirements were checked against the current
documentation, which lists compute capability 7.5 or later. Float16 is selected for the T4
profile. These JSON profiles do not assert that every model, kernel, quantization format, or
driver combination is interchangeable.

## Provisioning checkpoint

The following environment was installed during this work:

```text
/workspace/scratch/708ae715c693/vllm-runtime/.venv
```

Package metadata reported:

| Package | Installed version |
| --- | --- |
| vllm | `0.30.0+cpu` |
| torch | `2.13.0+cpu` |
| transformers | `5.17.0` |
| httpx | `0.28.1` |
| intel-openmp | `2024.2.1` |

The official CPU wheel was 147,429,514 bytes. Its measured SHA-256 matched the GitHub release
asset digest:

```text
0ee75278b3626c5d0b7c310c6d62afae93e900f4eac339c91e333fde5108ed78
```

The CPU-specific wheel metadata was inspected before installation. It requested CPU PyTorch
packages; the resolved environment was kept separate from the application and training
environments. This is an installation checkpoint. It does not prove that importing the engine,
loading the model, serving a request, or running a comparison succeeds.

The environment is outside the repository. A portable version snapshot now exists as
`runtime-cpu.lock.txt`: it records 153 exact package versions and the official vLLM CPU wheel
URL/hash. Only the vLLM artifact has a pinned hash; this is not a complete hash-verified lock for
every transitive artifact. The last observed shared
workspace disk availability was 8.8 GiB; do not infer present capacity from that historical value.
The prepared [provisioning script](provision_cpu.sh) passed a shell syntax check, but a fresh
environment installation from that script and snapshot has not been executed.

## Actual CPU attempt and current blocker

The [first actual server report](../../artifacts/p14-cpu-functional-first/report.json)
records the bounded run on 2026-09-29 from 10:35:13 to 10:35:39 UTC. The installed runtime's
real `serve --help=all` command succeeded and verified every configured serving flag. The
subsequent server exited 1 before `/health` became ready. Its
[preserved log](../../artifacts/p14-cpu-functional-first/vllm-server.log) records
`zmq.error.ZMQError: Operation not permitted` while binding an `ipc:///tmp/...` address.
There were zero generation requests, no gateway workload probes, and
`inference_identity_verified=false`.

The [final local entrypoint report](../../artifacts/p14-local-final-preflight.json) records
an explicit prerequisite check: `AF_UNIX` / `SOCK_STREAM` socket creation raises
`PermissionError` with errno 1. The entrypoint now returns exit 2 and starts no server when
that prerequisite is unavailable. Inspection of the installed runtime found that its
supported asynchronous single-engine frontend requires multiprocessing and this IPC path.
No package or execution-control workaround was applied. A further functional run requires
an authorized host that supports the runtime's required local IPC.

The failed startup's sampled aggregate process RSS peaked at 1,342,173,184 bytes, across
515 samples at 50 ms intervals. This is a startup resource observation, not a serving
capacity measurement: summed RSS can count shared pages more than once, and no per-run
kernel memory limit was applied. The watchdog did not trigger, all owned processes stopped,
and the original P09 model files were preserved.

The first report contains literal `HEAD` in its commit field because the repository was
unborn when that report was captured. This is not a commit hash. The evidence index records
the correction, and the final prerequisite report uses a null commit with an explicit
unborn/unavailable marker. The exact executed supervisor source and source hash are retained
with the first report; the current supervisor additionally includes the fail-closed check.

## Existing setup and command interfaces

The application environment already supplies the gateway's FastAPI/Pydantic/httpx dependencies.
The actual vLLM runtime is intentionally isolated because its dependency versions differ from
the application. Use the intended interpreter when checking a runtime profile: a doctor run
under the root environment will not discover packages installed only in the separate CPU
environment.

Existing commands from the repository root:

```bash
uv run --no-sync python -m pais.inference doctor projects/14-inference-server/profiles/cpu-functional.json
uv run --no-sync python -m pais.inference doctor projects/14-inference-server/profiles/l4-deployment.json --deployment
uv run --no-sync python -m pais.inference load --help
uv run --no-sync pytest tests/test_operations_inference.py -q
uv run --no-sync pais demo 14 --profile fixture --output artifacts/p14-fixture.json
uv run --no-sync pais demo 14 --profile local --output artifacts/p14-local.json
```

The unprovisioned example profiles are expected to report missing prerequisites. A configuration
that parses successfully is not a verified runtime.

The prepared CPU supervisor provides an explicit runtime path and keeps the server, gateway,
and probes in one process tree/network namespace:

```bash
.venv/bin/python projects/14-inference-server/run_cpu_smoke.py --runtime-python /workspace/scratch/708ae715c693/vllm-runtime/.venv/bin/python --output artifacts/p14-cpu-functional-first
```

Use a fresh output directory for a new evidence run. The generic local demo dispatches the same
supervisor and accepts the runtime interpreter through `PAIS_VLLM_PYTHON`. The included
`chat-template.jinja` supplies the functional model's chat rendering. The final test run
passed eight gateway/admission contracts and three supervisor/prerequisite tests, with zero
skips. These checks do not establish real model serving. On this host the local demo is
expected to report the verified IPC prerequisite block with exit 2.

`kubernetes-cpu.template.yaml` contains four parsed YAML documents for the CPU profile. Parsing
is the extent of its current validation. No schema validation, image build, cluster apply, or
multi-instance recovery has been executed for that template.

Once real backends and their model configuration exist, the gateway factory can be launched
using the existing interface:

```bash
uv run --no-sync uvicorn pais.inference:create_gateway_app --factory --host 127.0.0.1 --port 8081 --workers 1
```

Before that launch, `PAIS_INFERENCE_GATEWAY_CONFIG` must point to a reviewed configuration such
as a provisioned copy of `gateway.example.json`. Gateway and upstream credential inputs are
`PAIS_INFERENCE_GATEWAY_TOKEN` and `VLLM_API_KEY`; provision them through the deployment's
authorized secret mechanism. No credential values belong in these files. The example backend
DNS names describe a future Kubernetes layout that does not yet exist in this repository.

The prepared tiny GPT-2 chat template still needs end-to-end validation on a functioning
server. The current gateway uses chat-completion and chat-tokenization endpoints for warmup
and admission. A plain completion-only model is not automatically compatible with that path.

The root fixture demo is implemented. Its [executed report](../../artifacts/p14-fixture.json)
passed four admission-control checks covering overflow, recovered capacity/idempotent release,
draining, and rejection accounting. It performed zero model requests and did not verify model
or engine identity. The serving supervisor, functional chat template, and CPU Kubernetes
template are prepared; the actual launch failure is preserved as a blocked acceptance result.

## Measurements and their meaning

The load harness records completed-request latency, TTFT, actual completion-token throughput,
gateway queue time when present, and individual request errors/cancellations. It reports p50,
p95, and p99 request latency. It requires a terminal stream marker, generated content, and
actual usage before counting a request as successful.

Wire-level SSE chunk gaps are labeled `inter_chunk_seconds`. A chunk can contain multiple
tokens, so these values are not presented as individual token intervals. vLLM's backend
`vllm:inter_token_latency_seconds` histogram is the intended server-side intertoken measurement.
Queue time, KV-cache usage, request counts, and memory/OOM observations also need backend and
runtime collection. That collection and the experimental comparison workflow remain incomplete.

The generic HTTP harness sets `inference_identity_verified=false`: successfully reaching an
OpenAI-compatible endpoint does not independently establish what engine or model it serves.
Tie its report to actual runtime/model startup evidence before labeling it vLLM evidence.

## Sources checked

- [vLLM CPU installation](https://docs.vllm.ai/en/stable/getting_started/installation/cpu/)
- [vLLM GPU installation](https://docs.vllm.ai/en/stable/getting_started/installation/gpu/)
- [vLLM v0.30.0 release](https://github.com/vllm-project/vllm/releases/tag/v0.30.0)
- [vLLM Kubernetes deployment](https://docs.vllm.ai/en/stable/deployment/k8s/)
- [vLLM production metrics](https://docs.vllm.ai/en/stable/usage/metrics/)

These sources were inspected during implementation. The configured serving flags were also
verified against the installed runtime's actual CLI help. Model loading and chat behavior
remain unverified because the server could not reach readiness.
