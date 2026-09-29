"""P09 data-integrity/retention tests; genuine training has its explicit isolated CLI gate."""

import copy
import json

import pytest
from pais import training


def _metrics(cases=25, score=0.8, nll=2.0):
    return {
        suite: {
            "cases": cases,
            "exact_match": score,
            "completion_nll": nll,
            "suite_sha256": letter * 64,
        }
        for suite, letter in (("domain", "a"), ("general", "b"))
    }


THRESHOLDS = {
    "minimum_cases_per_suite": 20,
    "max_general_score_drop": 0.05,
    "max_domain_score_drop": 0.02,
    "max_nll_ratio": 1.1,
}


def test_source_splits_stable_after_input_reordering():
    rows = training.load_builtin_rows()
    forward = training.prepare_dataset(rows)
    reverse = training.prepare_dataset(list(reversed(rows)))
    assert forward["splits"] == reverse["splits"]
    assert forward["manifest"]["counts"] == {"train": 36, "dev": 12, "test": 12}
    sources = [{r["source_id"] for r in part} for part in forward["splits"].values()]
    assert not (sources[0] & sources[1] or sources[0] & sources[2] or sources[1] & sources[2])


def test_duplicate_same_source_is_logged_not_leaked():
    rows = training.load_builtin_rows()
    duplicate = {**rows[0], "id": rows[0]["id"] + "-copy"}
    prepared = training.prepare_dataset([*rows, duplicate])
    assert prepared["manifest"]["deduplicated_records"] == 1
    assert sum(map(len, prepared["splits"].values())) == len(rows)


def test_duplicate_prompt_cross_source_is_rejected():
    rows = training.load_builtin_rows()
    duplicate = {**rows[0], "id": "other-row", "source_id": "other-source"}
    with pytest.raises(training.TrainingValidationError, match="different source groups"):
        training.prepare_dataset([*rows, duplicate])


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"rejected": "stop"}, "must differ"),
        ({"rationale": "Because better."}, "substantive"),
        ({"license": "unknown"}, "license"),
        ({"license": "CC-BY-4.0"}, "Attribution"),
        ({"completion": "wrong-label"}, "SFT completion"),
    ],
)
def test_invalid_instruction_or_preference_fails_closed(change, reason):
    rows = training.load_builtin_rows()
    rows[0].update(change)
    with pytest.raises(training.TrainingValidationError, match=reason):
        training.prepare_dataset(rows)


def test_known_benchmark_prompt_and_source_cannot_enter_training():
    rows = training.load_builtin_rows()
    normalized = "  " + rows[0]["prompt"].upper().replace(" ", "\n") + "  "
    with pytest.raises(training.TrainingValidationError, match="overlaps"):
        training.prepare_dataset(rows, {training.text_fingerprint(normalized)})
    with pytest.raises(training.TrainingValidationError, match="source"):
        training.prepare_dataset(rows, forbidden_source_ids={rows[0]["source_id"]})


def test_release_audit_and_benchmark_exclusions_are_all_required():
    exclusions = training.builtin_exclusions()
    names = {item["path"] for item in exclusions["manifest"]}
    assert names == {
        "evals/release.json",
        "evals/development.json",
        "evals/audit.json",
        "evals/corpus.json",
        "projects/17-domain-benchmark/data/tasks-v1.jsonl",
    }
    assert "Hash/overlap access only" in exclusions["audit_access"]
    prepared = training.prepare_dataset(
        training.load_builtin_rows(), exclusions["fingerprints"], exclusions["source_ids"]
    )
    assert prepared["manifest"]["forbidden_fingerprint_count"] > 100


def test_exclusion_manifest_captures_nested_source_content(tmp_path):
    path = tmp_path / "corpus.json"
    path.write_text(
        json.dumps(
            {
                "source-A": {
                    "pages": ["A complete excluded source passage"],
                    "title": "Private holdout",
                }
            }
        )
    )
    excluded = training.collect_exclusions([path])
    assert "source-A" in excluded["source_ids"]
    assert (
        training.text_fingerprint("A complete excluded source passage") in excluded["fingerprints"]
    )
    path.unlink()
    with pytest.raises(training.TrainingPrerequisiteError, match="not found"):
        training.collect_exclusions([path])


