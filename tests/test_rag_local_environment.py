"""Local launcher authentication boundary, independent of an unavailable Docker runtime."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "projects/07-local-first/container_entrypoint.py"
TOKEN = "fixture-opaque-credential-for-launcher-tests"


@pytest.fixture
def launcher():
    spec = importlib.util.spec_from_file_location("p07_launcher", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_local_launcher_preserves_trusted_identity_and_disables_fixture_auth(launcher, tmp_path, monkeypatch):
    source = tmp_path / "credentials.json"
    credentials = {TOKEN: {"subject": "operator", "tenant_id": "authorized-workspace", "roles": ["writer"]}}
    source.write_text(json.dumps(credentials))
    monkeypatch.setenv("PAIS_AUTH_TOKENS_FILE", str(source))
    monkeypatch.setenv("PAIS_ALLOW_FIXTURE_AUTH", "1")
    monkeypatch.setenv("PAIS_PROFILE", "fixture")
    monkeypatch.setenv("A_CUSTOM_PROXY_CONFIGURATION", "fixture-value-not-to-be-exported")
    runtime = launcher.runtime_environment()
    assert json.loads(runtime["PAIS_AUTH_TOKENS"]) == credentials
    assert runtime["PAIS_ALLOW_FIXTURE_AUTH"] == "0"
    assert runtime["PAIS_PROFILE"] == "local"
    assert runtime["HF_HUB_OFFLINE"] == "1"
    assert not any("proxy" in key.casefold() for key in runtime)


@pytest.mark.parametrize("credentials", [
    {},
    {"weak": {"subject": "operator", "tenant_id": "workspace", "roles": ["admin"]}},
    {TOKEN: {"subject": "operator", "tenant_id": "", "roles": ["admin"]}},
    {TOKEN: {"subject": "operator", "tenant_id": "workspace", "roles": ["owner"]}},
])
def test_invalid_launcher_identity_never_starts_api(launcher, tmp_path, monkeypatch, capsys, credentials):
    source = tmp_path / "credentials.json"
    source.write_text(json.dumps(credentials))
    monkeypatch.setenv("PAIS_AUTH_TOKENS_FILE", str(source))

    def forbidden_exec(*args):
        pytest.fail("An invalid credential mapping must never start the protected API")

    monkeypatch.setattr(launcher.os, "execvpe", forbidden_exec)
    assert launcher.main() == 2
    assert TOKEN not in capsys.readouterr().err


def test_missing_launcher_secret_never_uses_environment_credentials(launcher, tmp_path, monkeypatch):
    monkeypatch.setenv("PAIS_AUTH_TOKENS_FILE", str(tmp_path / "missing.json"))
    monkeypatch.setenv("PAIS_AUTH_TOKENS", json.dumps({TOKEN: {
        "subject": "operator", "tenant_id": "workspace", "roles": ["admin"]}}))
    assert launcher.main() == 2


def test_offline_result_revokes_verification_if_boundary_changes(tmp_path, monkeypatch):
    script = SCRIPT.with_name("offline_acceptance.py")
    spec = importlib.util.spec_from_file_location("p07_offline", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    boundaries = iter([
        {"verified": True, "scope": "fixture boundary", "limitation": "test only"},
        {"verified": False, "scope": "fixture boundary", "limitation": "changed during test"},
    ])
    monkeypatch.setattr(module, "network_boundary", lambda: next(boundaries))
    monkeypatch.setattr(module, "demo", lambda **_: {"checks": {"fixture": True}})
    monkeypatch.setattr(module, "manifest", lambda *_: {"profile": "fixture", "scope": "unit test"})
    monkeypatch.setattr(module, "ROOT", tmp_path)
    output = tmp_path / "changed-boundary.json"
    assert module.worker("sqlite", output) == 1
    report = json.loads(output.read_text())
    assert report["exit_status"] == 1
    assert report["result"]["offline_network_isolation_verified"] is False
