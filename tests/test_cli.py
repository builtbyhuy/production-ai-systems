"""The demo command must not report a failed acceptance assertion as success."""

import json
from types import SimpleNamespace

from pais import cli


def test_p03_tool_failure_returns_nonzero_and_preserves_failed_runs(monkeypatch, tmp_path):
    from pais.research import ResearchService

    def unavailable(*args):
        raise RuntimeError("controlled corpus unavailable")

    # Exercise the in-process P03 dispatcher; LangGraph itself still runs.
    monkeypatch.setattr(cli.sys, "prefix", str(cli.ROOT / "projects/03-multi-agent-research/.venv"))
    monkeypatch.setattr(ResearchService, "_lookup", unavailable)
    target = tmp_path / "failed-research.json"
    assert cli._demo("03", "fixture", target, "sqlite") == 1
    report = json.loads(target.read_text())
    assert report["exit_status"] == 1
    assert report["result"]["acceptance"] is False
    for name in ("accepted_run", "rejected_run"):
        run = report["result"][name]
        assert run["status"] == "failed" and run["actual_langgraph"] is True
        assert run["tools_executed"] == [] and run["calls"] == 2


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


def test_setup_stops_when_required_validator_installation_fails(monkeypatch):
    commands = []

    def install(command, **kwargs):
        commands.append(command)
        failed = "projects/06-security-guardrails" in command
        return SimpleNamespace(returncode=7 if failed else 0)

    monkeypatch.setattr(cli.subprocess, "run", install)
    assert cli.main(["setup", "--profile", "local"]) == 7
    assert commands[-1][-1] == "projects/06-security-guardrails"
    assert not any("projects/09-lora-training" in command for command in commands)
