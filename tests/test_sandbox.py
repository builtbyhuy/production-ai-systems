import pytest
from pais.sandbox import SandboxLimits, SandboxRunner, SandboxUnavailable


def test_execution_disabled_before_any_subprocess(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("host subprocess must not run")
    monkeypatch.setattr("pais.sandbox.subprocess.Popen", forbidden)
    with pytest.raises(SandboxUnavailable, match="disabled"):
        SandboxRunner().run_python("print('never runs')")


def test_unpinned_image_and_remote_daemon_rejected(monkeypatch):
    with pytest.raises(SandboxUnavailable, match="digest-pinned"):
        SandboxRunner(image="python:latest", enabled=True).preflight()
    monkeypatch.setattr("pais.sandbox.shutil.which", lambda _: "/usr/bin/docker")
    with pytest.raises(SandboxUnavailable, match="local Unix socket"):
        SandboxRunner(endpoint="tcp://remote:2375")._client()


def test_command_contains_real_resource_and_isolation_controls(monkeypatch):
    monkeypatch.setattr("pais.sandbox.shutil.which", lambda _: "/usr/bin/docker")
    runner = SandboxRunner(image="sha256:"+"a"*64)
    command = runner.command("test")
    for flag in ("--network=none", "--read-only", "--cap-drop=ALL", "--user=65534:65534",
                 "--pids-limit=32", "--memory=256m", "--memory-swap=256m", "--pull=never",
                 "--security-opt=no-new-privileges:true", "--ulimit=cpu=2:2"):
        assert flag in command
    assert "--privileged" not in command and "--volume" not in command
    with pytest.raises(ValueError):
        runner.command("test", SandboxLimits(memory_mb=512))


def test_daemon_security_capability_probe_fails_closed(monkeypatch):
    from types import SimpleNamespace
    runner = SandboxRunner(image="sha256:"+"a"*64, enabled=True)
    monkeypatch.setattr(runner, "_control", lambda _: SimpleNamespace(
        returncode=0, stdout='{"SecurityOptions":[],"CgroupVersion":"1"}'))
    with pytest.raises(SandboxUnavailable, match="protections not verified"):
        runner.preflight()
