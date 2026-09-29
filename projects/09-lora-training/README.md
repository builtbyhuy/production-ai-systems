# P09 — Provenance-aware LoRA SFT/DPO

**Status: implemented; genuine CPU training smoke verified; substantive fine-tuning and capability retention remain unverified.** The measured random model achieved **0% exact match** on both held-out suites before SFT, after SFT, and after DPO. The retention gate rejected promotion because each suite has only six held-out examples; the prospective minimum is twenty.

## Problem and scope

Fine-tuning can produce an adapter file while silently accepting contaminated examples, inconsistent preferences, truncated targets, or degraded capabilities. This project makes those conditions explicit and refuses a release when required evidence is absent. Its functional demonstration exercises real optimization with PEFT, Transformers, Datasets, and TRL on a tiny model initialized locally.

The implementation is [training.py](../../packages/pais/training.py). It validates instruction/preference records, deduplicates, groups source identities into reproducible train/development/test splits, checks known evaluation exclusions, builds tokenization, trains a LoRA SFT adapter, exports and reloads it, then trains DPO against a frozen SFT reference. Base/SFT/DPO are evaluated on the same held-out domain and general suites.

## Setup and commands

Run from the repository root with Python 3.12:

```bash
uv sync --project projects/09-lora-training --locked
PYTHONPATH=packages .venv/bin/python -m pais.training fixture --output artifacts/p09-fixture
PYTHONPATH=packages projects/09-lora-training/.venv/bin/python -m pais.training smoke --output artifacts/p09-smoke-reproduction
.venv/bin/python -m pais demo 09 --profile local --output artifacts/p09-cli-reproduction/run.json
.venv/bin/pytest -q tests/test_training.py
```

Choose a fresh output directory for each run; existing evidence is never overwritten. The isolated environment pins torch **2.8.0+cpu**, Transformers **4.56.2**, PEFT **0.17.1**, Datasets **4.1.1**, TRL **0.23.1**, Accelerate **1.10.1**, Tokenizers **0.22.0**, and Safetensors **0.6.2**. `uv.lock` also fixes transitive dependencies. The explicit PyTorch CPU index avoids CUDA downloads. Invoking training from the repository's different Transformers environment produces a prerequisite error, exit code 2.

The isolated environment also declares Pydantic because the common `pais demo` entrypoint
imports the shared evidence/contracts layer before dispatching training. A final integration
run exposed this missing declaration before training began; its failure log is preserved in
`artifacts/final/p09-local.log`. The dependency correction is a separate source commit from
the application release gate. Its actual CLI reproduction has its own source identity and
does not make a successful smoke a substantive model-quality release.

All Hugging Face loading uses locally provisioned files, `local_files_only=True`, `trust_remote_code=False`, and Safetensors. Hub/dataset telemetry and automatic Hub access are disabled before ML imports. These application settings prevent hidden Hugging Face downloads; a deployment that promises network isolation must additionally enforce it at the operating-system boundary.

## Architecture and data flow

1. Read the 60 original MIT-licensed records and verify their byte hash. Validate source revision/license, SFT completion, chosen/rejected alternatives, and a criterion-linked preference rationale.
2. Read P04 release/development/audit/corpus data and the entire P17 task release solely to derive exclusion hashes and source identifiers. Reject known overlap. Source grouping and a seeded hash order produce 36 training, 12 development, and 12 test examples.
3. Fit the smoke tokenizer using only training prompts and preference alternatives. Reject truncated targets and alternatives that become identical after tokenization.
4. Initialize GPT-2 with two layers, two attention heads, hidden size 32 and 128 positions. Fit rank-four LoRA on `c_attn`, with the GPT-2 Conv1D orientation explicitly configured.
5. Train SFT for three optimizer steps; prove adapter parameters changed and frozen backbone parameters did not. Export Safetensors, reload on a fresh base, and compare logits to tolerance `1e-6`.
6. Load the SFT policy again for DPO. Build an independent frozen, merged SFT reference. Train three DPO steps, prove adapter changes, export/reload, and evaluate the identical held-out suites.
7. Record all predictions, completion NLL, exact match, training logs, checkpoints, artifact hashes and the release decision.

