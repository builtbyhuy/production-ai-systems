import json

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
