from __future__ import annotations

import copy
import hashlib
import json
import multiprocessing
import sqlite3
import subprocess
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from pais.contracts import Principal
from pais.operations import (
    CapabilityDisabled,
    CapabilityFlags,
    CapabilityStateUnavailable,
    FlagConflict,
    ReleaseRejected,
    evaluate_canary_window,
    validate_release_bundle,
    validate_release_evaluation,
)


def _principal(tenant="alpha", roles=None):
    return Principal(subject=f"{tenant}-actor", tenant_id=tenant, roles=roles or ["admin"])


def _worker_check(path, sender):
    flags = CapabilityFlags(path)
    try:
        flags.require(_principal(), "agent.execute")
        sender.send("admitted")
    except CapabilityDisabled:
        sender.send("disabled")
    finally:
        sender.close()


def test_flags_default_and_tenant_authority(tmp_path):
    flags = CapabilityFlags(tmp_path / "flags.sqlite")
    admin = _principal()
    with pytest.raises(CapabilityDisabled):
        flags.require(admin, "agent.execute")
    with pytest.raises(PermissionError):
        flags.set(_principal(roles=["reader"]), "agent.execute", True)
    enabled = flags.set(admin, "agent.execute", True, expected_version=0)
    assert enabled["version"] == 1
    assert flags.require(admin, "agent.execute")["effective_enabled"]
    with pytest.raises(CapabilityDisabled):
        flags.require(_principal("beta"), "agent.execute")
    assert len(flags.audit(_principal("beta"))) == 0


def test_compare_and_set_blocks_lost_updates(tmp_path):
    flags = CapabilityFlags(tmp_path / "flags.sqlite")

    def enable():
        try:
            flags.set(_principal(), "agent.execute", True, expected_version=0)
            return "updated"
        except FlagConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=4) as pool:
        outcomes = list(pool.map(lambda _: enable(), range(4)))
    assert outcomes.count("updated") == 1
    assert outcomes.count("conflict") == 3
    assert len(flags.audit(_principal())) == 1


def test_global_emergency_propagates_to_distinct_process_and_restart(tmp_path):
    path = str(tmp_path / "flags.sqlite")
    flags = CapabilityFlags(path)
    admin = _principal()
    flags.set(admin, "agent.execute", True)
    with pytest.raises(PermissionError):
        flags.emergency_stop(admin, "agent.execute", True)
    context = multiprocessing.get_context("spawn")
    for disabled, expected in [(False, "admitted"), (True, "disabled")]:
        flags.emergency_stop(_principal("ops", ["operator"]), "agent.execute", disabled)
        receiver, sender = context.Pipe(duplex=False)
        process = context.Process(target=_worker_check, args=(path, sender))
        process.start()
        sender.close()
        assert receiver.poll(15), "Flag check worker did not respond"
        assert receiver.recv() == expected
        process.join(15)
        assert process.exitcode == 0
        receiver.close()
    assert CapabilityFlags(path).get(admin, "agent.execute")["emergency_disabled"]


def test_missing_emergency_state_stays_fail_closed_across_restart(tmp_path):
    path = tmp_path / "flags.sqlite"
    flags = CapabilityFlags(path)
    flags.set(_principal(), "agent.execute", True)
    with flags.db.transaction() as conn:
        conn.execute("DELETE FROM ops_emergency_flags")
    with pytest.raises(CapabilityStateUnavailable):
        CapabilityFlags(path).require(_principal(), "agent.execute")


def test_unavailable_database_never_uses_old_enabled_value(tmp_path, monkeypatch):
    flags = CapabilityFlags(tmp_path / "flags.sqlite")
    flags.set(_principal(), "agent.execute", True)
    assert flags.require(_principal(), "agent.execute")

    def broken():
        raise sqlite3.OperationalError("unavailable")

    monkeypatch.setattr(flags.db, "connect", broken)
    with pytest.raises(CapabilityStateUnavailable):
        flags.require(_principal(), "agent.execute")


def test_action_and_flag_admission_share_transaction(tmp_path):
    flags = CapabilityFlags(tmp_path / "flags.sqlite")
    flags.set(_principal(), "agent.execute", True)
    conn = flags.db.connect()
    try:
        with pytest.raises(CapabilityStateUnavailable):
            flags.require_tx(conn, _principal(), "agent.execute")
    finally:
        conn.close()
    with flags.db.transaction() as conn:
        state = flags.require_tx(conn, _principal(), "agent.execute")
        assert conn.in_transaction and state["version"] == 1


