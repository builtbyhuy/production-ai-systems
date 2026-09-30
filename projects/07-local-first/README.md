# P07 — A local stack with explicit model and storage boundaries

Run actual generation, embeddings, reranking, PDF provenance and tenant-filtered retrieval
on one local machine. Reranking runs on CPU; native Ollama selects the available device. SQLite/sqlite-vec is the default. LanceDB is a separately implemented,
selectable local vector store; selecting it does not launch a second vector service.

**Evidence:** both actual storage implementations pass the shared fixture contracts.
The complete local Ollama/CrossEncoder pipeline passed all 13 checks with each store inside
the verified offline application profile: [SQLite](evidence/offline-local-sqlite.json) and
[LanceDB](evidence/offline-local-lancedb.json). The runner refuses to claim isolation without
kernel network evidence. See [acceptance.md](acceptance.md) for resource measurement details
and the remaining container deployment gate.

## Clean setup and model provisioning

Use the repository's Python 3.12 environment and lockfile. The full local extra deliberately
includes CPU PyTorch; do not accidentally install a GPU wheel on an 8 GiB laptop.

```bash
uv sync --frozen --group dev --extra local
```

Install official native [Ollama](https://ollama.com/download) for your platform. Linux
verification used Ollama 0.34.4; macOS can use the native application. With the server running,
the explicit initial downloads are:

Start the server from the repository root in a separate terminal and keep it running:

```bash
OLLAMA_HOST=127.0.0.1:11434 OLLAMA_MODELS="$PWD/models/ollama" OLLAMA_NO_CLOUD=1 OLLAMA_CONTEXT_LENGTH=2048 ollama serve
```

The pulls, lock creation and later API must use this same server and model directory.
Run the following in the original repository terminal:

```bash
ollama pull qwen2.5:1.5b
ollama pull all-minilm:22m
uv run --no-sync python - <<'PYTHON'
from huggingface_hub import snapshot_download
snapshot_download(
    "cross-encoder/ms-marco-MiniLM-L6-v2",
    revision="233902d25c440f23af6f7d6e94d2946bac0bee0a",
    allow_patterns=["*.json", "*.txt", "*.safetensors"],
    local_dir="models/reranker", token=False,
)
PYTHON
.venv/bin/python projects/07-local-first/lock_models.py --reranker-dir models/reranker --output models/local-models.lock.json
```

The generation weights are approximately 986 MB and embedding weights approximately 46 MB
on the official model pages; reranker weights and the CPU runtime add disk/RAM requirements.
These estimates are not a promise of total resident memory. The corrected native offline
SQLite run measured a peak aggregate app/Ollama RSS of **1,865,792 KiB (1.78 GiB)** over a
25.58-second lifecycle demo. Shared pages can appear in more than one process's RSS. The
repository's provisioned model directory occupied **4,132,420,551 bytes (3.85 GiB)**, including
models provisioned for other projects; it is not the minimum P07 model download size.
See the [resource report](evidence/offline-local-sqlite-resources.json) and measurement notes
in [acceptance.md](acceptance.md).

`lock_models.py` never downloads anything. It records full local Ollama digests, the immutable
reranker revision and SHA-256 hashes of each local model file. It requires safetensors weights.
Runtime verification checks this manifest and prohibits hidden Hugging Face downloads.
The default CPU thread count is 2, configurable up to 4 with `PAIS_LOCAL_THREADS`.

For the managed execution environment, the root provides a native Ollama wrapper. The
server and application must run inside the same tool process/network namespace:

```bash
.venv/bin/python scripts/with_local_models.py --provision -- .venv/bin/python projects/07-local-first/lock_models.py --reranker-dir models/reranker --output models/local-models.lock.json
.venv/bin/python scripts/with_local_models.py -- .venv/bin/python projects/07-local-first/demo.py --profile local --backend sqlite --output artifacts/p07-local-sqlite.json
.venv/bin/python scripts/with_local_models.py -- .venv/bin/python projects/07-local-first/demo.py --profile local --backend lancedb --output artifacts/p07-local-lancedb.json
```

`--provision` is an explicit one-time pull. Subsequent commands omit it. Keep only one
inference verification running at once on the declared machine. The wrapper stops its own
server when the command exits; ordinary execution does not delete downloaded models.

## Select the store

| Concern | SQLite/sqlite-vec | LanceDB |
|---|---|---|
| Selection | `backend='sqlite'` or API `PAIS_VECTOR_BACKEND=sqlite` | `backend='lancedb'` or API `PAIS_VECTOR_BACKEND=lancedb` |
| Vector persistence | `rag_vectors_v1` in the application SQLite file | Sibling `<database-path>.lancedb` directory with Arrow schema and Lance versions |
| Vector query | Exact cosine KNN, tenant metadata filter | Exact cosine search, `where(..., prefilter=True)` |
| Lexical retrieval | SQLite FTS5 | SQLite FTS5, because source/lexical application state remains SQLite-authoritative |
| Active PDF/version authority | SQLite | SQLite |
| Repair/durability | Same-store transactional vector write | Separate external-index replacement/checkpoint protocol |
| Concurrency | SQLite write lock coordinates local writes/repair | RAG service takes the same lock around derived-index replacement and reads |
| ANN/distributed claim | None in P07 | None in P07; scale tests belong to P12 |

The local Lance adapter uses a separate schema/versioned table and real LanceDB operations.
It is not a switch that secretly forwards every query to sqlite-vec. Every returned vector
ID is checked again against authorized active SQLite chunks before source text is returned.

Changing the embedding model/dimension fails when reopening an existing database. Create
a new database and reingest authorized source PDFs with the new model; do not reuse old
vectors under a new model label. An externally missing derived index is rebuilt on read.

## Offline acceptance

```bash
.venv/bin/python projects/07-local-first/offline_acceptance.py --backend sqlite --output artifacts/p07-offline-sqlite.json
```

The runner strips every environment variable whose name contains `proxy` for the whole
native Ollama/application subtree, disables model downloads and tracing, and checks:

- Linux reports only the loopback interface and no non-loopback IPv4/IPv6 routes.
- Direct public IPv4 and IPv6 TCP connections fail.
- The same boundary is still present after real ingestion, retrieval, generation and citation.
- The model lock, local generation, citation, CRUD and failure/recovery checks all pass.

On an ordinary networked laptop this runner returns exit 2. Run it inside an externally
provisioned loopback-only Linux network namespace/VM, or a validated internal Compose
network. It does not disable your host network or change firewall rules. Creating a new
user/network namespace is prohibited in this managed environment, so the runner verifies
the existing isolated execution namespace instead.

Managed loopback proxy endpoints may still exist. This verifies the declared trusted
application's offline profile after proxy configuration is removed; it is not a hostile-code
network sandbox. A direct local-model demo with offline flags alone is not an offline proof.

## API and containers

The API uses `PAIS_PROFILE=local`, `PAIS_DB_PATH`, `PAIS_VECTOR_BACKEND`, `PAIS_MODEL_LOCK`
and `PAIS_OLLAMA_URL`. It resolves bearer credentials server-side. Fixture authentication is
opt-in and is not enabled by the local deployment configuration. Production validator
dependencies must be available or the API rejects protected requests.

Native Ollama is useful on macOS while the application components run in containers. Use
`http://host.docker.internal:11434` for the declared native service, mount a read-only model
directory, and generate a container-specific lock whose reranker path is `/models/reranker`.
The prepared [Compose file](compose.yaml) runs this API-only native-model profile. Its
[offline override](compose.offline.yaml) adds the official Ollama container on an internal
network. Both use the root `infra/Dockerfile.api`, including the mandatory isolated P06
validator environment. Docker was unavailable during this build: neither file has a recorded
Compose build/start result, and the native evidence does not validate container behavior.

### Prepare a container launch on a capable machine

After native model provisioning, create a path-specific lock while Ollama is running:

```bash
.venv/bin/python projects/07-local-first/lock_models.py --reranker-dir models/reranker --runtime-reranker-path /models/reranker --output models/container-models.lock.json
```

Choose a reviewed Python base-image digest and build the locked application. The image ID
used by Compose is captured from that build; no registry push is needed. Set
`PAIS_BASE_IMAGE` to an actual immutable `python:3.12-...@sha256:...` reference first.

```bash
docker build --build-arg BASE_IMAGE="$PAIS_BASE_IMAGE" -f infra/Dockerfile.api -t pais-local:reviewed .
export PAIS_API_IMAGE="$(docker image inspect --format '{{.Id}}' pais-local:reviewed)"
export PAIS_MODELS_DIR="$(pwd)/models"
export PAIS_AUTH_FILE="$(pwd)/var/p07-private/auth.json"
```

Create the credential file once, with independent random bearer credentials and an explicit
trusted subject/tenant/role mapping. The following local-development seed refuses to replace
an existing file. Keep it private and outside Git; supply its credential in the API/UI.

```python
import json
import os
import secrets
from pathlib import Path

path = Path("var/p07-private/auth.json")
path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
path.parent.chmod(0o700)
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, "w") as handle:
    json.dump({secrets.token_urlsafe(32): {
        "subject": "local-operator", "tenant_id": "local-workspace", "roles": ["admin"]
    }}, handle)
path.chmod(0o444)
```

The containing host directory is private (`0700`). The file is readable by the non-root
container after Docker mounts that file alone as a secret. Compose file-based secrets retain
host file permissions; do not assume its `uid`/`mode` fields remap an unreadable host file.

The container entrypoint reads the mounted secret, enforces a nonempty trusted mapping and
strips proxy variables before starting the API. It does not enable fixture credentials or
silently start with no authentication. Start the native Ollama application first, then:

```bash
docker compose -f projects/07-local-first/compose.yaml up -d --wait
docker compose -f projects/07-local-first/compose.yaml ps
docker compose -f projects/07-local-first/compose.yaml down
```

The base file permits connectivity to the native host service; it is not an offline proof.
Application state, including the selected LanceDB directory when enabled, persists in the
`application_state` volume. Only the selected Python adapter opens its index. Application
memory is capped at 3 GiB and two CPUs; a native Ollama process is outside those container
limits. Change the backend before starting with `PAIS_VECTOR_BACKEND=lancedb`.

For the full container profile, deliberately preload the official Ollama image and record
its immutable repository digest as `PAIS_OLLAMA_IMAGE`. Both Compose services have
`pull_policy: never`. With the models already provisioned:

```bash
docker compose -f projects/07-local-first/compose.yaml -f projects/07-local-first/compose.offline.yaml up -d --wait
docker compose -f projects/07-local-first/compose.yaml -f projects/07-local-first/compose.offline.yaml ps
docker compose -f projects/07-local-first/compose.yaml -f projects/07-local-first/compose.offline.yaml down
```

The override attaches API and Ollama to an `internal: true` network, changes the model URL
to `http://ollama:11434`, and caps Ollama at 3 GiB/two CPUs. Confirm external IPv4/IPv6
connection failures, model readiness, a seeded PDF upload and a cited answer on the target
machine before promoting this configuration to verified offline evidence. The native offline
runner intentionally rejects non-loopback interfaces, so it is not a container bridge-network
validator. A Compose declaration alone cannot substitute for those runtime checks.

Seed PDF bytes are available through `pais.rag.create_demo_pdf([...])`; the regular UI upload
or authenticated `POST /api/documents` ingests them. The project demo seeds itself and removes
its temporary database. `down` retains named state volumes and the externally provisioned
model directory; removing persistent data is a separate operator decision.

The configuration follows the official [Compose service fields](https://docs.docker.com/reference/compose-file/services/),
[internal network option](https://docs.docker.com/reference/compose-file/networks/) and
[Ollama container documentation](https://docs.ollama.com/docker), consulted 2026-09-29.
Container resource/digest/auth/runtime gates remain separately visible in the acceptance ledger.

## Troubleshooting and cleanup

| Symptom | Resolution |
|---|---|
| Local model lock missing | Provision deliberately, run `lock_models.py`, set `PAIS_MODEL_LOCK`; never switch to fixture silently |
| Digest changed | Restore the locked Ollama model or deliberately create a reviewed new lock/baseline |
| Reranker file hash mismatch | Re-download the pinned snapshot into a separate directory; do not edit the manifest to hide corruption |
| sqlite extension unavailable on macOS | Use a Python/SQLite build that supports extension loading; see [official Python binding notes](https://alexgarcia.xyz/sqlite-vec/python.html) |
| Embedding context exceeded | Source remains uncommitted; shorten chunks with a versioned configuration and reingest; truncation is disabled |
| Scanned PDF | Supply an OCR text-layer copy; no OCR capability is claimed here |
| API health works but protected requests return 503 | Inspect required P06 validator readiness; local data protection fails closed |
| Local demo succeeds, offline runner exits 2 | The execution boundary has not passed offline criteria; provision an isolated namespace/VM |

Temporary demo databases are removed after each demo. Downloaded models and API state are
persisted separately. Teardown stops only owned processes. Deleting model/state directories
is a separate explicit operator action; preserve the model lock and evidence first.

Read the [case study](case-study.md) and [interview walkthrough](interview.md).
