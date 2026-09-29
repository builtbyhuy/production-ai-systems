# P14 interview walkthrough

## Explain the critical code path

Begin with `VLLMProfile` and `GatewayConfig` in `packages/pais/inference.py`. Explain the
declared hardware/runtime choices, unprovisioned artifact fields, and why clients cannot choose
backend URLs. Then trace a request through body-size validation, authentication, admission,
backend selection, tokenizer counting, output/context limits, and streaming.

Point out where the lease is acquired and every path that releases it. Explain queue overflow,
queue timeout, cancellation, no ready backend, a tokenizer failure, an upstream error before
headers, and a stream that ends without `[DONE]`.

Walk through readiness separately: health probe, generation warmup, candidate selection,
periodic failure detection, and rewarmup. Clearly distinguish implemented behavior from the
absence of an actual serving-instance recovery run.

## Be able to answer these questions

1. Why bound both active and queued requests? Explain the resource and latency implications of
   accepting unlimited waiting work.
2. Are the limits global? No: identify the single-process boundary and what changes when the
   gateway is replicated.
3. Why is the tokenizer request made to the selected backend? Discuss tokenizer/model/template
   agreement and the requested output allowance.
4. What can go wrong when a tiny GPT-2 artifact is used through a chat endpoint? Explain the
   need to verify the chat template and supported serving interface.
5. Why does the gateway warm up before readiness? Explain model load versus useful generation.
6. What happens when a backend dies halfway through an answer? Explain truncated-stream
   signaling, the absence of a silent midstream retry, and caller recovery responsibilities.
7. Does closing an HTTP response prove GPU memory was released? No: describe the additional
   engine metrics and disconnect experiment required.
8. How is TTFT measured? Identify the first generated content observed by the client and
   distinguish it from internal prefill timing or first HTTP headers.
9. Why are chunk gaps not intertoken latency? Show the wire-level `inter_chunk_seconds` field
   and the separate backend metric that would be needed.
10. What does the installed CPU wheel prove? Explain package identity and installation, then
    list the separate import, model-load, generation, quality, and performance checks.
11. Why is the T4 profile float16? Explain its declared compute capability and why dtype support
    must be checked against the actual backend.
12. What must be held constant in a batching/cache/quantization comparison? Discuss model and
    dataset identities, input/output lengths, concurrency, warmup, measurement definitions,
    quality checks, and inclusion of errors.
13. Why did the installed CPU runtime fail to serve? Show the actual ZeroMQ IPC bind error
    and the AF_UNIX errno 1 prerequisite result. Explain why the entrypoint exits 2 without
    launching a server and why installing compatible packages did not establish host support.
14. Why is the one-head tiny model a separate artifact? Its weight shapes and bytes are
    unchanged, but its attention configuration changes; preserve both identities and avoid
    attributing this functional derivative to SFT/DPO training.

## Changes you should be able to make yourself

- Add a bounded test proving an admission reservation is released on a newly introduced error.
- Adjust context and output limits while preserving actual-tokenizer validation.
- Add a compatible backend profile without claiming that an untested quantization works.
- Extend the load report with a server-side metric while keeping client and server timing
  definitions distinct.
- Extend the fixture `demo()` profile handling while preserving a clear failure for missing
  real-serving prerequisites.
- Design an actual instance-failure recovery drill and specify the exact observations that
  would establish recovery.

## Describe the evidence accurately

State that the gateway passed mocked HTTP/async contract tests and that an isolated CPU vLLM
environment was installed with verified package metadata. The fixture demo passed four checks
with zero model requests; the final gateway/supervisor suite passed 11 tests with zero skips.
The real server launch exited 1 before readiness because required Unix-domain IPC was denied.
The final local entrypoint records the prerequisite block and exits 2 without starting a
server. No generation, real streaming, engine cancellation, cluster recovery, or performance
comparison passed. Use [EVIDENCE.json](EVIDENCE.json) to show the measured failure, cleanup,
source/model hashes and explicit correction of the first report's literal `HEAD` commit field.
A future tiny-model functional pass would still not establish useful model quality or
production throughput.