@pytest.fixture
def release_report(tmp_path, monkeypatch):
    """Mock captured outcomes, but bind their structure to real temporary Git objects.

    This unit fixture tests the evidence consumer. It is not model execution evidence.
    """
    from pais import evidence

    repository = tmp_path / "candidate"
    repository.mkdir()
    (repository / "evals").mkdir()
    original = Path(__file__).resolve().parents[1]
    for name in ("release.json", "corpus.json", "manifest.json", "thresholds.json"):
        (repository / "evals" / name).write_bytes((original / "evals" / name).read_bytes())
    for command in (
        ["git", "init", "--quiet"], ["git", "add", "evals"],
        ["git", "-c", "user.name=Contract Test", "-c", "user.email=test@example.invalid",
         "commit", "--quiet", "-m", "Isolated frozen contract fixture"],
    ):
        subprocess.run(command, cwd=repository, check=True, capture_output=True)
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repository, text=True).strip()
    monkeypatch.setattr(evidence, "ROOT", repository)
    cases = json.loads((repository / "evals/release.json").read_text())
    corpus = json.loads((repository / "evals/corpus.json").read_text())
    thresholds = json.loads((repository / "evals/thresholds.json").read_text())["release"]
    hashes = {
        str(path.relative_to(repository)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (repository / "evals").glob("*.json")
    }
    results = []
    for case in cases:
        source = corpus[case["source_id"]]
        reference = {
            "answer": source["pages"][0], "injection": source["pages"][0],
            "abstain": "abstain", "conflict": "conflict-visible",
            "citation": str(case.get("mutation") in {"valid", "archived"}),
            "authorization": "denied-or-isolated", "malformed": "rejected", "recovery": "recovered",
        }[case["scenario"]]
        summary = case["category"] == "cross-page"
        results.append({
            "id": case["id"], "category": case["category"], "scenario": case["scenario"],
            "question": case.get("question", source["pages"][0]), "passed": True,
            "profile": "local", "source_checks": [True], "latency_ms": 1.0,
            "expected_reference": reference, "actual_reference": reference,
            "metrics": {"deepeval_source_support": 1.0, "ragas_reference_exact_match": 1.0,
                        "ragas_reference_similarity": 1.0},
            "details": {"answer": {
                "text": "\n".join(case.get("expected_terms") or [source["pages"][0]]),
                "abstained": False,
                "citations": [{"page_number": page} for page in case.get("expected_pages", [1])],
                "evidence": {"generation": {
                    "real_inference": not summary, "model": "ollama:unit-test@" + "a" * 64,
                    "raw_model_output": '{"sentence_ids":["s1"],"abstain":false}',
                    "generation_mode": "deterministic bounded source-excerpt assembly" if summary
                    else "constrained evidence sentence selection",
                }},
            }},
        })
    counts = Counter(case["category"] for case in cases)
    return {
        "profile": "local",
        "suite": "release",
        "summary": {
            "total": len(cases),
            "passed": len(cases),
            "failed": 0,
            "errors": 0,
            "skipped": 0,
            "gate_passed": True,
            "deployment_eligible": True,
            "p95_latency_ms": 1.0,
            "per_category": {
                category: {"total": count, "passed": count, "errors": 0, "pass_rate": 1.0}
                for category, count in counts.items()
            },
        },
        "results": results,
        "required_cases": len(cases),
        "framework_metrics": {"versions": {"deepeval": "test-version", "ragas": "test-version"}},
        "manifest": {
            "git_commit": commit, "dirty_tree": False, "profile": "local",
            "timestamp_utc": "2026-09-29T00:00:00Z",
            "source_snapshot_sha256": hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest(),
            "source_file_hashes": hashes, "dataset_hashes": dict(hashes),
            "dependency_versions": {name: "test-version" for name in thresholds["required_dependencies"]},
            "models": {"lock_sha256": "d" * 64,
                       "configuration": {"generation": {"name": "unit-test", "digest": "a" * 64}}},
            "configuration": {"suite": "release", "thresholds": thresholds, "degraded": False},
        },
    }


def test_release_evidence_requires_real_complete_unique_cases(release_report):
    commit = release_report["manifest"]["git_commit"]
    assert validate_release_evaluation(release_report, commit)["accepted"]
    variants = []
    for key, value in (("profile", "fixture"), ("manifest", {})):
        report = copy.deepcopy(release_report)
        report[key] = value
        variants.append(report)
    report = copy.deepcopy(release_report)
    report["summary"]["skipped"] = 1
    variants.append(report)
    report = copy.deepcopy(release_report)
    report["results"][1]["id"] = report["results"][0]["id"]
    variants.append(report)
    report = copy.deepcopy(release_report)
    report["results"][0]["profile"] = "fixture"
    variants.append(report)
    report = copy.deepcopy(release_report)
    report["results"][0]["passed"] = False
    variants.append(report)
    for invalid in variants:
        with pytest.raises(ReleaseRejected):
            validate_release_evaluation(invalid, commit)
    with pytest.raises(ReleaseRejected):
        validate_release_evaluation(release_report, "b" * 40)


def test_release_rejects_self_registered_subsets_and_wrong_registered_cases(release_report):
    mutations = [
        lambda r: (r.__setitem__("results", r["results"][:100]), r.__setitem__("required_cases", 100),
                   r["summary"].update(total=100, passed=100)),
        lambda r: r["results"][0].__setitem__("id", "not-a-registered-case"),
        lambda r: r["results"][0].__setitem__("case_id", "not-a-registered-case"),
        lambda r: r["results"][0].__setitem__("category", "cross-page"),
        lambda r: r["results"][0].__setitem__("question", "A different easy question"),
        lambda r: r["summary"]["per_category"].pop("adversarial"),
    ]
    for mutate in mutations:
        report = copy.deepcopy(release_report)
        mutate(report)
        with pytest.raises(ReleaseRejected):
            validate_release_evaluation(report)


def test_release_rejects_forged_provenance_thresholds_and_metric_flags(release_report):
    mutations = [
        lambda r: r["manifest"].__setitem__("source_snapshot_sha256", "f" * 64),
        lambda r: r["manifest"]["source_file_hashes"].__setitem__("evals/release.json", "f" * 64),
        lambda r: r["manifest"]["dataset_hashes"].__setitem__("evals/release.json", "f" * 64),
        lambda r: r["manifest"]["configuration"]["thresholds"].__setitem__("minimum_cases", 100),
        lambda r: r["manifest"]["configuration"].__setitem__("suite", "audit"),
        lambda r: r.__setitem__("framework_metrics", {"fixture_contract_only": True}),
        lambda r: r["results"][0]["metrics"].__setitem__("deepeval_source_support", 0.0),
        lambda r: r["results"][0]["metrics"].__setitem__("ragas_reference_exact_match", 0.0),
        lambda r: r["results"][0]["metrics"].__setitem__("ragas_reference_similarity", float("nan")),
        lambda r: r["results"][0].__setitem__("source_checks", [False]),
        lambda r: r["results"][0].__setitem__("expected_reference", "An easier oracle"),
        lambda r: r["results"][0]["details"]["answer"]["evidence"]["generation"].__setitem__("real_inference", False),
        lambda r: r["results"][0]["details"]["answer"]["evidence"]["generation"].__setitem__("model", "fixture"),
        lambda r: r["results"][0]["details"]["answer"].__setitem__("citations", []),
        lambda r: r["summary"].__setitem__("p95_latency_ms", 0),
        lambda r: r["results"][0].__setitem__("latency_ms", float("nan")),
    ]
    for mutate in mutations:
        report = copy.deepcopy(release_report)
        mutate(report)
        with pytest.raises(ReleaseRejected):
            validate_release_evaluation(report)


def test_release_rejects_malformed_nested_evidence_and_missing_commit(release_report):
    mutations = [
        lambda r: r.__setitem__("summary", []),
        lambda r: r["manifest"].__setitem__("configuration", None),
        lambda r: r["manifest"].__setitem__("models", []),
        lambda r: r["results"][0].__setitem__("details", None),
        lambda r: r["results"][0]["details"]["answer"].__setitem__("evidence", None),
        lambda r: r["manifest"].__setitem__("git_commit", "f" * 40),
    ]
    for mutate in mutations:
        report = copy.deepcopy(release_report)
        mutate(report)
        with pytest.raises(ReleaseRejected):
            validate_release_evaluation(report)


def test_release_bundle_requires_digest_and_migration_compatibility():
    bundle = {
        "image": "ghcr.io/example/pais@sha256:" + "a" * 64,
        "git_commit": "b" * 40,
        "migration_policy": "expand-only",
        "state_schema": 1,
        "checkpoint_schema": 2,
        "minimum_readable_checkpoint_schema": 1,
    }
    for name in (
        "prompt_sha256",
        "model_config_sha256",
        "embedding_config_sha256",
        "flag_schema_sha256",
        "evaluation_sha256",
    ):
        bundle[name] = "c" * 64
    assert validate_release_bundle(bundle)["accepted"]
    for key, value in (
        ("image", "pais:latest"),
        ("migration_policy", "drop-columns"),
        ("minimum_readable_checkpoint_schema", 3),
        ("prompt_sha256", "missing"),
    ):
        invalid = copy.deepcopy(bundle)
        invalid[key] = value
        with pytest.raises(ReleaseRejected):
            validate_release_bundle(invalid)


def test_canary_missing_sparse_nonfinite_and_degraded_quality_block_promotion():
    healthy = {
        "request_count": 200,
        "quality_count": 120,
        "quality_successes": 120,
        "errors": 1,
        "p95_seconds": 2.0,
    }
    assert evaluate_canary_window(healthy)["promote"]
    for key, value in (
        ("quality_count", 0),
        ("request_count", 99),
        ("p95_seconds", float("nan")),
        ("p95_seconds", float("inf")),
        ("quality_successes", 100),
        ("quality_successes", 999),
        ("errors", 20),
    ):
        bad = {**healthy, key: value}
        assert not evaluate_canary_window(bad)["promote"]
    assert not evaluate_canary_window({})["promote"]
