"""P17 corpus/controller tests. No untrusted candidate is executed on this host."""

import copy
import hashlib
import json

import pytest
from pais import benchmark
from pais.sandbox import SandboxRunner, SandboxUnavailable


def test_original_corpus_has_100_distinct_contracts_and_325_checks():
    result = benchmark.validate_trusted_references()
    assert result["tasks"] == result["distinct_reference_asts"] == 100
    assert result["executable_checks"] == 325
    assert result["reference_contracts_passed"] == result["seeded_defects_reproduced"] == 100
    assert result["untrusted_submissions_executed"] == 0
    assert not result["leaderboard_eligible"]


def test_order_sensitive_query_fixture_is_not_sorted_by_serialization():
    task = next(t for t in benchmark.load_tasks() if t["id"].startswith("ppm-052-"))
    assert list(task["cases"][0]["args"][0]) == ["tag", "q"]


def test_altered_corpus_cannot_enter_trusted_exec_path(tmp_path, monkeypatch):
    modified = tmp_path / "altered.jsonl"
    modified.write_bytes(benchmark.DATASET_PATH.read_bytes() + b"\n")
    monkeypatch.setattr(benchmark, "DATASET_PATH", modified)
    with pytest.raises(benchmark.BenchmarkValidationError, match="checksum"):
        benchmark.validate_trusted_references()


def test_source_group_cannot_cross_benchmark_splits():
    tasks = benchmark.load_tasks()
    tasks[6]["source_id"] = tasks[0]["source_id"]
    with pytest.raises(benchmark.BenchmarkValidationError, match="crosses splits"):
        benchmark.validate_dataset(tasks)


def test_fewer_than_100_or_duplicate_checks_are_invalid():
    tasks = benchmark.load_tasks()
    with pytest.raises(benchmark.BenchmarkValidationError, match="100"):
        benchmark.validate_dataset(tasks[:-1])
    tasks[0]["cases"][1] = tasks[0]["cases"][0]
    with pytest.raises(benchmark.BenchmarkValidationError, match="Duplicate checks"):
        benchmark.validate_dataset(tasks)


@pytest.mark.parametrize(
    "source",
    [
        "def solve(:",
        "value = 1",
        "async def solve(): return 1",
        "def solve(): pass\n" * 2,
        "x" * 33_000,
    ],
)
def test_invalid_submission_source_rejected_without_execution(source):
    submission = benchmark.make_baseline()
    submission["solutions"][next(iter(submission["solutions"]))] = source
    with pytest.raises(benchmark.BenchmarkValidationError):
        benchmark.validate_submission(submission)


def test_validation_is_not_execution_or_a_security_boundary(tmp_path):
    sentinel = tmp_path / "must-not-exist"
    submission = benchmark.make_baseline()
    task_id = next(iter(submission["solutions"]))
    submission["solutions"][task_id] = (
        f"open({str(sentinel)!r}, 'w').write('executed')\ndef solve(*args): return None\n"
    )
    assert benchmark.validate_submission(submission)["valid"]
    assert not sentinel.exists()


def test_disabled_boundary_denies_before_launch_or_evidence_write(tmp_path, monkeypatch):
    def fail_if_launched(*args, **kwargs):
        raise AssertionError("No host process may be launched for a denied candidate")

    monkeypatch.setattr(benchmark.subprocess, "Popen", fail_if_launched)
    out = tmp_path / "score"
    with pytest.raises(SandboxUnavailable, match="disabled"):
        benchmark.run_benchmark(benchmark.make_baseline(), SandboxRunner(), out)
    assert not out.exists()


def test_custom_host_executor_cannot_replace_p06_boundary(tmp_path):
    with pytest.raises(SandboxUnavailable, match="P06 SandboxRunner"):
        benchmark.run_benchmark(benchmark.make_baseline(), object(), tmp_path / "score")


