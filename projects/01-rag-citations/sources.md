# Official API and compatibility notes

Researched 2026-09-29. These URLs informed API choices; the evidence manifests record the
exact installed dependency versions and model file hashes used in each executed run.

| Source | Implementation decision |
|---|---|
| [sqlite-vec Python bindings](https://alexgarcia.xyz/sqlite-vec/python.html) | Load the extension on each connection, disable extension loading afterward, and serialize normalized float32 vectors |
| [sqlite-vec metadata and KNN filters](https://alexgarcia.xyz/sqlite-vec/features/vec0.html) | Store tenant identity in the vec0 metadata and constrain it inside KNN search |
| [SQLite FTS5](https://sqlite.org/fts5.html) | Use actual FTS5/BM25 with data-only quoted query terms; do not average BM25 with cosine distance |
| [pypdf extraction](https://pypdf.readthedocs.io/en/stable/user/extract-text.html) | Preserve extraction text/page provenance; do not pretend pypdf performs OCR |
| [LangGraph graph API](https://docs.langchain.com/oss/python/langgraph/graph-api) | Compile a real StateGraph with retrieval, generation, validation and finalization nodes |
| [Ollama embed endpoint](https://docs.ollama.com/api/embed) | `/api/embed`, batched input, `truncate=false`, explicit dimension validation and provider failure propagation |
| [Ollama generate endpoint](https://docs.ollama.com/api/generate) | JSON-schema constrained selection, `stream=false`, actual usage and finish status captured |
| [CrossEncoder API](https://sbert.net/docs/package_reference/cross_encoder/model.html) | Actual pairwise reranking on CPU, `local_files_only=true`, `trust_remote_code=false` and bounded batch/context |
| [LanceDB vector search](https://docs.lancedb.com/search/vector-search/) | Separate local Arrow/Lance storage, cosine metric and prefiltering under the same adapter contract |
| [LanceDB Python API](https://lancedb.github.io/lancedb/python/python/) | Separate `create_table`, `add`, `delete`, `where` and local persistence implementation |

## Model revisions

The verified local stack uses `qwen2.5:1.5b` and `all-minilm:22m`; full Ollama manifest
digests are read from `/api/tags` and checked against `PAIS_MODEL_LOCK` before inference.
The model labels are [official Qwen 1.5B](https://ollama.com/library/qwen2.5:1.5b) and
[official MiniLM 22M](https://ollama.com/library/all-minilm:22m) distributions.

The reranker is `cross-encoder/ms-marco-MiniLM-L6-v2` at immutable revision
`233902d25c440f23af6f7d6e94d2946bac0bee0a`, downloaded and locked as safetensors. The earlier
verified tree revision `fbf9045f293a58fa68636213c5e0cb8a2de5d45e` exposed only legacy PyTorch
weights for the selected download pattern. Provisioning changed to the verified safetensors
revision; this was a compatibility/integrity choice before the successful model run.

The installed model and Sentence Transformers configuration emits raw scalar relevance
logits. A value of 0.20 is an operating threshold on those scores, not 20% confidence.
Changing the model, embedding dimension or score activation requires an explicit new
configuration/baseline. A changed embedding identity is rejected when opening an existing database.
