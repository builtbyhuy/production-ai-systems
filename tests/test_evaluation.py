import hashlib
import json
import sys
from types import SimpleNamespace

import pytest
from pais.evaluation import load_suite, run_case
from pais.evidence import ROOT
from pais.rag import RAGService


def test_release_coverage_and_source_group_separation():
    release, _ = load_suite("release")
    dev, _ = load_suite("development")
    audit, _ = load_suite("audit")
    assert len(release) >= 120
    assert len({c["id"] for c in release}) == len(release)
    assert len({c["category"] for c in release}) == 9
    groups = [{c["source_id"] for c in suite} for suite in [release, dev, audit]]
    assert not groups[0] & groups[1]
    assert not groups[0] & groups[2]
    assert not groups[1] & groups[2]


def test_answer_oracles_do_not_enter_corpus():
    _, corpus = load_suite("release")
    for source in corpus.values():
        assert (
            not {"question", "expected_terms", "expected_outcome", "expected_pages"} & source.keys()
        )


def test_degraded_candidate_is_caught_by_real_case(tmp_path):
    cases, corpus = load_suite("development")
    case = cases[0]
    normal_db = tmp_path / "normal.db"
    baseline = run_case(
        RAGService(normal_db), case, corpus[case["source_id"]], normal_db, "fixture"
    )
    broken_db = tmp_path / "broken.db"
    broken = run_case(
        RAGService(broken_db), case, corpus[case["source_id"]], broken_db, "fixture", degraded=True
    )
    assert baseline["passed"]
    assert not broken["passed"]
    assert broken["source_checks"] == [False]


def test_release_thresholds_require_full_evidence():
    t = json.loads((ROOT / "evals/thresholds.json").read_text())["release"]
    assert t["minimum_cases"] >= 120
    assert t["maximum_skipped"] == t["maximum_errors"] == 0
    assert t["requires_local_model_profile_for_deployment"]


@pytest.mark.parametrize("mutation", ["hash", "count", "split", "category"])
def test_frozen_dataset_mutations_fail_before_execution(tmp_path, monkeypatch, mutation):
    from pais import evaluation

    folder = tmp_path / "evals"
    folder.mkdir()
    for name in ("release.json", "corpus.json", "manifest.json"):
        (folder / name).write_bytes((ROOT / "evals" / name).read_bytes())
    cases = json.loads((folder / "release.json").read_text())
    manifest = json.loads((folder / "manifest.json").read_text())
    if mutation == "count":
        cases = cases[:100]
    elif mutation == "split":
        cases[0]["split"] = "audit"
    elif mutation == "category":
        cases[0]["category"] = "cross-page"
    else:
        cases[0]["question"] = "An unregistered easy question"
    (folder / "release.json").write_text(json.dumps(cases))
    if mutation != "hash":
        manifest["files"]["release.json"] = hashlib.sha256((folder / "release.json").read_bytes()).hexdigest()
        (folder / "manifest.json").write_text(json.dumps(manifest))
    monkeypatch.setattr(evaluation, "ROOT", tmp_path)
    with pytest.raises(ValueError):
        load_suite("release")


@pytest.mark.parametrize("mutation", ["identity", "missing", "nan", "contradiction", "versions"])
def test_invalid_worker_metrics_fail_closed(tmp_path, monkeypatch, mutation):
    from pais import evaluation

    report = {
        "versions": {"deepeval": "test-version", "ragas": "test-version"},
        "results": {"case-1": {"deepeval_source_support": 1.0,
                               "ragas_reference_exact_match": 1.0,
                               "ragas_reference_similarity": 1.0}},
    }
    if mutation == "identity":
        report["results"]["unknown-case"] = report["results"].pop("case-1")
    elif mutation == "missing":
        report["results"]["case-1"].pop("ragas_reference_exact_match")
    elif mutation == "nan":
        report["results"]["case-1"]["ragas_reference_similarity"] = float("nan")
    elif mutation == "contradiction":
        report["results"]["case-1"]["deepeval_source_support"] = 0.0
    else:
        report["versions"] = {}

    def mock_worker(command, **kwargs):
        from pathlib import Path

        Path(command[-1]).write_text(json.dumps(report))
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setenv("PAIS_EVAL_PYTHON", sys.executable)
    monkeypatch.setattr(evaluation.subprocess, "run", mock_worker)
    rows = [{"id": "case-1", "passed": True, "source_checks": [True]}]
    with pytest.raises(evaluation.EvaluationPrerequisite):
        evaluation._framework_metrics(rows, tmp_path / "metrics.json")
