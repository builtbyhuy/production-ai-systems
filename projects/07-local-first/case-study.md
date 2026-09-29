# Case study — local means a verified execution profile

The hardware constraint shaped this implementation: an 8 GiB CPU environment cannot be
treated as an unlimited inference workstation. The chosen local models are a small quantized
generator, a 22M embedding model and a compact pairwise reranker. One inference verification
runs at a time; provider calls are local HTTP, model files remain outside Git, and runtime
downloads are disabled after deliberate provisioning.

## Why two storage implementations

The specification named both SQLite/sqlite-vec and LanceDB. Hiding one behind a label would
not demonstrate backend interchangeability. Both expose the same principal-scoped vector
contract, but they own different physical stores, schema initialization and mutation code.
SQLite remains the authoritative PDF/version store. This keeps citations and authorization
stable while allowing vector storage to change.

Their transaction semantics are different. SQLite can atomically update its own vector
table. LanceDB cannot join that transaction. The RAG service commits source changes first,
invalidates the index checkpoint and repairs from committed authority while serialized by
the SQLite lock. A targeted failure test interrupts after the external side effect; the next
access repairs successfully instead of trusting a stale completed checkpoint.

## What was verified

The shared contracts execute both actual libraries, including tenant filtering before top-k,
reopening persistent state, deletion, malformed vectors and unsafe-looking filter values.
The actual offline local demos separately exercised Ollama generation/embeddings and the
pinned CrossEncoder with 13/13 behavior checks for each store. This separation prevents
fixture model scores from becoming a claim of semantic quality.

The corrected SQLite resource run passed all 13 checks in 25.579 seconds. Sampled app and
Ollama aggregate RSS peaked at 1,865,792 KiB (1.78 GiB); application-only high-water RSS was
623,516 KiB. The model directory occupied 4,132,420,551 bytes, including models for other
projects. These are measured observations for one small workload, not capacity guarantees.
The [resource report](evidence/offline-local-sqlite-resources.json) records commands,
versions, model identities, hardware and the two network-boundary checks.

An initial memory watcher exposed a measurement failure worth retaining: the child process
ID belonged to a nested PID namespace, while `/proc` exposed host IDs. It sampled an unrelated
process and produced an implausibly low aggregate. Those original aggregate observations are
marked invalid, while their independently collected application RSS and lifecycle evidence
remain intact. The corrected watcher resolves `PPid` and `NSpid` before walking descendants;
a known child/grandchild allocation verified that mapping before the model workload rerun.

## The offline distinction

Turning off SDK telemetry and model downloads is useful, but it does not disable the
network. In this managed environment Linux exposes only loopback and no external route;
direct IPv4 and IPv6 connections fail with `ENETUNREACH`. Managed proxy variables can still
provide egress, so the offline runner removes them for the full native service/application
subtree and records the kernel boundary before and after its real workload.

That is a declared trusted-application offline profile. It is not a sandbox for arbitrary
malicious code: a managed loopback proxy endpoint could still exist. On a normal connected
host the runner returns a prerequisite failure and requires an externally provisioned isolated
namespace/VM. It does not weaken the gate to obtain a green result.

Container deployment and resource limits are separate operational work. Docker is not
available here, so a prepared Compose configuration cannot be described as an executed clean
container setup. P07 stays visibly incomplete until those deployment acceptance criteria have
real evidence on a capable machine.
