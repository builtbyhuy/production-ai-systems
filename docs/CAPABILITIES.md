# Capability and dependency plan

Preflight: Linux x86_64, Python3.12.14, Node24.19.0, Git2.51.1, 8GiB cgroup RAM,
eight-CPU quota, initially26GiB free. No GPU, Docker, Kubernetes, native model server or
provider credentials were initially present. GitHub account `builtbyhuy` was resolved;
the named portfolio repository was not found and the connector has no repository-create operation.

| Profile | What it proves | Requirements | What it cannot establish |
|---|---|---|---|
| Fixture | Deterministic contracts, real storage/graph behavior, security/recovery assertions | Locked core/workflow/vector dependencies and explicit fixture auth | Real model quality, actual provider savings, cloud billing, production operation |
| Local | Actual Ollama embeddings/generation, real cross-encoder, PDF/RAG/application behavior | Provisioned model digests, CPU runtime, about2–4GiB working memory depending on concurrently loaded models | Cluster throughput, real SaaS integration, arbitrary semantic correctness |
| Connected | Actual authenticated third-party services in allowed test modes | Supabase/Stripe test/LangSmith accounts and explicit target/budget | Evidence for integrations not exercised |
| Deployment/performance | Named hardware, declared load, real operational drill | Sandbox/cluster/runtimes, provisioned models and digest-pinned artifacts | Larger datasets/concurrency/hardware than actually tested |

## Deliberate provisioning

| Component | Download/storage scale | Decision |
|---|---|---|
| Core Python and optional storage/workflows | Hundreds of MB, exact versions in uv.lock | Separate lean fixture vs local profile |
| CPU PyTorch2.8 | About175MiB wheel | CPU-only explicit Linux index avoids CUDA dependency downloads |
| Ollama0.34.4 Linux archive | 1,427,703,051bytes compressed | CPU components extracted; consumed archive removed after SHA256 capture |
| qwen2.5:1.5b Q4_K_M | 986,061,892bytes model bundle | One generation request at a time, two threads |
| all-minilm:22m F16 | 45,960,996bytes model bundle | 384-dimensional embeddings |
| MiniLM-L6 cross-encoder | About90MB weights | Immutable safetensors revision233902d25c440f23af6f7d6e94d2946bac0bee0a |
| Redis8.2.1 | About4MB source archive plus native build | Local durable-broker/memory tests, no hosted Redis |
| Tiny LoRA SFT/DPO | Randomly initialized tiny model, no downloaded base weights | Pipeline smoke only, no language-quality claim |
| CPU vLLM | Separate wheel/runtime and profile | Functional serving evaluated separately from GPU/cluster performance |

The old cross-encoder revision chosen from historical documentation had only pickle-format
weights. Provisioning moved to the verified immutable safetensors revision before running
quality checks. Hashes and exact models are recorded in `models/local-models.lock.json`.

No paid provider or billing action has been configured. Local API-charge reports refer only
to the actual native profile and exclude hardware, electricity and engineering costs.

## Offline execution

Both native SQLite and LanceDB offline runs passed thirteen checks in a loopback-only
network namespace, with proxy variables removed and direct IPv4/IPv6 egress probes failing
before and after the run. Model loaders use local files, telemetry defaults are disabled,
and Ollama cloud is disabled. LiteLLM uses bundled model metadata; ledger prices are explicit.
The corrected process-tree measurement recorded 1,865,792 KiB sampled aggregate RSS for
the application plus Ollama. Summed RSS can double-count shared pages.

This proves the stated trusted-application native profile. The managed host may expose
loopback proxy endpoints, and this is not an isolation boundary for hostile code. The
executor gives each command its own network namespace; services and probes therefore run
inside one orchestration command. Compose's internal-network profile is prepared but was
not executed because Docker is unavailable. See P07's evidence and exact commands.

## Working context

Keep this repository as its own Codex project root. Read AGENTS.md and STATE.md first.
Do not open a parent containing unrelated projects. `.gitignore` excludes dependencies,
models, databases, build output and raw logs from Git, but is not a universal context-control
mechanism. Use `rg --files packages/pais projects/<active-project> tests` with scoped paths;
avoid recursively loading node_modules, .venv, .tools, models or artifacts.
