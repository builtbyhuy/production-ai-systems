from __future__ import annotations

import copy
import multiprocessing
import sqlite3
from concurrent.futures import ThreadPoolExecutor

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


def _report():
    return {
        "profile": "local",
        "suite": "release",
        "summary": {
            "total": 100,
            "passed": 100,
            "failed": 0,
            "errors": 0,
            "skipped": 0,
            "gate_passed": True,
            "deployment_eligible": True,
        },
        "results": [
            {"case_id": f"case-{i}", "passed": True, "profile": "local"} for i in range(100)
        ],
        "required_cases": 100,
        "framework_metrics": {"fixture_contract_only": True},
        "manifest": {
            "commit": "a" * 40, "dirty_tree": False, "profile": "local",
            "timestamp_utc": "2026-09-29T00:00:00Z", "source_snapshot_sha256": "b" * 64,
            "dataset_hashes": {"fixture": "c" * 64},
            "dependency_versions": {"contract-fixture": "1"},
            "models": {"lock_sha256": "d" * 64},
        },
    }


def test_release_evidence_requires_real_complete_unique_cases():
    assert validate_release_evaluation(_report(), "a" * 40)["accepted"]
    variants = []
    for key, value in (("profile", "fixture"), ("manifest", {})):
        report = _report()
        report[key] = value
        variants.append(report)
    report = _report()
    report["summary"]["skipped"] = 1
    variants.append(report)
    report = _report()
    report["results"][1]["case_id"] = report["results"][0]["case_id"]
    variants.append(report)
    report = _report()
    report["results"][0]["profile"] = "fixture"
    variants.append(report)
    report = _report()
    report["results"][0]["passed"] = False
    variants.append(report)
    for invalid in variants:
        with pytest.raises(ReleaseRejected):
            validate_release_evaluation(invalid, "a" * 40)
    with pytest.raises(ReleaseRejected):
        validate_release_evaluation(_report(), "b" * 40)


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
