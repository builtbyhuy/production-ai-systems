"""The demo command must not report a failed acceptance assertion as success."""

import json
from types import SimpleNamespace

from pais import cli


def test_demo_failed_check_returns_nonzero_and_preserves_report(monkeypatch, tmp_path):
    module = SimpleNamespace(
        demo=lambda profile: {
            "checks": {"source_exists": True, "citation_span_valid": False},
            "actual_model_output": "unsupported citation",
        }
    )
    monkeypatch.setattr(cli.importlib, "import_module", lambda name: module)
    monkeypatch.setattr(cli, "manifest", lambda *args: {"profile": "fixture"})
    target = tmp_path / "failed-demo.json"
    assert cli._demo("01", "fixture", target, "sqlite") == 1
    report = json.loads(target.read_text())
    assert report["exit_status"] == 1
    assert report["result"]["checks"]["citation_span_valid"] is False


def test_demo_missing_required_boundary_is_blocked(monkeypatch, tmp_path):
    module = SimpleNamespace(demo=lambda profile: {"status": "blocked", "reason": "No sandbox"})
    monkeypatch.setattr(cli.importlib, "import_module", lambda name: module)
    monkeypatch.setattr(cli, "manifest", lambda *args: {"profile": "fixture"})
    target = tmp_path / "blocked-demo.json"
    assert cli._demo("17", "fixture", target, "sqlite") == 2
    assert json.loads(target.read_text())["exit_status"] == 2
