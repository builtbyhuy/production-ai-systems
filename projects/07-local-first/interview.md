# Interview walkthrough — P07

Show the two adapter test runs first, then the local model report and offline boundary
report. Explain why they prove different properties and why none is a scale benchmark.

## Critical code to explain

- `models.LocalModels`: immutable Ollama digests, local safetensors file hashes, CPU
  CrossEncoder loading, bounded threads and explicit failure when prerequisites are absent.
- `retrieval.SQLiteVecAdapter`: per-connection extension loading, normalized vectors,
  parameterized metadata filtering and transactional tenant mutation.
- `retrieval.LanceDBAdapter`: real Arrow schema/Lance table, explicit string-literal escaping,
  prefilter cosine query and separate persistence/replacement behavior.
- `rag._ensure_index`: authority revision, incomplete external checkpoint, serialized repair
  and reauthorization of retrieved IDs against active source versions.
- `offline_acceptance.py`: proxy environment removal, actual kernel boundary verification,
  negative IPv4/IPv6 probes, same-namespace native server and end-to-end application run.
- `compose.yaml` and `compose.offline.yaml`: native-model versus internal-network container
  profiles, persistent selected-store state, explicit images and bounded resources. Explain
  why these prepared files still require an actual target-machine build/start acceptance run.

## Questions to answer clearly

Why must a model change trigger reingestion rather than reuse existing vectors? Why can the
Lance index have a different lifecycle from the PDFs? What exactly would make the offline
runner refuse to run? Which memory number includes the model server, and which does not?
Why is setting `HF_HUB_OFFLINE=1` insufficient evidence of network isolation?

## Demonstration to own yourself

Run a fixture demo with each store. Add a second tenant whose vectors are closer to a query
and show that the first tenant still receives its own top-k. Remove the selected derived
index and show authorized retrieval repair from SQLite. Then run the actual local profile,
inspect raw model usage and citations, and deliberately change one model-lock digest to show
the requested profile fails instead of falling back.

For a laptop handoff, provision models on the target machine, regenerate its path-specific
manifest and measure its own latency/RAM. Do not reuse this environment's results as claims
about a different machine.
