# P01 — Versioned PDF RAG with validated citations

This project answers technical operations questions from authorized PDFs while preserving
the exact document version, physical page, printed page label when declared, and text span
used for every assertion. A LangGraph graph retrieves evidence, routes QA through the selected model,
validates its selections, and either returns supported source assertions or abstains.

**Current evidence:** the real local SQLite demonstration passes all 13 behavior checks in
[local-sqlite-selection-v2.json](evidence/local-sqlite-selection-v2.json). The earlier
[sentence-selection failure](evidence/local-sqlite-selection.json) is preserved. Fixture
contracts exercise both actual vector stores; fixture models do not measure semantic quality.
See [acceptance.md](acceptance.md) for the remaining verification boundaries.

## Run

From the repository root, install the locked environment. The `vectors` extra permits
both storage adapters without installing local inference; `local` includes the CPU model runtime.

```bash
uv sync --frozen --group dev --extra local
.venv/bin/python projects/01-rag-citations/demo.py --profile fixture --backend sqlite
.venv/bin/python projects/01-rag-citations/demo.py --profile fixture --backend lancedb
.venv/bin/python -m pytest -q tests/test_rag_service.py tests/test_rag_models.py tests/test_retrieval_adapters.py
```

Provision and lock the models with [P07's instructions](../07-local-first/README.md), then:

```bash
.venv/bin/python scripts/with_local_models.py -- .venv/bin/python projects/01-rag-citations/demo.py --profile local --backend sqlite --output artifacts/p01-local.json
.venv/bin/python scripts/with_local_models.py -- .venv/bin/python projects/01-rag-citations/demo.py --profile local --backend sqlite --evaluate --output artifacts/p01-retrieval-local.json
```

`--evaluate` compares lexical, dense, hybrid and hybrid plus reranking on the same frozen
[synthetic corpus](retrieval_dataset.json). `--retrieval-only` avoids generation during the
comparison. Missing models/dependencies return exit 2; failed acceptance checks return exit 1.
There is no automatic fallback from local inference to fixtures.

## Architecture and exact behavior

| Stage | Implementation | Boundary |
|---|---|---|
| Ingestion | pypdf extraction; original PDF bytes, SHA-256, immutable versions and pages in SQLite | Encrypted, malformed, empty and image-only PDFs fail explicitly; OCR is not implemented |
| Chunking | Page-local spans, 600-character target, up to 80 characters of whole-sentence overlap | Offsets refer to the unnormalized extracted page text |
| Lexical retrieval | SQLite FTS5 with Porter/Unicode tokenization | A quoted term query prevents user text from becoming FTS syntax |
| Dense retrieval | sqlite-vec cosine search by default; optional local LanceDB | Tenant filtering occurs before top-k; returned IDs are reauthorized against active SQLite rows |
| Fusion | Reciprocal rank fusion, `sum(1/(60+rank))`, one-based ranks | Raw BM25 and cosine scales are never averaged |
| Reranking | CPU `CrossEncoder`, pinned MS MARCO MiniLM-L6 checkpoint | Actual model scalar scores are recorded; the verified checkpoint emits raw logits, not probabilities |
| QA generation | Local Ollama selects short sentence IDs under a JSON schema | IDs bind to exact original source sentences; generated text cannot rewrite source facts |
| Explicit summaries | Bounded, deterministic assembly of validated excerpts, balanced across retrieved pages | Reported as `extractive:page-balanced-v1`, with no claim that a model generated the summary |
| Validation | Existence, exact page/span, then whole-sentence extractive support | A correct-looking substring does not establish support for an altered claim |
| Final answer | Validated assertions with numbered citations, conflict details, or abstention | Invalid generated claims invalidate the answer; independently validated source conflicts remain visible |

Ordinary question answering requires at least 0.25 content-term coverage and a reranker
score of at least 0.20 in the verified local configuration. Those are initial development
operating points, not calibrated probabilities. The [versioned thresholds](thresholds.json)
were recorded before measurement; the release dataset remains separate.

Explicit document summaries use a different scope decision: matching document filenames
or matching excerpt topics identify the requested sources. A generic request can summarize
the retrieved authorized excerpts even without a literal question word in the text. The
summary route assembles one complete validated assertion per retrieved page, then adds
assertions in page-balanced rounds up to eight. It records the available/represented page
counts and `real_inference=false` for this assembly stage; ordinary QA still invokes the
actual model. The answer says it summarizes **retrieved excerpts**, because the evidence
limit can omit part of a long corpus. Ordinary QA thresholds are unchanged.

## Measured retrieval result

The [actual local comparison](evidence/local-retrieval.json) used 16 queries and the same
frozen synthetic corpus for all methods. These are single-run development measurements.

| Method | Page recall@5 | MRR | nDCG@5 | Mean retrieval latency |
|---|---:|---:|---:|---:|
| Lexical | 0.9375 | 0.9375 | 0.9375 | 1.93 ms |
| Dense | 1.0000 | 0.9688 | 0.9769 | 275.42 ms |
| Hybrid | 1.0000 | 0.9688 | 0.9769 | 282.59 ms |
| Hybrid + reranking | 1.0000 | 0.9688 | 0.9769 | 350.32 ms |

Reranking added latency and did not improve these metrics on this small corpus. The
0.90 local recall target was met, and all eight grounding development cases passed. This
does not establish that reranking is universally useful or that the system meets a
production domain's quality needs.

The conflict detector compares the same textual predicate with changed quantities or
negation. It normalizes seconds/minutes/hours/days; 60 seconds and one minute agree.
Different or unknown units remain a discrepancy for human review. This is deliberately a
limited structural check, not a general natural-language contradiction classifier. It
checks source assertions independently of the generator so the model cannot silently
choose one side of a recognized conflict.

## Durable state and recovery

Replacement creates a new version and retires the prior version from retrieval. Prior
citations still resolve to their original bytes and spans. Duplicate active uploads return
the existing version, including concurrent identical uploads. Deletion removes all versions
from authorized access and invalidates their citations; this is logical application deletion,
not a promise of forensic erasure from filesystem snapshots or backups.

SQLite source state is authoritative for both backends. A source transaction increments a
tenant index revision and invalidates the derived-index checkpoint. After commit, index
repair runs under a SQLite write lock. A crash during Lance replacement leaves no completed
checkpoint, so the next access rebuilds the index from committed sources. Count mismatches
also trigger repair. This serializes repair and reads and is appropriate for the small local
workload; it is not a claim of distributed index atomicity or high write concurrency.

## Public integration

`RAGService(db_path, profile='fixture', backend='sqlite')` provides `ingest`, `answer`,
`search`, `validate_citation`, `list_documents`, `get_pdf`, and `delete` exactly as specified
in [CONTRACTS.md](../../docs/CONTRACTS.md). Every operation accepts a trusted `Principal`.
Readers and writers may read; writers and admins may mutate. No tenant header grants authorization.

Citation support is intentionally extractive: `claim` must equal one complete source
sentence and preserve its negation, numbers and context. Arbitrary paraphrases fail this
validator. A cited assertion can still be wrong in the source document. Applications must
not present source validation as external truth verification.

## Known limits

- Text extraction is strongest on ordinary text-layer PDFs. There is no OCR, table layout
  interpretation, or multilingual quality claim. Extremely long individual sentences may
  be chunked and subsequently rejected by the whole-sentence validator.
- PDF size/page/text caps do not constitute a hostile PDF parser sandbox. Deployment
  isolation is a separate gate; the local parser has not passed decompression-bomb testing.
- Injection quarantine uses transparent patterns plus an untrusted-data model instruction.
  It is a defense layer; the integrated API also applies P06 output/security controls.
- Retrieval latency includes reranking; the nested reranking stage is also measured.
  Buffered generation cannot provide provider TTFT. Reported token usage is used when
  available; missing usage is unknown, never zero.
- The small model sometimes selects extra supported sentences. Verbatim grounding and
  question relevance are separate quality dimensions.

See the [case study](case-study.md), [interview walkthrough](interview.md), and
[official API/revision notes](sources.md).