def test_baselines_are_deterministic_and_described_as_rules_not_models():
    first, second = (
        benchmark.make_baseline("mechanical-repair"),
        benchmark.make_baseline("mechanical-repair"),
    )
    assert first == second
    assert first["metadata"]["model"] is None
    assert first["metadata"]["origin"] == "hand-authored-rule-engine"
    assert len(first["solutions"]) == 100
    assert any(
        first["solutions"][key] != value
        for key, value in benchmark.make_baseline()["solutions"].items()
    )


def test_wire_protocol_does_not_accept_exception_name_substrings():
    case = {"args": [], "raises": "ValueError"}
    assert benchmark._outcome_matches(
        {"kind": "exception", "classes": ["JSONDecodeError", "ValueError"]}, case
    )
    assert not benchmark._outcome_matches({"kind": "exception", "classes": "NotAValueError"}, case)
    assert not benchmark._outcome_matches(
        {"kind": "exception", "classes": ["NotAValueError"]}, case
    )


def test_numeric_controller_rejects_bool_and_huge_float_coercion():
    assert not benchmark._equivalent(True, 1)
    assert not benchmark._equivalent(10**1000, 1.0)
    assert benchmark._equivalent(10**1000, 10**1000)
    assert not benchmark._equivalent(float("nan"), 1)


def test_candidate_harness_never_embeds_expected_results():
    source = "def solve(x): return x\n"
    harness = benchmark._candidate_harness(source)
    assert "expected" not in harness
    assert source in harness


def _controller_fixture_record():
    """Invented controller fixture only; never model/sandbox execution evidence."""
    tasks = [task for task in benchmark.load_tasks() if task["split"] == "test"]
    results = [
        {
            "task_id": task["id"],
            "case_passes": [index == 0] * len(task["cases"]),
            "passed": index == 0,
        }
        for index, task in enumerate(tasks)
    ]
    return {
        "verification_kind": "sandbox-scored-submission",
        "status": "executed",
        "dataset_sha256": benchmark.DATASET_SHA256,
        "sandbox": {"boundary": "rootless-docker-cgroupv2"},
        "split": "test",
        "results": results,
        "passed_tasks": 1,
        "total_tasks": len(tasks),
        "raw_results_sha256": hashlib.sha256(benchmark._json(results).encode()).hexdigest(),
        "generator": {"name": "CONTROLLER UNIT FIXTURE — NOT A REAL RUN"},
        "duration_seconds": 0,
        "hardware": "unit fixture",
        "submission_sha256": "a" * 64,
    }


def test_leaderboard_rejects_corpus_qa_as_scoring_evidence(tmp_path):
    path = tmp_path / "trusted-qa.json"
    path.write_text(json.dumps(benchmark.validate_trusted_references()))
    with pytest.raises(benchmark.BenchmarkValidationError, match="actual sandbox-scored"):
        benchmark.build_leaderboard([path])


def test_leaderboard_recounts_raw_outcomes_and_rejects_summary_tampering(tmp_path):
    path = tmp_path / "controller-fixture.json"
    record = _controller_fixture_record()
    path.write_text(json.dumps(record))
    leaderboard = benchmark.build_leaderboard([path])
    assert leaderboard["rows"][0]["passed"] == 1
    assert leaderboard["rows"][0]["pass_at_1"] == 1 / 20
    altered = copy.deepcopy(record)
    altered["passed_tasks"] = 20
    path.write_text(json.dumps(altered))
    with pytest.raises(benchmark.BenchmarkValidationError, match="altered"):
        benchmark.build_leaderboard([path])


def test_leaderboard_rejects_incomplete_split_and_corrupted_case_digest(tmp_path):
    path = tmp_path / "controller-fixture.json"
    record = _controller_fixture_record()
    record["results"].pop()
    path.write_text(json.dumps(record))
    with pytest.raises(benchmark.BenchmarkValidationError, match="exactly the declared split"):
        benchmark.build_leaderboard([path])
    record = _controller_fixture_record()
    record["raw_results_sha256"] = "0" * 64
    path.write_text(json.dumps(record))
    with pytest.raises(benchmark.BenchmarkValidationError, match="altered"):
        benchmark.build_leaderboard([path])
