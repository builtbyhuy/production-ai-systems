# P09 interview walkthrough

Start with the result: genuine SFT/DPO, successful reloads, **zero correct held-out answers**, and a rejected release. Explain why loss movement and operational success are not the same as an improved assistant.

1. Open `prepare_dataset`. Trace schema checks, chosen/completion consistency, rationale validation, exact duplicate handling, source grouping and exclusion hashes. Explain why different sources carrying the same instruction are rejected instead of randomly split.
2. Open `collect_exclusions` and the recorded manifest. Identify P04 release/audit content and P17 task text. Describe the narrow hash/overlap access and the limitations of exact or trigram overlap detection.
3. Follow `_build_tiny_model` and `validate_tokenization`. Explain why a train-only tokenizer avoids fitting on held-out text, why it can make held-out labels unknown, and why this is only a smoke model.
4. Trace `get_peft_model`, `SFTTrainer`, the frozen-weight comparison and `_export_reload`. Explain GPT-2's `c_attn` target and `fan_in_fan_out`, which tensors update, and why Safetensors plus an explicit base revision matter.
5. Trace DPO's separate policy and frozen merged SFT reference. Explain chosen/rejected likelihood comparison at a high level and why an original-base reference would be a different experiment.
6. Open `retention_gate`. Demonstrate rejection for a general-score regression, changed suite hash or count, missing/nonfinite NLL and insufficient cases. Explain why a twenty-case floor does not prove statistical adequacy.

Be able to make these changes yourself:

- Add a correctly licensed independent source with a verifiable preference rationale and prove its full source group stays in one split.
- Add a forbidden release example and show training fails before optimization.
- Reduce `max_length` until a target would be truncated and show the run rejects it.
- Change the predeclared general retention tolerance with a written workload rationale and compare it to the prior version.
- Provision a small existing local model, record every model file hash and correct its LoRA target modules.

Do not claim a successful pretrained fine-tune, broad retention, statistical power, GPU performance, automatic checkpoint recovery, or production deployment. Those are separate experiments and remaining gates.
