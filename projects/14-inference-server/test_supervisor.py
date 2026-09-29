"""Failure-path checks for the real Linux supervisor; no model runtime is launched."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "p14_smoke", Path(__file__).with_name("run_cpu_smoke.py")
)
assert SPEC and SPEC.loader
SMOKE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SMOKE)


def test_supervisor_maps_namespace_pids_and_only_cleans_owned_processes(tmp_path):
    unrelated = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(20)"], start_new_session=True
    )
    supervisor = SMOKE.Supervisor(tmp_path, time.monotonic() + 5)
    try:
        process = supervisor.launch(
            "owned", [sys.executable, "-c", "import time; time.sleep(20)"], dict(os.environ)
        )
        until = time.monotonic() + 2
        observed = False
        while time.monotonic() < until:
            rows = supervisor.owned(SMOKE.process_snapshot())
            observed = any(row["namespace_pid"] == process.pid for row in rows.values())
            if observed and supervisor.samples > 0:
                break
            time.sleep(0.02)
        assert observed
        assert not any(row["namespace_pid"] == unrelated.pid for row in rows.values())
        report = supervisor.cleanup()
        assert report["owned_processes_stopped"]
        assert report["aggregate_peak_rss_bytes"] > 0
        assert unrelated.poll() is None
    finally:
        supervisor.cleanup()
        unrelated.terminate()
        unrelated.wait(timeout=2)


def test_changed_source_is_rejected_before_derivative_is_written(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "config.json").write_text('{"n_embd": 32, "n_head": 2}')
    target = tmp_path / "derived"
    with pytest.raises(SMOKE.PrerequisiteMissing, match="Source config differs"):
        SMOKE.prepare_model(source, target, [32, 64])
    assert not target.exists()


def test_ipc_permission_failure_is_explicit_and_does_not_create_transport(tmp_path, monkeypatch):
    def denied_socket(*_args, **_kwargs):
        raise PermissionError(1, "Operation not permitted")

    monkeypatch.setattr(SMOKE.socket, "socket", denied_socket)
    result = SMOKE.ipc_prerequisite(tmp_path / "private-rpc")
    assert result["passed"] is False
    assert result["operation"] == "socket_creation"
    assert result["errno"] == 1
    assert not (tmp_path / "private-rpc").exists()