def test_retention_rejects_regression_even_with_good_domain_score():
    base, sft, dpo = _metrics(), _metrics(), _metrics()
    sft["general"]["exact_match"] = 0.74
    result = training.retention_gate(base, sft, dpo, THRESHOLDS)
    assert not result["accepted"]
    assert "sft/general:score_regression" in result["reasons"]


def test_retention_rejects_nll_regression_and_changed_suite():
    base, sft, dpo = _metrics(), _metrics(), _metrics()
    dpo["domain"]["completion_nll"] = 2.21
    sft["general"]["suite_sha256"] = "c" * 64
    result = training.retention_gate(base, sft, dpo, THRESHOLDS)
    assert "dpo/domain:nll_regression" in result["reasons"]
    assert "sft/general:suite_mismatch" in result["reasons"]


def test_retention_requires_same_case_count_despite_matching_hash_claim():
    base, sft, dpo = _metrics(), _metrics(cases=30), _metrics()
    assert (
        "sft/general:suite_count_mismatch"
        in training.retention_gate(base, sft, dpo, THRESHOLDS)["reasons"]
    )


@pytest.mark.parametrize("invalid", [None, float("nan"), True, "missing"])
def test_retention_cannot_accept_invalid_nll(invalid):
    base, sft, dpo = _metrics(), _metrics(), _metrics()
    dpo["domain"]["completion_nll"] = invalid
    result = training.retention_gate(base, sft, dpo, THRESHOLDS)
    assert not result["accepted"]
    assert "dpo/domain:invalid_metric" in result["reasons"]


def test_small_smoke_is_not_a_retention_pass():
    result = training.retention_gate(_metrics(6), _metrics(6), _metrics(6), THRESHOLDS)
    assert not result["accepted"]
    assert len(result["reasons"]) == 6


def test_prospectively_declared_tolerances_allow_valid_measurements():
    base, sft, dpo = _metrics(), _metrics(score=0.79), _metrics(score=0.85)
    assert training.retention_gate(base, sft, dpo, THRESHOLDS)["accepted"]
    bad_thresholds = {**THRESHOLDS, "max_nll_ratio": float("inf")}
    with pytest.raises(training.TrainingValidationError, match="finite"):
        training.retention_gate(base, sft, dpo, bad_thresholds)


class _TokenizerProbe:
    eos_token = "[EOS]"

    def __init__(self, alias_alternatives=False):
        self.alias_alternatives = alias_alternatives

    def encode(self, text, add_special_tokens=False):
        if self.alias_alternatives:
            return [1, 2]
        return list(text.encode())

    def __len__(self):
        return 256


def test_tokenization_rejects_identical_preferences_after_unknown_mapping():
    with pytest.raises(training.TrainingValidationError, match="identical after tokenization"):
        training.validate_tokenization(training.load_builtin_rows()[:1], _TokenizerProbe(True), 128)


def test_tokenization_forbids_silent_target_truncation():
    with pytest.raises(training.TrainingValidationError, match="silent truncation"):
        training.validate_tokenization(training.load_builtin_rows()[:1], _TokenizerProbe(), 16)


def test_wrong_environment_reports_exact_missing_dependency(monkeypatch):
    monkeypatch.setattr(training.importlib.metadata, "version", lambda name: "0.0.0")
    with pytest.raises(training.TrainingPrerequisiteError, match=r"torch==2.8.0\+cpu"):
        training._dependency_versions()


def test_preference_label_conflict_is_not_silently_deduplicated():
    rows = training.load_builtin_rows()
    duplicate = copy.deepcopy(rows[0])
    duplicate.update(id="conflicting-copy", rejected="different_wrong_answer")
    with pytest.raises(training.TrainingValidationError, match="conflicting"):
        training.prepare_dataset([*rows, duplicate])
