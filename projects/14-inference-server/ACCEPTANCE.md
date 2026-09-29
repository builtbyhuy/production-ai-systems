# P14 acceptance and evidence ledger

Do not combine installation, mocked HTTP behavior, small functional generation, and accelerator
performance into a single readiness claim.

| Criterion | Implementation | Verification state | Evidence / remaining action |
| --- | --- | --- | --- |
| Explicit CPU/CUDA compatibility profiles | Implemented | Configuration checks only | Official installation docs inspected; model/kernel/runtime validation pending |
| CPU-specific wheel identity | Downloaded and inspected | PASS, asset digest matched | 147,429,514-byte v0.30.0+cpu wheel |
| CPU package installation | Completed in separate environment | PASS, package metadata inspection | No engine/model inference claimed |
| Portable CPU dependency snapshot | Prepared | Version snapshot only | `runtime-cpu.lock.txt`: 153 exact package versions; only vLLM artifact hash pinned |
| Actual CPU model load and generation | Supervisor implemented; actual launch attempted | BLOCKED before readiness | First launch exited 1 on denied ZeroMQ IPC; zero generation requests |
| Required local IPC checked before launch | Implemented | PASS, observed fail-closed rejection | Final local demo reports AF_UNIX errno 1, exits 2, and launches no server |
| Tiny GPT-2 chat-template compatibility | `chat-template.jinja` prepared | Real serving validation pending | Current gateway requires chat endpoints |
| Root `pais demo 14` fixture entrypoint | Implemented | PASS, four admission checks | `artifacts/p14-fixture.json`; zero model requests; engine identity unverified |
| Concurrency and queue limits | Implemented | PASS, async contract test | Overflow, timeout, and cancellation release capacity |
| Graceful admission drain | Implemented | PASS, async contract test | New and queued work rejected after drain |
| Configured backend destinations and authentication requirement | Implemented | PASS, contract test | Real deployment access boundary not exercised |
| Readiness waits for successful generated-content warmup | Implemented | PASS with mocked HTTP | Actual vLLM warmup NOT RUN |
| Actual-tokenizer context admission | Implemented | PASS with mocked tokenizer response | Real tokenizer/template behavior NOT RUN |
| Two-backend selection | Implemented | PASS with mocked HTTP backends | Real balancing and traffic distribution NOT RUN |
| Truncated stream becomes an observable failure | Implemented | PASS with mocked HTTP stream | Real engine interruption NOT RUN |
| Client disconnect releases engine resources | Finalizer implemented | NOT RUN against vLLM | Measure active request/KV-memory recovery on disconnect |
| Returning backend rewarms before readiness | Health-loop path implemented | NOT RUN against vLLM | Kill/restart an actual serving instance |
| Actual throughput, TTFT, p95/p99 | HTTP harness implemented | NOT RUN against a verified vLLM runtime | Declare prompt lengths, output limits, concurrency, runtime and model identity |
| Backend intertoken latency and queue measurements | Metrics identified | NOT RUN | Collect backend metrics rather than relabeling chunk gaps |
| Supervised startup process resources and cleanup | Sampled process-tree observer | MEASURED for failed startup only | Peak sum-RSS 1,342,173,184 bytes; 515 samples; no watchdog trigger; no owned processes remain |
| Serving memory, KV-cache use, errors and OOMs | Not fully instrumented by this project | NOT RUN | Runtime/GPU metrics and failure classification required |
| Continuous-batching comparison | Profile controls prepared | NOT RUN | Repeat declared workload with the compared settings |
| Prefix-cache comparison | Profile flag prepared | NOT RUN | Warm/cold shared-prefix experiment with quality held constant |
| Quantization quality/performance comparison | Validation boundary only | NOT RUN | Supported artifact/backend plus independent quality evaluation |
| CPU Kubernetes template | Prepared | Four YAML documents parsed; schema/cluster NOT RUN | `kubernetes-cpu.template.yaml` requires actual target validation |
| CUDA Kubernetes deployment | Not prepared as an executed deployment | NOT RUN | Real resource/probe/storage/network/shutdown configuration and GPU cluster required |
| Cluster load balancing and serving-instance recovery | Not deployed | NOT RUN | Actual cluster drill required |

## Existing test evidence

The final P14 run passed 11 tests, with zero failures, errors or skips: eight existing
gateway/admission contracts and three supervisor/prerequisite cases. The command was
`.venv/bin/pytest tests/test_operations_inference.py projects/14-inference-server/test_supervisor.py -q --junitxml=artifacts/p14-contract-tests.xml`.
The [JUnit report](../../artifacts/p14-contract-tests.xml) records 0.294 seconds. Gateway tests
use explicit mock HTTP responses; this is not vLLM inference evidence. The
[evidence index](EVIDENCE.json) records the fixture, runtime installation, failed actual launch,
final blocked preflight, model identities, source hashes and their distinct scopes.

## Evidence required for a functional run

A separately identified one-head derivative was prepared because the original random P09
model's head size 16 is outside the installed CPU backend's advertised supported sizes.
Its weight bytes match the original initialization, but its changed attention semantics
give it a distinct model identity. The actual launch failed before readiness on the required
Unix-domain IPC socket; no model generation passed. The original P09 files were preserved.

Record exact invocation, UTC timestamp, source commit/dirty status, runtime and package
versions, backend, host architecture/CPU features, process resource limits, model architecture,
immutable model/config/tokenizer identities, warmup behavior, request/response, usage, exit
status, and any startup errors. A tiny locally trained or random model may establish execution
of the serving path; it must not support useful-answer or model-quality claims.

## Evidence required for performance acceptance

Record named hardware, driver/runtime versions, memory capacity/use, model revision, dtype,
quantization, KV/prefix-cache settings, batching/context limits, prompt/output lengths,
concurrency/rate, warm/cold state, warmup policy, repeats, timing definitions, raw request results,
backend histograms, error/OOM counts, and the corresponding quality evaluation.

Keep deliberately cancelled requests separate from failed requests. Include failed runs in
the comparison rather than reporting only successful throughput. Do not infer per-token
latency from an HTTP chunk count.

## Completion rule

Current P14 status is **gateway/supervisor contracts verified; CPU dependencies installed;
actual server attempt BLOCKED before readiness; generation and deployment/performance
acceptance unverified**. The final local entrypoint fails closed with exit 2 before server
launch on this host. CPU functional execution on a host supporting the required IPC would be
a separate milestone and would not satisfy the cluster/performance criteria by itself.
