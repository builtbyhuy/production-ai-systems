# Interview walkthrough — P01

Start with the actual local report and show the raw `sentence_ids` output, the supplied
bindings, the selected physical pages, the real rerank scores and the three citation checks.
Explain which source assertions came from model selection and which opposing conflict
assertion was added by the independent validator.

## Code path to explain

1. `RAGService.ingest` validates role and replacement ownership, extracts pages before writing,
   embeds bounded chunks, then commits a new source version. Concurrent duplicate checks run
   again under the write transaction. An embedding failure leaves the active version unchanged.
2. `_refresh_fts_and_revision` replaces the tenant's active lexical entries and invalidates
   derived-index checkpoints. `_ensure_index` is a separate repair phase after authority commits.
3. `_search_impl` constructs a data-only FTS expression, performs tenant-filtered vector search,
   combines ranks with RRF, reauthorizes active chunk IDs and invokes the actual reranker.
4. LangGraph branches from retrieval directly to abstention when evidence is insufficient.
   A generated sentence ID must belong to the supplied evidence set; an invented ID fails.
   Explicit document summaries take a separate, disclosed page-balanced excerpt assembly
   route; its model field and evidence explicitly report that no model generated the summary.
5. `validate_citation` verifies source identity, physical page/label/span and the complete
   extractive assertion. Replacing a PDF does not rewrite old citations; deleting it removes access.

## Questions you should answer without memorizing a script

- Why do we need both a PDF content hash and a version ID?
- Why does a matching substring fail to validate “allowed” when the full source says “not allowed”?
- Why are cross-encoder scores not automatically probabilities?
- Why can an explicit summary use the filename to choose a document, while an ordinary factual
  question cannot use the filename as evidence for an answer?
- What happens if Lance replacement succeeds but the process crashes before its checkpoint?
- What concurrency and throughput cost does the repair/read serialization impose?
- What changes if the source documents are twenty times longer, scanned, or multilingual?

## Small modifications to demonstrate yourself

Add a new operating policy PDF, ask a multi-page question, then replace and delete the policy.
Create a dev test for a changed number or a dropped negation and show the correct validation
level failing. Add a supported unit conversion to `_conflict_groups`, test both disagreement
and equality, and explain why arbitrary natural-language contradiction detection remains out of scope.

Do not claim OCR, perfect injection detection, free-form semantic entailment or production
load capacity. Those are explicitly separate capabilities and gates.
