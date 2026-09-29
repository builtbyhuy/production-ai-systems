# P14 case study — bounded serving with honest measurements

## Decision

Place a small explicit admission and streaming boundary ahead of configured model servers,
while keeping hardware-specific serving in an isolated vLLM environment. Measure what the
client and server actually expose, and label installation, contract, functional, and performance
evidence separately.

## Why admission is outside the engine

The gateway rejects excessive queue growth before a request reaches generation. It limits
both active requests and waiting requests, has a bounded wait time, and exposes draining as an
explicit state. This keeps overload behavior reviewable even while the model server's scheduler
changes between runtime versions.

Before generation, the gateway asks the selected backend to tokenize the actual chat messages
with their generation template. It then checks input tokens plus the requested output budget.
A character-count estimate would be an unreliable context limit across languages and models.
The request also has an earlier byte-size bound so tokenization is not the first limit applied.

The limits are local to one gateway event loop. This choice is simple enough to test, but it
does not establish a cluster-wide quota. Multiple gateway replicas need an explicitly designed
global limit or a carefully declared multiplication of the per-process capacity.

## Why warmup and liveness differ

A responding process can still be loading a model or unable to generate. Backends therefore
must pass a health check and return generated warmup content before becoming ready. The
gateway's liveness endpoint remains separate from that readiness decision.

A backend that fails later is removed from selection and must warm up again before returning.
The code implements that path. A real instance restart has not yet validated it.

## Why streamed failure is explicit

After the gateway sends part of an answer, silently retrying on another backend could duplicate
or contradict content. The implementation reports a failed/truncated stream and leaves recovery
to the caller. A missing terminal marker does not count as a completed inference.

Admission leases are released in a finalizer, and the upstream response is closed. Tests cover
queue cancellation and mocked response cleanup. Real engine-request cancellation and memory
reclamation remain separate acceptance criteria.

## Hardware finding

The initial environment had no GPU, Docker, or vLLM command. That did not mean vLLM was
intrinsically unavailable: current official releases provide an x86 CPU wheel, and this host's
architecture/CPU instruction set made a CPU functional trial plausible. The 147 MB official
v0.30.0+cpu wheel was downloaded, its release digest matched, its CPU-specific dependencies
were inspected, and those dependencies were installed in a separate environment.

The installed CPU attention backend advertised head sizes starting at 32. P09's random GPT-2
had head size 16, so the functional model was an explicitly recorded one-head derivative with
head size 32. Its tensor bytes were unchanged, its attention semantics and identity changed,
and the original P09 model was preserved. It was never presented as a trained adapter or a
useful language model.

The bounded supervisor then ran the real vLLM CLI help and verified the configured flags.
The actual server failed before readiness: ZeroMQ could not bind its required Unix-domain
IPC address because the execution host returned `Operation not permitted`. A direct
prerequisite check confirmed that AF_UNIX socket creation itself raises errno 1. The final
entrypoint now reports the unavailable prerequisite with exit 2 and does not launch a server.
The runtime's supported asynchronous single-engine frontend requires this IPC path; no
runtime package or execution-control workaround was applied.

This distinguishes a package-installation success from an actual serving failure. An
authorized host with the required IPC capability is needed for the next functional test.
GPU experiments and cluster recovery retain their separate prerequisites. The complete
checkpoint, including the first report's corrected unborn-repository commit metadata, is
in [EVIDENCE.json](EVIDENCE.json).

## Alternatives considered

| Alternative | Reason it was not selected |
| --- | --- |
| Treat all hardware backends as interchangeable | Kernel, dtype, quantization, driver, and package support differ |
| Use character counts as token counts | Would not account for actual tokenizer and chat-template behavior |
| Unlimited waiting behind the model server | Hides overload and allows waiting work to grow without a bound |
| Retry a partially emitted response silently | Can duplicate output and hide a failed inference |
| Report SSE chunk gaps as token intervals | A chunk can contain multiple tokens |
| Treat a compatible HTTP response as verified vLLM identity | The endpoint can be backed by a different engine or model |
| Install vLLM into the main application environment | Its runtime dependencies differ substantially from the application |

## What was measured

The final P14 contract/supervisor suite passed 11 tests with zero skips. Gateway tests
covered capacity reclamation after queue timeout/cancellation, draining, invalid configuration,
warmup-based readiness, two mocked backend selections, token-budget rejection, and visible
truncated-stream failure. Supervisor tests include prerequisite rejection. The exact vLLM/CPU
package versions were separately inspected after installation.

The failed actual startup recorded zero generation requests. Its sampled aggregate process
RSS peaked at 1,342,173,184 bytes over 515 samples at 50 ms intervals, with no watchdog trigger
and all owned processes stopped. This sum can double-count shared pages and was not enforced
by a per-run kernel memory cap. It describes failed startup resource use, not serving capacity.

No throughput, TTFT, intertoken latency, GPU-memory, model-quality, OOM, batching, prefix-cache,
or quantization result has been measured against a verified vLLM server. There are no invented
performance numbers in this project.

## Next evidence that would change the status

On an authorized host that supports the required local IPC, first run a bounded tiny-model
CPU functional request and record the exact model/runtime identity, startup behavior, output,
and cancellation/error path. Then connect the existing gateway after checking the model's
chat-template compatibility. Finally execute a provisioned CUDA/Kubernetes profile with
comparative performance and failure-recovery workloads. Each step should update its own
acceptance state without replacing the preserved failed run.
