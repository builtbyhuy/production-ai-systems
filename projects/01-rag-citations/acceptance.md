# P01 acceptance and evidence

Implementation and acceptance evidence are tracked separately. A green fixture result is
not local-model quality evidence, and a local process run is not a deployment performance test.

| Criterion | Status | Evidence |
|---|---|---|
| Real PDF extraction with physical page, printed label and exact span | Pass, actual pypdf | `tests/test_rag_service.py::test_page_offsets_and_printed_page_labels` |
| Real SQLite FTS5, sqlite-vec and LangGraph graph | Pass | [local SQLite demo](evidence/local-sqlite-selection-v2.json) |
| Real local generation, embedding and cross-encoder reranking | Pass | Same report includes model digests/revision, raw generation and actual rerank values |
| Cross-page answer, unanswerable request, injection quarantine, conflicts | Pass, selected local demo | All 13 behavior checks pass in the local report |
| Replacement, old citation stability, delete invalidation, duplicate uploads | Pass | Local demo and both-backend fixture contracts |
| Incorrect page/span/claim rejected; whole-sentence support enforced | Pass | Local negative page test and five forged-citation test variants |
| Generic summaries, filename scope, cross-unit discrepancies | Pass, development fixtures | `test_rag_service.py`; real release coverage is reported by P04 |
| Same-dataset lexical/dense/hybrid/reranked comparison | Pass, actual local models | [local comparison](evidence/local-retrieval.json): 16 queries, recall@5 1.0 for dense/hybrid/rerank; 8/8 grounding dev cases correct |
| Source-index interrupted write recovery | Pass, both storage implementations | `test_derived_index_failure_is_repaired_from_committed_source` |
| Deployment load, hostile PDF process isolation, broad semantic conflict detection | Not run/not implemented as applicable | See README limitations; no completion claim for these capabilities |

## Failure evidence retained

The first real local generation copied several sentences into one `quote`; the strict
whole-sentence validator rejected it. The next sentence-ID run still abstained on an
answerable cross-page question: [local-sqlite-selection.json](evidence/local-sqlite-selection.json).
The successful follow-up used a positive selection example and clearer multi-part guidance,
without weakening citation support: [local-sqlite-selection-v2.json](evidence/local-sqlite-selection-v2.json).

Root P04 also preserves its first fixture release result (120/144): generic document
summaries and differing-unit conflicts exposed real gaps. Fixes were developed with new
warehouse/queue/gateway examples, not by altering the frozen release cases or their oracle.
The first full actual local run (132/144) then exposed incomplete model-selected summaries.
Explicit summaries now use disclosed, page-balanced source-excerpt assembly; ordinary QA
continues to invoke the real model. P04 owns the subsequent full release result.

## Reproduce contract evidence

```bash
.venv/bin/python -m pytest -q tests/test_rag_service.py tests/test_rag_models.py tests/test_retrieval_adapters.py
.venv/bin/python projects/01-rag-citations/demo.py --profile fixture --evaluate --output artifacts/p01-fixture-retrieval.json
```

The project demo entrypoints create manifests with timestamps, the exact command,
source snapshot, commit/dirty state, installed versions, dataset hash, model lock,
configuration, exit status and process resource measurements. Results saved before
later fixes remain historical snapshots, not proof of the final code tree.
