"""P09: provenance-aware LoRA SFT/DPO and retention gates in an isolated ML env.

The built-in CPU smoke initializes a tiny random model locally. It verifies real
optimization, checkpoint/export/reload and identical-suite evaluation. It does not
measure the usefulness of a pretrained assistant or establish substantive gains.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import re
import shutil
import subprocess
import sys
import time
import unicodedata
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
PROJECT = ROOT / "projects/09-lora-training"
DATA_PATH = PROJECT / "data/ops-instructions-v1.jsonl"
DATA_SHA256 = "6652a2bc386a68c9feb5a8dc5613cb8c75a30ab743da47dcb44c7b29cde56f9c"
LICENSES = {"MIT", "Apache-2.0", "CC0-1.0", "CC-BY-4.0"}
CRITERIA = {
    "factuality",
    "authorization",
    "uncertainty",
    "privacy",
    "bounded_execution",
    "durability",
    "idempotency",
    "provenance",
    "completeness",
}
REQUIRED_VERSIONS = {
    "torch": "2.8.0+cpu",
    "transformers": "4.56.2",
    "peft": "0.17.1",
    "datasets": "4.1.1",
    "trl": "0.23.1",
    "accelerate": "1.10.1",
    "tokenizers": "0.22.0",
    "safetensors": "0.6.2",
}


class TrainingValidationError(ValueError):
    pass


class TrainingPrerequisiteError(RuntimeError):
    pass


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode()


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _normalize(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def text_fingerprint(text: str) -> str:
    return _sha(_normalize(text).encode())


def _source_split(sources: dict[str, str], seed: int) -> dict[str, str]:
    by_suite: dict[str, list[str]] = defaultdict(list)
    for source, suite in sources.items():
        by_suite[suite].append(source)
    result = {}
    for suite, groups in by_suite.items():
        if len(groups) < 5:
            raise TrainingValidationError(
                f"Suite {suite} requires at least five independent source groups"
            )
        groups.sort(key=lambda item: _sha(f"{seed}:{item}".encode()))
        train_end, dev_end = int(len(groups) * 0.6), int(len(groups) * 0.8)
        for index, source in enumerate(groups):
            result[source] = "train" if index < train_end else "dev" if index < dev_end else "test"
    return result


def _shingles(text: str) -> set[tuple[str, ...]]:
    tokens = _normalize(text).split()
    return {tuple(tokens[index : index + 3]) for index in range(max(0, len(tokens) - 2))}


def prepare_dataset(
    rows: list[dict],
    forbidden_fingerprints: set[str] | None = None,
    forbidden_source_ids: set[str] | None = None,
    split_seed: int = 20260929,
) -> dict:
    forbidden_fingerprints = forbidden_fingerprints or set()
    forbidden_source_ids = forbidden_source_ids or set()
    if not isinstance(rows, list) or not rows:
        raise TrainingValidationError("Dataset must contain instruction/preference records")
    seen_ids, seen_prompts, sources, clean, duplicates = set(), {}, {}, [], 0
    required = {
        "id",
        "source_id",
        "source_revision",
        "license",
        "provenance",
        "suite",
        "prompt",
        "completion",
        "chosen",
        "rejected",
        "rationale",
        "criterion",
    }
    for row in rows:
        if not isinstance(row, dict) or set(row) != required:
            raise TrainingValidationError(
                "Each record must follow the exact instruction/preference schema"
            )
        if any(not isinstance(value, str) or not value.strip() for value in row.values()):
            raise TrainingValidationError("All record fields must be nonempty strings")
        if row["id"] in seen_ids or not re.fullmatch(r"[a-zA-Z0-9_.:/-]{1,160}", row["id"]):
            raise TrainingValidationError("Duplicate or invalid example id")
        seen_ids.add(row["id"])
        if (
            row["license"] not in LICENSES
            or len(row["provenance"]) < 20
            or not row["source_revision"]
        ):
            raise TrainingValidationError("Unreviewed license or incomplete source provenance")
        if row["license"] == "CC-BY-4.0" and "attribution:" not in row["provenance"].lower():
            raise TrainingValidationError("Attribution is required for CC-BY data")
        if row["suite"] not in {"domain", "general"}:
            raise TrainingValidationError("Every source must declare domain or general suite")
        if row["criterion"] not in CRITERIA or len(row["rationale"].split()) < 8:
            raise TrainingValidationError(
                "Preference pairs need a substantive criterion-linked rationale"
            )
        if (
            " ".join(row["chosen"].split()) == " ".join(row["rejected"].split())
            or row["chosen"] != row["completion"]
        ):
            raise TrainingValidationError(
                "Chosen/rejected answers must differ and SFT completion must match chosen"
            )
        if any(
            len(row[field].encode()) > 16_384
            for field in ("prompt", "completion", "chosen", "rejected")
        ):
            raise TrainingValidationError("Example exceeds bounded text length")
        if row["source_id"] in forbidden_source_ids:
            raise TrainingValidationError("A benchmark/release source is present in training data")
        # Short answer labels alone are not an example identity: common numbers
        # and yes/no labels occur legitimately across unrelated tasks. All prompts,
        # prompt+answer identities, and substantive response text are checked.
        fingerprints = {
            text_fingerprint(row["prompt"]),
            text_fingerprint(row["prompt"] + "\n" + row["completion"]),
        }
        fingerprints.update(
            text_fingerprint(row[field])
            for field in ("completion", "chosen", "rejected", "rationale", "provenance")
            if len(row[field]) >= 32
        )
        if fingerprints & forbidden_fingerprints:
            raise TrainingValidationError(
                "Known evaluation/benchmark content overlaps an instruction or preference record"
            )
        prompt = text_fingerprint(row["prompt"])
        if prompt in seen_prompts:
            previous = seen_prompts[prompt]
            if previous["source_id"] != row["source_id"]:
                raise TrainingValidationError("Duplicate prompt spans different source groups")
            if any(previous[field] != row[field] for field in ("chosen", "rejected", "criterion")):
                raise TrainingValidationError(
                    "The same instruction has conflicting preference labels"
                )
            duplicates += 1
            continue
        seen_prompts[prompt] = row
        if row["source_id"] in sources and sources[row["source_id"]] != row["suite"]:
            raise TrainingValidationError("A source cannot cross domain/general suites")
        sources[row["source_id"]] = row["suite"]
        clean.append(dict(row))
    if set(sources.values()) != {"domain", "general"}:
        raise TrainingValidationError("Both domain and general-capability sources are required")
    split_map = _source_split(sources, split_seed)
    shingles = [(row, _shingles(row["prompt"])) for row in clean]
    for index, (left, left_shingles) in enumerate(shingles):
        for right, right_shingles in shingles[index + 1 :]:
            if (
                split_map[left["source_id"]] == split_map[right["source_id"]]
                or len(left_shingles) < 8
                or len(right_shingles) < 8
            ):
                continue
            similarity = len(left_shingles & right_shingles) / len(left_shingles | right_shingles)
            if similarity >= 0.9:
                raise TrainingValidationError(
                    "Near-duplicate prompts cross splits; group their sources before splitting"
                )
    splits = {
        name: sorted(
            (row for row in clean if split_map[row["source_id"]] == name), key=lambda row: row["id"]
        )
        for name in ("train", "dev", "test")
    }
    manifest = {
        "dataset_version": "ops-instructions-v1",
        "dataset_sha256": _sha(_canonical(clean)),
        "split_seed": split_seed,
        "split_policy": "source-grouped, hash-sorted, stratified by domain/general; 60/20/20",
        "counts": {name: len(part) for name, part in splits.items()},
        "suite_counts": {
            name: dict(Counter(row["suite"] for row in part)) for name, part in splits.items()
        },
        "source_assignment": split_map,
        "split_sha256": {name: _sha(_canonical(part)) for name, part in splits.items()},
        "example_fingerprints": {
            name: [text_fingerprint(row["prompt"] + "\n" + row["completion"]) for row in part]
            for name, part in splits.items()
        },
        "licenses": sorted({row["license"] for row in clean}),
        "deduplicated_records": duplicates,
        "forbidden_fingerprint_count": len(forbidden_fingerprints),
        "forbidden_source_count": len(forbidden_source_ids),
        "contamination_limits": "Exact normalized and high-overlap trigram checks cannot prove absence of semantic paraphrases or prior pretraining exposure.",
    }
    return {"splits": splits, "manifest": manifest}


def load_builtin_rows() -> list[dict]:
    content = DATA_PATH.read_bytes()
    if _sha(content) != DATA_SHA256:
        raise TrainingValidationError(
            "Built-in training data hash changed without a version review"
        )
    return [json.loads(line) for line in content.splitlines() if line.strip()]


def collect_exclusions(paths: list[str | Path]) -> dict:
    fingerprints, source_ids, manifest = set(), set(), []

    def visit(value: Any):
        if isinstance(value, str):
            fingerprints.add(text_fingerprint(value))
        elif isinstance(value, list):
            for item in value:
                visit(item)
        elif isinstance(value, dict):
            if isinstance(value.get("source_id"), str):
                source_ids.add(value["source_id"])
            if isinstance(value.get("question"), str):
                terms = value.get("expected_terms", [])
                if isinstance(terms, list):
                    fingerprints.add(
                        text_fingerprint(value["question"] + "\n" + " ".join(str(x) for x in terms))
                    )
            for key, item in value.items():
                # Corpus objects may be keyed by source identity.
                if isinstance(item, dict) and "pages" in item:
                    source_ids.add(key)
                visit(item)

    for value in paths:
        path = Path(value)
        if not path.exists():
            raise TrainingPrerequisiteError(f"Required exclusion dataset not found: {path}")
        payload = path.read_bytes()
        parsed = (
            [json.loads(line) for line in payload.splitlines() if line.strip()]
            if path.suffix == ".jsonl"
            else json.loads(payload)
        )
        before = len(fingerprints)
        visit(parsed)
        manifest.append(
            {
                "path": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
                "sha256": _sha(payload),
                "new_text_fingerprints": len(fingerprints) - before,
            }
        )
    return {
        "fingerprints": fingerprints,
        "source_ids": source_ids,
        "manifest": manifest,
        "audit_access": "Hash/overlap access only; release and audit examples are excluded, never used for training, checkpoint selection or threshold tuning.",
    }


def builtin_exclusions() -> dict:
    return collect_exclusions(
        [
            ROOT / name
            for name in (
                "evals/release.json",
                "evals/development.json",
                "evals/audit.json",
                "evals/corpus.json",
                "projects/17-domain-benchmark/data/tasks-v1.jsonl",
            )
        ]
    )


def retention_gate(base: dict, sft: dict, dpo: dict, thresholds: dict) -> dict:
    required = {
        "minimum_cases_per_suite",
        "max_general_score_drop",
        "max_domain_score_drop",
        "max_nll_ratio",
    }
    if set(thresholds) != required:
        raise TrainingValidationError("Retention thresholds must be complete and explicit")
    if (
        type(thresholds["minimum_cases_per_suite"]) is not int
        or thresholds["minimum_cases_per_suite"] < 1
    ):
        raise TrainingValidationError("Minimum evaluation size must be positive")
    if any(
        type(thresholds[k]) not in {float, int} or not math.isfinite(thresholds[k])
        for k in required - {"minimum_cases_per_suite"}
    ):
        raise TrainingValidationError("Retention thresholds must be finite")
    if (
        any(
            not 0 <= thresholds[k] <= 1 for k in ("max_general_score_drop", "max_domain_score_drop")
        )
        or thresholds["max_nll_ratio"] < 1
    ):
        raise TrainingValidationError("Invalid retention tolerances")
    reasons = []
    for stage, metrics in (("base", base), ("sft", sft), ("dpo", dpo)):
        for suite in ("domain", "general"):
            item = metrics.get(suite, {})
            if not {"cases", "exact_match", "completion_nll", "suite_sha256"} <= item.keys():
                reasons.append(f"{stage}/{suite}:missing_metrics")
                continue
            if type(item["cases"]) is not int or item["cases"] < 1:
                reasons.append(f"{stage}/{suite}:invalid_metric")
            elif item["cases"] < thresholds["minimum_cases_per_suite"]:
                reasons.append(f"{stage}/{suite}:insufficient_cases")
            if (
                type(item["exact_match"]) not in {float, int}
                or not math.isfinite(item["exact_match"])
                or not 0 <= item["exact_match"] <= 1
                or type(item["completion_nll"]) not in {float, int}
                or not math.isfinite(item["completion_nll"])
                or item["completion_nll"] < 0
            ):
                reasons.append(f"{stage}/{suite}:invalid_metric")
            if stage != "base" and item["suite_sha256"] != base.get(suite, {}).get("suite_sha256"):
                reasons.append(f"{stage}/{suite}:suite_mismatch")
            if stage != "base" and item["cases"] != base.get(suite, {}).get("cases"):
                reasons.append(f"{stage}/{suite}:suite_count_mismatch")
    if not any("missing_metrics" in reason or "invalid_metric" in reason for reason in reasons):
        for stage, metrics in (("sft", sft), ("dpo", dpo)):
            for suite in ("domain", "general"):
                drop = base[suite]["exact_match"] - metrics[suite]["exact_match"]
                if drop > thresholds[f"max_{suite}_score_drop"] + 1e-12:
                    reasons.append(f"{stage}/{suite}:score_regression")
                if (
                    metrics[suite]["completion_nll"]
                    > base[suite]["completion_nll"] * thresholds["max_nll_ratio"]
                ):
                    reasons.append(f"{stage}/{suite}:nll_regression")
    return {
        "accepted": not reasons,
        "reasons": reasons,
        "thresholds": thresholds,
        "policy": "Both SFT and DPO must retain base capabilities on identical held-out suites. This does not guarantee the absence of forgetting outside those suites.",
    }


def _offline() -> None:
    for key, value in {
        "HF_HUB_OFFLINE": "1",
        "HF_DATASETS_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "HF_HUB_DISABLE_TELEMETRY": "1",
        "TOKENIZERS_PARALLELISM": "false",
        "WANDB_DISABLED": "true",
    }.items():
        os.environ[key] = value


def _dependency_versions() -> dict:
    result = {}
    for name, expected in REQUIRED_VERSIONS.items():
        try:
            actual = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError as exc:
            raise TrainingPrerequisiteError(
                "Use the isolated P09 environment: uv sync --project projects/09-lora-training --locked"
            ) from exc
        if actual != expected:
            raise TrainingPrerequisiteError(
                f"P09 requires {name}=={expected}; found {actual}. Use projects/09-lora-training/.venv/bin/python, not the core environment."
            )
        result[name] = actual
    return result


def _artifact_hashes(directory: Path) -> dict:
    return {
        str(path.relative_to(directory)): _sha(path.read_bytes())
        for path in sorted(directory.rglob("*"))
        if path.is_file() and path.name != "manifest.json"
    }


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False))


def _git_metadata() -> dict:
    result = {"commit": None, "dirty": None}
    git = shutil.which("git")
    if git is None:
        return result
    for key, args in (
        ("commit", [git, "rev-parse", "HEAD"]),
        ("dirty", [git, "status", "--porcelain"]),
    ):
        try:
            proc = subprocess.run(
                args, cwd=ROOT, text=True, capture_output=True, timeout=3, check=False
            )
            if proc.returncode == 0:
                result[key] = bool(proc.stdout.strip()) if key == "dirty" else proc.stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            pass
    return result


def _prompt(row: dict) -> str:
    return row["prompt"] + "\nAnswer:"


def validate_tokenization(rows: list[dict], tokenizer: Any, max_length: int) -> dict:
    maxima = {"prompt": 0, "chosen_total": 0, "rejected_total": 0}
    for row in rows:
        prompt_ids = tokenizer.encode(_prompt(row), add_special_tokens=False)
        chosen_ids = tokenizer.encode(
            " " + row["chosen"] + " " + tokenizer.eos_token, add_special_tokens=False
        )
        rejected_ids = tokenizer.encode(
            " " + row["rejected"] + " " + tokenizer.eos_token, add_special_tokens=False
        )
        if chosen_ids == rejected_ids:
            raise TrainingValidationError(
                "Preference alternatives become identical after tokenization"
            )
        if (
            not chosen_ids
            or not rejected_ids
            or len(prompt_ids) + max(len(chosen_ids), len(rejected_ids)) > max_length
        ):
            raise TrainingValidationError(
                "Tokenization exceeds max_length or has no target tokens; silent truncation is forbidden"
            )
        maxima["prompt"] = max(maxima["prompt"], len(prompt_ids))
        maxima["chosen_total"] = max(maxima["chosen_total"], len(prompt_ids) + len(chosen_ids))
        maxima["rejected_total"] = max(
            maxima["rejected_total"], len(prompt_ids) + len(rejected_ids)
        )
    return {
        "examples": len(rows),
        "max_lengths": maxima,
        "truncation": "rejected",
        "tokenizer_vocabulary_size": len(tokenizer),
    }


def _build_tiny_model(train_rows: list[dict], output: Path, seed: int, max_length: int):
    import torch
    from tokenizers import Tokenizer, models, pre_tokenizers
    from transformers import GPT2Config, GPT2LMHeadModel, PreTrainedTokenizerFast, set_seed

    set_seed(seed)
    torch.set_num_threads(2)
    vocab = {"[PAD]": 0, "[UNK]": 1, "[BOS]": 2, "[EOS]": 3}
    # Only train-split prompts and preference alternatives define vocabulary.
    words = set()
    for row in train_rows:
        words.update((_prompt(row) + " " + row["chosen"] + " " + row["rejected"]).split())
    for word in sorted(words):
        if word not in vocab:
            vocab[word] = len(vocab)
    special_tokens = {
        "pad_token": "[PAD]",
        "unk_token": "[UNK]",
        "bos_token": "[BOS]",
        "eos_token": "[EOS]",
    }
    backend = Tokenizer(models.WordLevel(vocab, unk_token=special_tokens["unk_token"]))
    backend.pre_tokenizer = pre_tokenizers.WhitespaceSplit()
    tokenizer = PreTrainedTokenizerFast(
        tokenizer_object=backend,
        **special_tokens,
        model_max_length=max_length,
    )
    config = GPT2Config(
        vocab_size=len(tokenizer),
        n_positions=max_length,
        n_ctx=max_length,
        n_embd=32,
        n_layer=2,
        n_head=2,
        bos_token_id=tokenizer.bos_token_id,
        eos_token_id=tokenizer.eos_token_id,
        pad_token_id=tokenizer.pad_token_id,
        resid_pdrop=0,
        embd_pdrop=0,
        attn_pdrop=0,
    )
    model = GPT2LMHeadModel(config)
    model.save_pretrained(output, safe_serialization=True)
    tokenizer.save_pretrained(output)
    return (
        model,
        tokenizer,
        {
            "origin": "randomly initialized GPT-2 architecture, no pretrained weights",
            "revision": f"pais-tiny-gpt2-v1-seed-{seed}",
            "license": "Apache-2.0 implementation; original random weights MIT",
            "parameters": sum(p.numel() for p in model.parameters()),
            "tokenizer_fit_split": "train only",
            "tokenizer_vocabulary_size": len(tokenizer),
            "files": _artifact_hashes(output),
        },
    )


def _evaluate(model: Any, tokenizer: Any, rows: list[dict], max_new_tokens: int = 12) -> dict:
    import torch

    model.eval()
    suites = {}
    for suite in ("domain", "general"):
        selected = [row for row in rows if row["suite"] == suite]
        details = []
        for row in selected:
            prompt_ids = tokenizer.encode(_prompt(row), add_special_tokens=False)
            completion_ids = tokenizer.encode(
                " " + row["completion"] + " " + tokenizer.eos_token, add_special_tokens=False
            )
            ids = torch.tensor([prompt_ids + completion_ids], dtype=torch.long)
            labels = ids.clone()
            labels[:, : len(prompt_ids)] = -100
            with torch.no_grad():
                loss = float(
                    model(input_ids=ids, attention_mask=torch.ones_like(ids), labels=labels).loss
                )
                prompt_tensor = torch.tensor([prompt_ids], dtype=torch.long)
                generated = model.generate(
                    input_ids=prompt_tensor,
                    attention_mask=torch.ones_like(prompt_tensor),
                    max_new_tokens=max_new_tokens,
                    do_sample=False,
                    pad_token_id=tokenizer.pad_token_id,
                    eos_token_id=tokenizer.eos_token_id,
                )
            prediction = tokenizer.decode(
                generated[0, len(prompt_ids) :], skip_special_tokens=True
            ).strip()
            details.append(
                {
                    "id": row["id"],
                    "completion_nll": loss,
                    "exact_match": " ".join(prediction.split())
                    == " ".join(row["completion"].split()),
                    "prediction": prediction,
                    "expected": row["completion"],
                    "target_tokens": len(completion_ids),
                }
            )
        suites[suite] = {
            "cases": len(details),
            "exact_match": sum(row["exact_match"] for row in details) / len(details),
            "completion_nll": sum(row["completion_nll"] for row in details) / len(details),
            "suite_sha256": _sha(_canonical(selected)),
            "details": details,
        }
    return suites


def _export_reload(
    model: Any,
    tokenizer: Any,
    base_path: Path,
    adapter_path: Path,
    probe_ids: Any,
    provenance: dict,
) -> dict:
    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM

    model.eval()
    model.save_pretrained(adapter_path, safe_serialization=True)
    tokenizer.save_pretrained(adapter_path)
    with torch.no_grad():
        expected = model(probe_ids).logits.detach().cpu()
    fresh = AutoModelForCausalLM.from_pretrained(
        base_path, local_files_only=True, trust_remote_code=False, use_safetensors=True
    )
    reloaded = PeftModel.from_pretrained(
        fresh, adapter_path, is_trainable=False, local_files_only=True
    )
    reloaded.eval()
    with torch.no_grad():
        observed = reloaded(probe_ids).logits.detach().cpu()
    delta = float((observed - expected).abs().max())
    verified = bool(torch.allclose(observed, expected, atol=1e-6, rtol=1e-6))
    manifest = {
        "adapter_format": "PEFT LoRA safetensors",
        "reload_verified": verified,
        "max_logit_absolute_difference": delta,
        "base_provenance": provenance,
        "files": _artifact_hashes(adapter_path),
    }
    _write_json(adapter_path / "manifest.json", manifest)
    if not verified:
        raise TrainingValidationError(
            "Export/reload changes model outputs beyond the declared tolerance"
        )
    return manifest


def run_pipeline(config_path: str | Path, output_dir: str | Path) -> dict:
    _offline()
    versions = _dependency_versions()
    import torch
    from datasets import Dataset
    from peft import LoraConfig, PeftModel, get_peft_model
    from transformers import AutoModelForCausalLM, AutoTokenizer, set_seed
    from trl import DPOConfig, DPOTrainer, SFTConfig, SFTTrainer

    config_path = Path(config_path)
    config = json.loads(config_path.read_text())
    if (
        config["stages"] != ["sft", "dpo"]
        or not 1 <= config["max_steps"] <= 10000
        or not 16 <= config["max_length"] <= 4096
    ):
        raise TrainingValidationError("Invalid bounded training configuration")
    if config.get("torch_threads") != 2 or config.get("device") != "cpu":
        raise TrainingValidationError(
            "This verified functional profile requires CPU and two threads"
        )
    out = Path(output_dir)
    if out.exists() and any(out.iterdir()):
        raise TrainingValidationError(
            "Use a fresh output directory; existing evidence must not be overwritten"
        )
    exclusions = builtin_exclusions()
    data_path = Path(config.get("data_path", str(DATA_PATH)))
    if not data_path.is_absolute():
        data_path = ROOT / data_path
    rows = (
        load_builtin_rows()
        if data_path.resolve() == DATA_PATH.resolve()
        else [json.loads(line) for line in data_path.read_text().splitlines() if line.strip()]
    )
    prepared = prepare_dataset(
        rows, exclusions["fingerprints"], exclusions["source_ids"], config["seed"]
    )
    out.mkdir(parents=True, exist_ok=True)
    _write_json(out / "configuration.json", config)
    _write_json(
        out / "dataset-manifest.json",
        {
            **prepared["manifest"],
            "exclusions": exclusions["manifest"],
            "audit_access": exclusions["audit_access"],
        },
    )
    for split, part in prepared["splits"].items():
        _write_json(out / f"{split}-records.json", part)
    started = time.perf_counter()
    set_seed(config["seed"])
    torch.set_num_threads(2)
    base_path = out / "base-model"
    if config["model"]["mode"] == "random-tiny":
        model, tokenizer, provenance = _build_tiny_model(
            prepared["splits"]["train"], base_path, config["seed"], config["max_length"]
        )
    elif config["model"]["mode"] == "local-snapshot":
        item = config["model"]
        local = Path(item["path"])
        if (
            not local.is_dir()
            or not re.fullmatch(r"[a-f0-9]{40,64}", item.get("revision", ""))
            or not item.get("license")
        ):
            raise TrainingPrerequisiteError(
                "Local snapshot requires an existing path, immutable 40..64 hex revision, and recorded license"
            )
        expected = item.get("files_sha256")
        if (
            not isinstance(expected, dict)
            or not expected
            or any(
                not (local / name).is_file() or _sha((local / name).read_bytes()) != sha
                for name, sha in expected.items()
            )
        ):
            raise TrainingPrerequisiteError("Local model artifact hashes are absent or invalid")
        model = AutoModelForCausalLM.from_pretrained(
            local,
            local_files_only=True,
            trust_remote_code=False,
            use_safetensors=True,
            torch_dtype=torch.float32,
        )
        tokenizer = AutoTokenizer.from_pretrained(
            local, local_files_only=True, trust_remote_code=False
        )
        if tokenizer.pad_token is None:
            tokenizer.pad_token = tokenizer.eos_token
        model.save_pretrained(base_path, safe_serialization=True)
        tokenizer.save_pretrained(base_path)
        provenance = {
            **item,
            "parameters": sum(p.numel() for p in model.parameters()),
            "files": _artifact_hashes(base_path),
        }
    else:
        raise TrainingValidationError(
            "Models must be locally initialized or preprovisioned; automatic downloads are forbidden"
        )
    if provenance["parameters"] > config["max_model_parameters"]:
        raise TrainingPrerequisiteError("The model exceeds the declared compute envelope")
    _write_json(base_path / "manifest.json", provenance)
    tokenization = validate_tokenization(
        prepared["splits"]["train"], tokenizer, config["max_length"]
    )
    heldout = prepared["splits"]["test"]
    base_metrics = _evaluate(model, tokenizer, heldout)
    model.name_or_path = str(base_path)
    peft_config = LoraConfig(
        r=config["lora"]["r"],
        lora_alpha=config["lora"]["alpha"],
        lora_dropout=0,
        target_modules=config["lora"]["target_modules"],
        fan_in_fan_out=config["lora"]["fan_in_fan_out"],
        bias="none",
        task_type="CAUSAL_LM",
    )
    model = get_peft_model(model, peft_config)
    adapter_before = {
        name: p.detach().clone() for name, p in model.named_parameters() if p.requires_grad
    }
    frozen_before = {
        name: p.detach().clone() for name, p in model.named_parameters() if not p.requires_grad
    }
    sft_data = Dataset.from_list(
        [
            {
                "prompt": _prompt(row),
                "completion": " " + row["completion"] + " " + tokenizer.eos_token,
            }
            for row in prepared["splits"]["train"]
        ]
    )
    common = {
        "max_steps": config["max_steps"],
        "per_device_train_batch_size": config["batch_size"],
        "gradient_accumulation_steps": 1,
        "learning_rate": config["learning_rate"],
        "use_cpu": True,
        "bf16": False,
        "fp16": False,
        "gradient_checkpointing": False,
        "dataloader_num_workers": 0,
        "dataloader_pin_memory": False,
        "report_to": [],
        "logging_steps": 1,
        "save_strategy": "steps",
        "save_steps": max(1, config["max_steps"] // 2),
        "save_total_limit": 2,
        "seed": config["seed"],
        "data_seed": config["seed"],
        "optim": "adamw_torch",
        "disable_tqdm": True,
        "eval_strategy": "no",
    }
    sft = SFTTrainer(
        model=model,
        processing_class=tokenizer,
        train_dataset=sft_data,
        args=SFTConfig(
            output_dir=str(out / "sft-checkpoints"),
            max_length=config["max_length"],
            completion_only_loss=True,
            packing=False,
            **common,
        ),
    )
    sft_started = time.perf_counter()
    sft_output = sft.train()
    sft_seconds = time.perf_counter() - sft_started
    sft_model = sft.model
    adapter_changed = any(
        not torch.equal(adapter_before[name], p.detach())
        for name, p in sft_model.named_parameters()
        if name in adapter_before
    )
    frozen_unchanged = all(
        torch.equal(frozen_before[name], p.detach())
        for name, p in sft_model.named_parameters()
        if name in frozen_before
    )
    if not adapter_changed or not frozen_unchanged:
        raise TrainingValidationError(
            "SFT must change adapter weights while retaining the frozen backbone"
        )
    probe = tokenizer(_prompt(heldout[0]), return_tensors="pt")["input_ids"]
    sft_export = _export_reload(
        sft_model, tokenizer, base_path, out / "sft-adapter", probe, provenance
    )
    sft_metrics = _evaluate(sft_model, tokenizer, heldout)
    _write_json(
        out / "sft-training-log.json",
        {"trainer_metrics": sft_output.metrics, "log_history": sft.state.log_history},
    )
    # DPO starts at the trained SFT policy and uses a frozen SFT reference. Merely
    # disabling a LoRA adapter here would incorrectly use the original base model.
    policy_base = AutoModelForCausalLM.from_pretrained(
        base_path, local_files_only=True, trust_remote_code=False, use_safetensors=True
    )
    policy = PeftModel.from_pretrained(
        policy_base, out / "sft-adapter", is_trainable=True, local_files_only=True
    )
    ref_base = AutoModelForCausalLM.from_pretrained(
        base_path, local_files_only=True, trust_remote_code=False, use_safetensors=True
    )
    reference = PeftModel.from_pretrained(
        ref_base, out / "sft-adapter", is_trainable=False, local_files_only=True
    ).merge_and_unload()
    reference.eval()
    for parameter in reference.parameters():
        parameter.requires_grad = False
    dpo_before = {
        name: p.detach().clone() for name, p in policy.named_parameters() if p.requires_grad
    }
    preference_data = Dataset.from_list(
        [
            {
                "prompt": _prompt(row),
                "chosen": " " + row["chosen"],
                "rejected": " " + row["rejected"],
            }
            for row in prepared["splits"]["train"]
        ]
    )
    dpo = DPOTrainer(
        model=policy,
        ref_model=reference,
        processing_class=tokenizer,
        train_dataset=preference_data,
        args=DPOConfig(
            output_dir=str(out / "dpo-checkpoints"),
            max_length=config["max_length"],
            max_prompt_length=config["max_length"] - 16,
            beta=config["dpo_beta"],
            loss_type="sigmoid",
            force_use_ref_model=True,
            disable_dropout=True,
            **common,
        ),
    )
    dpo_started = time.perf_counter()
    dpo_output = dpo.train()
    dpo_seconds = time.perf_counter() - dpo_started
    dpo_changed = any(
        not torch.equal(dpo_before[name], p.detach())
        for name, p in dpo.model.named_parameters()
        if name in dpo_before
    )
    if not dpo_changed:
        raise TrainingValidationError("DPO did not update any adapter parameter")
    dpo_export = _export_reload(
        dpo.model, tokenizer, base_path, out / "dpo-adapter", probe, provenance
    )
    dpo_metrics = _evaluate(dpo.model, tokenizer, heldout)
    _write_json(
        out / "dpo-training-log.json",
        {"trainer_metrics": dpo_output.metrics, "log_history": dpo.state.log_history},
    )
    gate = retention_gate(base_metrics, sft_metrics, dpo_metrics, config["retention_thresholds"])
    result = {
        "project": "P09",
        "profile": "local",
        "verification_kind": "genuine-tiny-training-smoke"
        if config["model"]["mode"] == "random-tiny"
        else "local-pretrained-training",
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "command": sys.argv,
        "git": _git_metadata(),
        "exit_status": 0,
        "configuration_sha256": _sha(config_path.read_bytes()),
        "dataset_manifest": prepared["manifest"],
        "exclusions": exclusions["manifest"],
        "audit_access": exclusions["audit_access"],
        "dependency_versions": versions,
        "python": sys.version,
        "hardware": platform.platform(),
        "torch_threads": torch.get_num_threads(),
        "model": provenance,
        "tokenization": tokenization,
        "sft_steps": sft.state.global_step,
        "dpo_steps": dpo.state.global_step,
        "sft_train_loss": float(sft_output.training_loss),
        "dpo_train_loss": float(dpo_output.training_loss),
        "adapter_parameters": sum(p.numel() for p in dpo.model.parameters() if p.requires_grad),
        "sft_adapter_changed": adapter_changed,
        "frozen_backbone_unchanged": frozen_unchanged,
        "dpo_adapter_changed": dpo_changed,
        "sft_export": sft_export,
        "dpo_export": dpo_export,
        "metrics": {"base": base_metrics, "sft": sft_metrics, "dpo": dpo_metrics},
        "retention_gate": gate,
        "timing_seconds": {
            "sft": sft_seconds,
            "dpo": dpo_seconds,
            "total": time.perf_counter() - started,
        },
        "release_approved": bool(gate["accepted"] and config["model"]["mode"] != "random-tiny"),
        "substantive_quality_verified": False,
        "limitations": [
            "Random tiny model is not a pretrained assistant; pipeline behavior is the only smoke claim.",
            "The small synthetic held-out suites cannot establish broad capability retention or task utility.",
            "No adapter is released when retention checks fail.",
        ],
    }
    _write_json(out / "training-result.json", result)
    _write_json(
        out / "checkpoint-manifest.json",
        {
            "sft": _artifact_hashes(out / "sft-checkpoints"),
            "dpo": _artifact_hashes(out / "dpo-checkpoints"),
        },
    )
    return result


def demo(profile: str = "fixture", output_dir: str | Path | None = None) -> dict:
    if profile == "local":
        output = (
            output_dir
            or ROOT / "artifacts" / f"p09-smoke-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S')}"
        )
        return run_pipeline(PROJECT / "configs/tiny-smoke.json", output)
    if profile != "fixture":
        raise TrainingPrerequisiteError(
            "P09 provides fixture validation and a local CPU training profile"
        )
    exclusions = builtin_exclusions()
    prepared = prepare_dataset(
        load_builtin_rows(), exclusions["fingerprints"], exclusions["source_ids"]
    )
    bad = load_builtin_rows()
    bad[0] = {**bad[0], "rejected": bad[0]["chosen"]}
    rejected = False
    try:
        prepare_dataset(bad)
    except TrainingValidationError:
        rejected = True
    overlap_rejected = False
    try:
        prepare_dataset(load_builtin_rows(), {text_fingerprint(load_builtin_rows()[0]["prompt"])})
    except TrainingValidationError:
        overlap_rejected = True
    result = {
        "project": "P09",
        "profile": "fixture",
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "command": sys.argv,
        "git": _git_metadata(),
        "python": sys.version,
        "source_sha256": _sha(Path(__file__).read_bytes()),
        "exit_status": 0,
        "dataset_manifest": prepared["manifest"],
        "exclusions": exclusions["manifest"],
        "audit_access": exclusions["audit_access"],
        "identical_preference_rejected": rejected,
        "known_overlap_rejected": overlap_rejected,
        "trained": False,
        "substantive_quality_verified": False,
    }
    if output_dir is not None:
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        _write_json(out / "fixture-validation.json", result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["fixture", "smoke", "train"])
    parser.add_argument("--config", default=str(PROJECT / "configs/tiny-smoke.json"))
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        result = (
            demo(output_dir=args.output)
            if args.command == "fixture"
            else run_pipeline(args.config, args.output)
        )
        concise = {
            key: value
            for key, value in result.items()
            if key
            not in {
                "dataset_manifest",
                "model",
                "exclusions",
                "metrics",
                "sft_export",
                "dpo_export",
            }
        }
        if "metrics" in result:
            concise["metrics"] = {
                stage: {
                    suite: {k: v for k, v in item.items() if k != "details"}
                    for suite, item in suites.items()
                }
                for stage, suites in result["metrics"].items()
            }
        print(json.dumps(concise, indent=2, ensure_ascii=False))
        return 0
    except (TrainingValidationError, TrainingPrerequisiteError, FileNotFoundError) as exc:
        print(json.dumps({"error": str(exc), "exit_status": 2}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
