"""Fail-closed untrusted Python execution through an explicit rootless Docker boundary.

The host subprocess is only the container control client. Python submissions never execute
on the host. Containers share a kernel: use a dedicated VM/microVM for hostile multi-tenant
public workloads. Merely finding bwrap/docker on PATH is not sufficient authorization.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
from dataclasses import asdict, dataclass, field

from pais.contracts import new_id


class SandboxUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class SandboxLimits:
    wall_seconds: float = 5
    cpu_seconds: int = 2
    memory_mb: int = 256
    processes: int = 32
    output_bytes: int = 65536

    def __post_init__(self):
        if not (0 < self.wall_seconds <= 60 and 1 <= self.cpu_seconds <= 30
                and 32 <= self.memory_mb <= 2048 and 1 <= self.processes <= 128
                and 1024 <= self.output_bytes <= 1_048_576):
            raise ValueError("Sandbox limits exceed permitted functional-profile bounds")


@dataclass
class SandboxResult:
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool
    truncated: bool
    boundary: str = "rootless-docker-cgroupv2"
    evidence: dict = field(default_factory=dict)


_WRAPPER = """import io,json,sys
payload=json.load(sys.stdin)
sys.stdin=io.StringIO(payload['stdin'])
sys.argv=['submission.py']
exec(compile(payload['code'],'<submission>','exec'),{'__name__':'__main__'})
"""


class SandboxRunner:
    def __init__(self, image: str | None = None, runtime: str = "docker", enabled: bool = False,
                 limits: SandboxLimits | None = None, endpoint: str | None = None):
        self.image = image
        self.runtime = runtime
        self.enabled = enabled
        self.limits = limits or SandboxLimits()
        self.endpoint = endpoint or f"unix:///run/user/{os.getuid()}/docker.sock"
        self._env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin")}

    def _client(self) -> list[str]:
        if self.runtime != "docker" or not shutil.which(self.runtime):
            raise SandboxUnavailable("A supported Docker client and rootless daemon are required")
        if not re.fullmatch(r"unix:///[-A-Za-z0-9_./]+", self.endpoint):
            raise SandboxUnavailable("Sandbox daemon must use an explicit local Unix socket")
        return [self.runtime, "--host", self.endpoint]

    def _control(self, args: list[str], timeout: float = 5):
        try:
            return subprocess.run(self._client()+args, capture_output=True, text=True,
                                  timeout=timeout, env=self._env, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise SandboxUnavailable("Container control plane unavailable") from exc

    def preflight(self) -> dict:
        if not self.enabled:
            raise SandboxUnavailable("Execution disabled: explicit sandbox enablement is required")
        if not self.image or not re.fullmatch(r"(?:[A-Za-z0-9_./:-]+@)?sha256:[a-f0-9]{64}", self.image):
            raise SandboxUnavailable("A preprovisioned, audited, digest-pinned Python image is required")
        result = self._control(["info", "--format", "{{json .}}"])
        if result.returncode:
            raise SandboxUnavailable("Rootless Docker daemon is not reachable")
        try:
            info = json.loads(result.stdout)
        except (ValueError, TypeError) as exc:
            raise SandboxUnavailable("Cannot verify container daemon security configuration") from exc
        options = " ".join(info.get("SecurityOptions", []))
        required = {"rootless": "rootless" in options, "seccomp": "seccomp" in options,
                    "cgroup_v2": str(info.get("CgroupVersion")) == "2",
                    "memory_limit": info.get("MemoryLimit") is True,
                    "pids_limit": info.get("PidsLimit") is True,
                    "cpu_quota": info.get("CPUCfsQuota") is True,
                    "linux": info.get("OSType") == "linux"}
        if not all(required.values()):
            missing = ", ".join(key for key, present in required.items() if not present)
            raise SandboxUnavailable(f"Required sandbox protections not verified: {missing}")
        image_info = self._control(["image", "inspect", self.image])
        if image_info.returncode:
            raise SandboxUnavailable("Pinned image is missing; automatic image pulls are forbidden")
        return {"boundary": "rootless-docker-cgroupv2", "image": self.image,
                "server_version": info.get("ServerVersion"), "checks": required,
                "shared_kernel": True, "network": "none", "host_mounts": []}

    def command(self, name: str, limits: SandboxLimits | None = None) -> list[str]:
        """Trusted fixed command. Submission code travels over stdin, never in shell syntax."""
        selected = limits or self.limits
        for key, value in asdict(selected).items():
            if value > getattr(self.limits, key):
                raise ValueError("A submission cannot increase the configured sandbox limits")
        return self._client()+[
            "run", "--rm", "--pull=never", "--name", name, "--network=none", "--ipc=none",
            "--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges:true",
            "--user=65534:65534", f"--pids-limit={selected.processes}", "--cpus=1",
            f"--memory={selected.memory_mb}m", f"--memory-swap={selected.memory_mb}m",
            f"--ulimit=cpu={selected.cpu_seconds}:{selected.cpu_seconds}",
            "--ulimit=nofile=64:64", "--ulimit=core=0:0", "--hostname=sandbox",
            "--tmpfs=/tmp:rw,noexec,nosuid,nodev,size=16m,mode=1777", "--workdir=/tmp",
            "--env=PYTHONDONTWRITEBYTECODE=1", "--entrypoint=/usr/local/bin/python", "-i",
            self.image or "", "-I", "-u", "-c", _WRAPPER,
        ]

    def run_python(self, code: str, stdin: str = "", limits: SandboxLimits | None = None) -> SandboxResult:
        if not isinstance(code, str) or not code.strip() or len(code.encode()) > 256_000:
            raise ValueError("Submission must contain 1 to 256000 bytes of Python source")
        if not isinstance(stdin, str) or len(stdin.encode()) > 1_000_000:
            raise ValueError("Submission stdin is too large")
        evidence = self.preflight()  # No host execution fallback, including when disabled.
        selected = limits or self.limits
        name = f"pais-sandbox-{new_id()}"
        command = self.command(name, selected)
        payload = json.dumps({"code": code, "stdin": stdin}).encode()
        start = time.perf_counter()
        proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, env=self._env)
        chunks: dict[str, bytearray] = {"stdout": bytearray(), "stderr": bytearray()}
        lock = threading.Lock()
        overflow = threading.Event()
        total = 0

        def reader(stream, key):
            nonlocal total
            while True:
                data = stream.read(4096)
                if not data:
                    break
                with lock:
                    remaining = max(0, selected.output_bytes-total)
                    chunks[key].extend(data[:remaining])
                    total += len(data)
                    if total > selected.output_bytes:
                        overflow.set()

        def writer():
            try:
                proc.stdin.write(payload)
                proc.stdin.close()
            except (BrokenPipeError, OSError):
                pass

        threads = [threading.Thread(target=reader, args=(proc.stdout, "stdout"), daemon=True),
                   threading.Thread(target=reader, args=(proc.stderr, "stderr"), daemon=True),
                   threading.Thread(target=writer, daemon=True)]
        for thread in threads:
            thread.start()
        timed_out = False
        try:
            while proc.poll() is None:
                timed_out = time.perf_counter()-start > selected.wall_seconds
                if timed_out or overflow.is_set():
                    # Kill the actual container; killing only the client can leave work running.
                    self._control(["rm", "--force", name])
                    proc.kill()
                    break
                time.sleep(0.01)
            proc.wait(timeout=5)
        finally:
            try:
                self._control(["rm", "--force", name])
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait(timeout=5)
                for thread in threads:
                    thread.join(timeout=1)
        evidence["limits"] = asdict(selected)
        return SandboxResult(proc.returncode, chunks["stdout"].decode(errors="replace"),
                             chunks["stderr"].decode(errors="replace"), time.perf_counter()-start,
                             timed_out, overflow.is_set(), evidence=evidence)

    def execute(self, code: str, input_data: str | None = None) -> SandboxResult:
        return self.run_python(code, stdin=input_data or "")