The final step count is fixed before the smoke; there is no test-set checkpoint selection. Development data is reserved for a future predeclared selection procedure. The current run writes optimizer/scheduler/trainer checkpoints and hashes them; automated crash-resume selection is not claimed.

## Measured result

The committed-size [EVIDENCE.json](EVIDENCE.json) summary derives from [training-result.json](../../artifacts/p09-smoke/training-result.json), timestamp **2026-09-29T09:22:07Z**, Python **3.12.14**, Linux x86-64, two PyTorch threads. It used 39,456 base parameters, 1,024 trainable adapter parameters and a 309-token vocabulary. The host allocation was 8 GiB RAM and eight CPU quota; the configured run used no GPU and downloaded no model weights. Raw artifacts are generated locally and excluded from Git; the summary retains their digests and measured values.

| Stage | Domain exact match, n=6 | General exact match, n=6 | Domain mean completion NLL | General mean completion NLL |
|---|---:|---:|---:|---:|
| Random base | 0% | 0% | 5.793780 | 5.737118 |
| SFT | 0% | 0% | 5.787117 | 5.721899 |
| DPO | 0% | 0% | 5.784540 | 5.708778 |

SFT training loss was **5.716662** and DPO loss was **0.692596**. Those are different objectives and must not be compared as one quality scale. Recorded optimizer time was about **0.282 s** per stage and measured pipeline time after imports/setup was **1.182 s**. These timings describe this tiny fixture workload, not pretrained-model throughput. Both adapter reloads had **0.0 maximum logit difference**. NLL changes do not establish useful answers: every exact-match score remained zero.

## Full local training prerequisites

`train --config PATH --output FRESH_DIRECTORY` also supports an already provisioned small local model snapshot. [local-snapshot.example.json](configs/local-snapshot.example.json) is an explicitly incomplete input template. Fill its existing model path, immutable revision, license, artifact SHA-256 mapping, appropriate LoRA target modules, and reviewed dataset path. The supplied dataset schema must still include both suites and source identities. The pipeline forbids automatic model downloads and rejects snapshots with missing or mismatched hashes.

Substantive acceptance additionally needs a suitable pretrained model, a justified training budget, a substantially larger independent domain/general evaluation set, and actual baseline/SFT/DPO evidence. The verified runtime is CPU only. Larger GPU configurations and their memory requirements have not been executed. LoRA does not guarantee freedom from forgetting.

Read [DATA_CARD.md](DATA_CARD.md), [ACCEPTANCE.md](ACCEPTANCE.md), [CASE_STUDY.md](CASE_STUDY.md), and [INTERVIEW.md](INTERVIEW.md) for provenance, exact remaining gates, decisions and walkthrough.

## Compatibility sources

The conservative pinned APIs were checked against official versioned documentation on 2026-09-29. They are intentionally pinned and are not presented as the latest releases.

- [TRL 0.23.1 SFTTrainer and SFTConfig](https://huggingface.co/docs/trl/v0.23.1/en/sft_trainer): `processing_class`, completion-only loss, PEFT models and saved checkpoints.
- [TRL 0.23.1 DPOTrainer](https://huggingface.co/docs/trl/v0.23.1/en/dpo_trainer): preference schema, explicit reference model and PEFT behavior.
- [PEFT quicktour](https://huggingface.co/docs/peft/main/quicktour): adapter saving/loading; actual 0.17.1 behavior was exercised in the smoke.
- [Transformers GPT-2 implementation](https://github.com/huggingface/transformers/blob/v4.56.2/src/transformers/models/gpt2/modeling_gpt2.py): model configuration and causal-language-model labels.
