# Evaluation data and release contract

`release.json` contains 144 individually identified scenarios across nine categories.
They include 32 distinct operational concepts, 16 two-page questions, 16 absent-information
questions, eight conflicting-current-source pairs, and independent citation, authorization,
malformed input, adversarial and persistence mutations. Source documents are original
synthetic MIT-licensed data in `corpus.json`. These are fictional operating policies.

`development.json` and `audit.json` use different source documents. Training/benchmark source
groups live in their projects and must never ingest these data. The source generator is
`scripts/build_eval_dataset.py`; PDF generation consumes corpus pages only. Questions,
expected answers and oracle metadata never enter the model prompt or retrieval index.

The public release suite is a regression suite, not an unseen generalization benchmark.
The eight audit cases are a small source-separated smoke check, not a blind quality
benchmark. They reuse the development inspection-interval template and numeric values
with renamed subjects, so they provide little distribution shift. Audit executions are
logged under `artifacts/evals/audit-exposures.jsonl`; direct source reads are not captured
by that execution log. Prior source inspection and repeated execution must be disclosed.

Metrics: a real DeepEval custom BaseMetric evaluates exact supporting evidence; RAGAS
ExactMatch scores structured expected decisions (authorization/abstention/etc.). Raw term
coverage, citation page recall, retrieval ranks, latency and actual model metadata are
retained separately. These deterministic metrics do not establish broad semantic quality.
No model judge is used for the release gate: there is therefore no uncalibrated LLM judge
masquerading as ground truth. Optional future model judges must add a reviewed calibration
set and version their agreement/false-acceptance rates before they can affect release.

`thresholds.json` is declared before the first quality run. A missing required package,
model, metric failure, incomplete suite, mandatory skip or failed case prevents promotion.
Fixture pass status never permits a local-model or deployment release. External LangSmith
dataset/run integration has an independent status and requires configured credentials.

Known compatibility decision: RAGAS0.3.9 and0.4.3 both import a removed VertexAI module in
LangChain Community0.4.2. Both initial imports failed. An older-family isolated runtime first
restored execution. The final lock uses DeepEval4.2.6 and RAGAS0.4.3 with Community0.3.31,
LangChain1.4.3/Core1.6.5/OpenAI1.6.6. Community0.3.31 retains that import path. Actual replay
of144 preserved release observations produced432 identical metric values before adoption;
the remaining RAGAS/DiskCache advisories are disclosed in `docs/dependencies/AUDIT.md`.
No unreviewed import shim or missing metric was used to create a pass. Reference APIs:

- https://deepeval.com/docs/metrics-custom
- https://docs.ragas.io/en/v0.3.9/concepts/metrics/available_metrics/traditional/
- https://docs.ragas.io/en/stable/references/metrics/
- https://docs.smith.langchain.com/evaluation/how_to_guides/manage_datasets_programmatically
