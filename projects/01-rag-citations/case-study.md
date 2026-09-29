# Case study — source integrity before fluent generation

## Problem and decision

An operations assistant can sound plausible while citing the wrong revision of a policy,
an unrelated page, or a span that does not support its claim. This implementation makes
the immutable PDF version and original extracted page text the evidence authority. Search
indexes can be rebuilt. Citations cannot silently move when someone uploads a replacement.

The first local model run was useful precisely because it failed. The model copied a whole
paragraph into `quote` while the validator required a complete individual assertion. The
right response was to constrain generation to sentence IDs and bind those IDs back to exact
spans. Allowing loose quotation matching would have weakened the boundary we needed to prove.

A second model run showed a separate failure: an answerable two-page question produced
an empty selection. An explicit positive selection example corrected that behavior on the
development demo. The [successful local report](evidence/local-sqlite-selection-v2.json)
passes 13/13 behavior checks in 24.06 seconds, with a 628,676 KiB Python process high-water RSS.
Ollama is a separate process, so that number is not total stack memory.

## What the evidence means

The successful cross-page model output selected four short sentence IDs, including the
two requested facts and two additional supported facts. This proves real model selection,
source binding and successful citation validation; it does not establish ideal answer
precision. The conflict question selected only one side. The independent structural source
check supplied the opposing validated assertion and recorded that it had done so.

The [actual local retrieval comparison](evidence/local-retrieval.json) subsequently ran 16
frozen development queries. Lexical recall@5 was 0.9375; dense, hybrid and hybrid plus
reranking each achieved 1.0 recall and 0.96875 MRR. Mean latency was 1.93, 275.42, 282.59 and
350.32 ms respectively. Reranking did not improve this small corpus's metrics. All eight
grounding development cases passed. The fixture comparison remains separate evidence of
deterministic pipeline behavior, not semantic quality.

The broader release run exposed another honest limit of small-model selection: it omitted
pages from explicit document summaries. The summary path now compiles bounded, validated
source excerpts in page-balanced order and reports its deterministic assembly identity.
It makes no model-generation claim. Ordinary question answering still invokes Ollama.

## Alternatives rejected

- **Citation by filename and page only:** insufficient to preserve what the model actually used
  after replacement. We retain immutable versions and exact supporting spans.
- **Cosine similarity as claim support:** similarity is useful for candidate discovery, not
  verification of a statement's number, negation or complete context.
- **Free-form generation plus an LLM saying “supported”:** a second opinion can fail for the
  same reasons. This small application deliberately returns validated extractive assertions.
- **Global vector top-k followed by tenant filtering:** authorized evidence can be crowded out
  by another tenant's nearer vectors. Both actual adapters filter before top-k.
- **Pretending SQLite and Lance share a transaction:** they do not. Source commit, invalidated
  checkpoint and serialized repair make that boundary visible and recoverable.

## Remaining engineering work

Semantic relevance, paraphrase support and nuanced contradictions need a larger domain
dataset and validated models. The current source conflict detector handles the same predicate
with incompatible quantities or negation, including equivalent time-unit normalization.
Generic summaries resolve document scope separately from ordinary question grounding and
disclose that only retrieved excerpts are summarized. Deployment would additionally need
parser isolation, operating load measurements, retention/backups policy and broader adversarial testing.
