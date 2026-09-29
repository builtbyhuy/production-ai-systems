"""Supervise a bounded, offline, random-model vLLM CPU functional exercise.

The supervisor, server, gateway, and HTTP probes share one invocation/network namespace.
An aggregate RSS watchdog is an observed-process bound, not a kernel memory sandbox.
No model downloads, untrusted code, trained-adapter claims, or quality claims are involved.
"""

from __future__ import annotations

import argparse
import ast
import asyncio
import contextlib
import hashlib
import json
import os
import platform
import re
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from pais.inference import GatewayConfig, load_test

PROJECT = Path(__file__).resolve().parent
ROOT = PROJECT.parents[1]
GIB = 1024**3
MODEL_NAME = "pais-random-gpt2-one-head-functional"
SOURCE_CONFIG_SHA256 = "7e367bf7127392256f1772799f8f51db58cd2086c76d54991ddf8eff5a42f6fe"
SOURCE_WEIGHTS_SHA256 = "210ad2b451c4b7fa8930d4a7ab67d9263dc4b72bdc89de8c119598dfa305ca77"
PROMPTS = ["State the retry limit.", "Describe the request timeout.", "Name the health check."]
OWN_PROC_PID = int(Path("/proc/self/stat").read_text().split(" ", 1)[0])
OWN_NAMESPACE_INDEX = (
    len(
        next(
            line.split()[1:]
            for line in Path("/proc/self/status").read_text().splitlines()
            if line.startswith("NSpid:")
        )
    )
    - 1
)


class PrerequisiteMissing(RuntimeError):
    """The requested real runtime is not provisioned or violates this bounded profile."""


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def files_manifest(directory: Path) -> dict[str, str]:
    paths = sorted(directory.iterdir())
    if any(path.is_symlink() or not path.is_file() for path in paths):
        raise PrerequisiteMissing("Tiny model must contain only regular files, without symlinks")
    if sum(path.stat().st_size for path in paths) > 10 * 1024**2:
        raise PrerequisiteMissing("This smoke only accepts a <=10 MiB locally authored model")
    return {path.name: sha256(path) for path in paths}


def prepare_model(source: Path, target: Path, supported_heads: list[int]) -> dict[str, Any]:
    """Copy approved random weights, changing only attention head count and provenance."""
    before = files_manifest(source)
    if before.get("config.json") != SOURCE_CONFIG_SHA256:
        raise PrerequisiteMissing("Source config differs from the approved P09 random artifact")
    if before.get("model.safetensors") != SOURCE_WEIGHTS_SHA256:
        raise PrerequisiteMissing("Source weights differ from the approved P09 random artifact")
    source_manifest = json.loads((source / "manifest.json").read_text())
    if any(before.get(name) != digest for name, digest in source_manifest["files"].items()):
        raise PrerequisiteMissing("Original P09 artifact manifest does not match its bytes")
    config = json.loads((source / "config.json").read_text())
    original_head_size = config["n_embd"] // config["n_head"]
    if original_head_size in supported_heads or config["n_embd"] not in supported_heads:
        raise PrerequisiteMissing("Installed CPU head-size contract differs from reviewed profile")
    shutil.copytree(source, target)
    config["n_head"] = 1
    (target / "config.json").write_text(json.dumps(config, indent=2) + "\n")
    (target / "manifest.json").unlink()
    generated = files_manifest(target)
    revision = hashlib.sha256(json.dumps(generated, sort_keys=True).encode()).hexdigest()
    provenance = {
        "origin": "P09 original random initialization, with separately approved config derivative",
        "trained_adapter_served": False,
        "meaningful_model_quality_claim": False,
        "license": "original random weights MIT; GPT-2 implementation Apache-2.0",
        "parameters": source_manifest["parameters"],
        "source_directory": str(source),
        "source_files_sha256": before,
        "original_profile_rejected": True,
        "rejection_scope": "outside advertised CPUAttentionBackend head-size contract; no engine attempt",
        "original_head_size": original_head_size,
        "supported_cpu_head_sizes": supported_heads,
        "transformation": {"n_head": {"from": 2, "to": 1}, "new_head_size": config["n_embd"]},
        "attention_semantics_changed": True,
        "weights_bytes_unchanged": generated["model.safetensors"] == SOURCE_WEIGHTS_SHA256,
        "revision_sha256": revision,
        "files_sha256": generated,
    }
    (target / "manifest.json").write_text(json.dumps(provenance, indent=2) + "\n")
    if files_manifest(source) != before:
        raise RuntimeError("Source model changed while preparing the derivative")
    return provenance


def inspect_runtime(python: Path) -> dict[str, Any]:
    if not python.is_file():
        raise PrerequisiteMissing(f"Provision the isolated CPU vLLM interpreter: {python}")
    code = (
        "import importlib.metadata as m,json,sys,sysconfig; "
        "print(json.dumps({'python':sys.version,'site':sysconfig.get_paths()['purelib'],"
        "'versions':{n:m.version(n) for n in ['vllm','torch','transformers','tokenizers',"
        "'safetensors','uvicorn','httpx']}}))"
    )
    result = subprocess.run(
        [str(python), "-c", code], capture_output=True, text=True, timeout=15, check=False
    )
    if result.returncode:
        raise PrerequisiteMissing(
            "Isolated runtime metadata query failed; provision its dependencies"
        )
    metadata = json.loads(result.stdout)
    if metadata["versions"]["vllm"] != "0.30.0+cpu":
        raise PrerequisiteMissing("This supervisor is checked against vllm==0.30.0+cpu only")
    source = Path(metadata["site"]) / "vllm/v1/attention/backends/cpu_attn.py"
    tree = ast.parse(source.read_text())
    head_sizes = None
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "CPUAttentionBackend":
            for function in node.body:
                if (
                    isinstance(function, ast.FunctionDef)
                    and function.name == "get_supported_head_sizes"
                ):
                    returns = [item for item in function.body if isinstance(item, ast.Return)]
                    if len(returns) == 1:
                        head_sizes = ast.literal_eval(returns[0].value)
    if not isinstance(head_sizes, list) or not all(type(size) is int for size in head_sizes):
        raise PrerequisiteMissing("Cannot inspect declared CPU attention head-size compatibility")
    gpt2 = Path(metadata["site"]) / "vllm/model_executor/models/gpt2.py"
    if not any(
        isinstance(node, ast.ClassDef) and node.name == "GPT2LMHeadModel"
        for node in ast.parse(gpt2.read_text()).body
    ):
        raise PrerequisiteMissing(
            "Installed vLLM has no inspected native GPT2LMHeadModel implementation"
        )
    metadata["cpu_attention_source_sha256"] = sha256(source)
    metadata["gpt2_source_sha256"] = sha256(gpt2)
    metadata["supported_cpu_head_sizes"] = head_sizes
    return metadata


def ipc_prerequisite(directory: Path) -> dict[str, Any]:
    """Check the required normal AF_UNIX transport; never substitute unsupported transports."""
    connection = None
    socket_file = directory / "probe.sock"
    operation = "socket_creation"
    try:
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        operation = "private_socket_bind"
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        connection.bind(os.path.relpath(socket_file, ROOT))
        return {"passed": True, "operation": operation, "transport": "AF_UNIX/SOCK_STREAM"}
    except OSError as exc:
        return {
            "passed": False,
            "operation": operation,
            "transport": "AF_UNIX/SOCK_STREAM",
            "errno": exc.errno,
            "error": str(exc),
        }
    finally:
        if connection is not None:
            connection.close()
        socket_file.unlink(missing_ok=True)
        if directory.is_dir():
            directory.rmdir()


def process_snapshot() -> dict[int, dict[str, int | str]]:
    """Read Linux process identity and RSS without importing the engine's ML libraries."""
    result = {}
    page_size = os.sysconf("SC_PAGE_SIZE")
    for directory in Path("/proc").iterdir():
        if not directory.name.isdigit():
            continue
        try:
            fields = (directory / "stat").read_text().rpartition(")")[2].split()
            namespace_pids = next(
                line.split()[1:]
                for line in (directory / "status").read_text().splitlines()
                if line.startswith("NSpid:")
            )
            result[int(directory.name)] = {
                "state": fields[0],
                "ppid": int(fields[1]),
                "session": int(fields[3]),
                "started": int(fields[19]),
                "rss": max(0, int(fields[21])) * page_size,
                "namespace_pid": int(namespace_pids[OWN_NAMESPACE_INDEX])
                if len(namespace_pids) > OWN_NAMESPACE_INDEX
                else 0,
            }
        except (OSError, ValueError, IndexError, StopIteration):
            continue
    return result


class Supervisor:
    def __init__(self, output: Path, deadline: float):
        self.output, self.deadline = output, deadline
        self.processes: list[tuple[str, subprocess.Popen, Any]] = []
        self.identities: dict[int, int] = {}
        self.root_sessions: set[int] = set()
        self.peak_rss_bytes = 0
        self.failure: str | None = None
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.samples = 0
        self.thread = threading.Thread(target=self.watch, daemon=True)
        self.thread.start()

    def owned(self, snapshot: dict[int, dict]) -> dict[int, dict]:
        with self.lock:
            namespace_roots = {process.pid for _, process, _ in self.processes}
        # /proc may use host PIDs while Popen/kill use this process's nested namespace.
        self.root_sessions.update(
            pid
            for pid, record in snapshot.items()
            if record["ppid"] == OWN_PROC_PID and record["namespace_pid"] in namespace_roots
        )
        selected = {
            pid: record
            for pid, record in snapshot.items()
            if pid != OWN_PROC_PID
            and (
                record["session"] in self.root_sessions
                or self.identities.get(pid) == record["started"]
            )
        }
        while True:
            children = {
                pid: record
                for pid, record in snapshot.items()
                if pid not in selected and record["ppid"] in selected
            }
            if not children:
                break
            selected.update(children)
        for pid, record in selected.items():
            self.identities[pid] = record["started"]
        if OWN_PROC_PID in snapshot:
            selected[OWN_PROC_PID] = snapshot[OWN_PROC_PID]
        return selected

    def signal_owned(self, kind: signal.Signals) -> None:
        with self.lock:
            processes = list(self.processes)
        owned = self.owned(process_snapshot())
        for _, process, _ in processes:
            if any(record["namespace_pid"] == process.pid for record in owned.values()):
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(process.pid, kind)
        for pid, record in owned.items():
            if pid != OWN_PROC_PID and record["state"] != "Z" and record["namespace_pid"] > 0:
                with contextlib.suppress(ProcessLookupError):
                    os.kill(record["namespace_pid"], kind)

    def watch(self) -> None:
        while not self.stop.wait(0.05):
            snapshot = self.owned(process_snapshot())
            total = sum(record["rss"] for record in snapshot.values())
            self.samples += 1
            self.peak_rss_bytes = max(self.peak_rss_bytes, total)
            if total > int(3.75 * GIB):
                self.failure = "aggregate RSS crossed the conservative 3.75 GiB stop threshold"
            if time.monotonic() > self.deadline:
                self.failure = "supervised run exceeded its finite 240-second deadline"
            for _, _, log in list(self.processes):
                if Path(log.name).stat().st_size > 4 * 1024**2:
                    self.failure = "a child log exceeded the 4 MiB output bound"
            if self.failure:
                self.signal_owned(signal.SIGTERM)
                if not self.stop.wait(0.5):
                    self.signal_owned(signal.SIGKILL)
                return

    def launch(
        self, name: str, command: list[str], environment: dict[str, str]
    ) -> subprocess.Popen:
        log = (self.output / f"{name}.log").open("wb")
        try:
            process = subprocess.Popen(
                command,
                cwd=ROOT,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        except OSError:
            log.close()
            raise
        with self.lock:
            self.processes.append((name, process, log))
        # Set affinity before heavy imports/spawn; the declared two-core budget is inherited.
        os.sched_setaffinity(process.pid, sorted(os.sched_getaffinity(0))[:2])
        return process

    def check(self) -> None:
        if self.failure:
            raise RuntimeError(self.failure)

    def cleanup(self) -> dict[str, Any]:
        self.signal_owned(signal.SIGTERM)
        until = time.monotonic() + 5
        while time.monotonic() < until:
            for _, process, _ in self.processes:
                process.poll()
            active = {
                pid: record
                for pid, record in self.owned(process_snapshot()).items()
                if pid != OWN_PROC_PID and record["state"] != "Z"
            }
            if not active:
                break
            time.sleep(0.05)
        self.signal_owned(signal.SIGKILL)
        exits = {}
        for name, process, log in self.processes:
            with contextlib.suppress(subprocess.TimeoutExpired):
                process.wait(timeout=2)
            exits[name] = process.returncode
            log.close()
        self.stop.set()
        self.thread.join(timeout=2)
        remaining = [
            pid
            for pid, record in self.owned(process_snapshot()).items()
            if pid != OWN_PROC_PID and record["state"] != "Z"
        ]
        return {
            "owned_processes_stopped": not remaining,
            "remaining_live_pids": remaining,
            "process_exit_codes": exits,
            "aggregate_peak_rss_bytes": self.peak_rss_bytes,
            "sample_count": self.samples,
            "sample_period_seconds": 0.05,
            "stop_threshold_bytes": int(3.75 * GIB),
            "observed_within_4_gib": self.peak_rss_bytes <= 4 * GIB,
            "kernel_memory_limit_applied": False,
            "rss_measurement": "sum of supervised process RSS; shared pages can be counted twice",
            "pid_mapping": "host /proc PID plus direct-parent/NSpid mapping into the supervisor namespace",
            "watchdog_failure": self.failure,
        }


def free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def metric_total(contents: str, name: str, label: str | None = None) -> float:
    total = 0.0
    for line in contents.splitlines():
        if re.match(re.escape(name) + r"(?:\{|\s)", line) and (label is None or label in line):
            total += float(line.rsplit(" ", 1)[1])
    return total


async def wait_ready(
    url: str, process: subprocess.Popen, supervisor: Supervisor, seconds: int
) -> dict:
    started = time.monotonic()
    async with httpx.AsyncClient(timeout=2, trust_env=False) as client:
        while time.monotonic() - started < seconds:
            supervisor.check()
            if process.poll() is not None:
                raise RuntimeError(
                    f"{url} process exited before readiness with status {process.returncode}"
                )
            try:
                response = await client.get(url)
                if response.status_code == 200:
                    return {"status": 200, "wait_seconds": time.monotonic() - started}
            except httpx.HTTPError:
                pass
            await asyncio.sleep(0.2)
    raise RuntimeError(f"Readiness deadline of {seconds}s exceeded for {url}")


async def probes(
    backend: str, gateway: str, upstream_token: str, gateway_token: str, output: Path
) -> dict:
    backend_headers = {"Authorization": f"Bearer {upstream_token}"}
    gateway_headers = {"Authorization": f"Bearer {gateway_token}"}
    async with httpx.AsyncClient(timeout=20, trust_env=False) as client:
        versions = await client.get(backend + "/version")
        versions.raise_for_status()
        models = await client.get(backend + "/v1/models", headers=backend_headers)
        models.raise_for_status()
        payload = {
            "model": MODEL_NAME,
            "messages": [{"role": "user", "content": PROMPTS[0]}],
            "max_tokens": 8,
            "temperature": 0,
        }
        completion = await client.post(
            backend + "/v1/chat/completions", headers=backend_headers, json=payload
        )
        completion.raise_for_status()
        direct = completion.json()
        before = (await client.get(backend + "/metrics")).text
        (output / "backend-metrics-before.txt").write_text(before)
        unauthenticated = await client.post(gateway + "/v1/chat/completions", json=payload)
        streaming = await load_test(
            gateway, MODEL_NAME, gateway_token, PROMPTS, concurrency=1, max_tokens=16, timeout=20
        )
        burst = await load_test(
            gateway,
            MODEL_NAME,
            gateway_token,
            PROMPTS * 3,
            concurrency=9,
            max_tokens=64,
            timeout=20,
        )
        cancel_before = (await client.get(backend + "/metrics")).text
        cancelled = await load_test(
            gateway,
            MODEL_NAME,
            gateway_token,
            [PROMPTS[1]],
            concurrency=1,
            max_tokens=96,
            timeout=20,
            cancel_every=1,
        )
        # Allow real disconnect cleanup to settle; engine abort is measured, not assumed.
        until = time.monotonic() + 3
        while time.monotonic() < until:
            await asyncio.sleep(0.1)
            gateway_metrics = (await client.get(gateway + "/metrics")).text
            after = (await client.get(backend + "/metrics")).text
            if (
                metric_total(gateway_metrics, "pais_inference_active") == 0
                and metric_total(after, "vllm:num_requests_running") == 0
                and metric_total(after, "vllm:num_requests_waiting") == 0
            ):
                break
        long_payload = {
            **payload,
            "messages": [{"role": "user", "content": "request " * 120}],
            "max_tokens": 16,
            "stream": True,
        }
        context_rejected = await client.post(
            gateway + "/v1/chat/completions", headers=gateway_headers, json=long_payload
        )
        final_metrics = (await client.get(gateway + "/metrics")).text
        drain = await client.post(gateway + "/drain", headers=gateway_headers)
        drained_ready = await client.get(gateway + "/ready")
        drained_request = await client.post(
            gateway + "/v1/chat/completions",
            headers=gateway_headers,
            json={**payload, "stream": True},
        )
        after = (await client.get(backend + "/metrics")).text
        (output / "backend-metrics-after.txt").write_text(after)
        (output / "gateway-metrics-final.txt").write_text(final_metrics)
    abort_delta = metric_total(
        after, "vllm:request_success_total", 'finished_reason="abort"'
    ) - metric_total(cancel_before, "vllm:request_success_total", 'finished_reason="abort"')
    status_counts = dict(Counter(str(row.get("http_status")) for row in burst["records"]))
    checks = {
        "version_endpoint_matches_installed": versions.json().get("version") == "0.30.0+cpu",
        "model_endpoint_matches_provisioned": any(
            item.get("id") == MODEL_NAME for item in models.json()["data"]
        ),
        "direct_generated_content_and_usage": bool(direct["choices"][0]["message"]["content"])
        and direct.get("usage", {}).get("completion_tokens", 0) > 0,
        "authenticated_gateway": unauthenticated.status_code == 401,
        "all_sequential_streams_complete": streaming["successful"] == len(PROMPTS)
        and streaming["errors"] == 0,
        "bounded_burst_rejected_excess": status_counts.get("503", 0) > 0
        and burst["successful"] > 0
        and set(status_counts) <= {"200", "503"},
        "client_closed_stream": cancelled["cancelled"] == 1,
        "admission_capacity_recovered": metric_total(final_metrics, "pais_inference_active") == 0
        and metric_total(final_metrics, "pais_inference_queued") == 0,
        "tokenized_context_overflow_rejected": context_rejected.status_code == 422,
        "drain_rejects_new_requests": drain.status_code == 200
        and drained_ready.status_code == 503
        and drained_request.status_code == 503,
    }
    return {
        "checks": checks,
        "server_version": versions.json(),
        "models": models.json(),
        "direct_completion": direct,
        "sequential_streams": streaming,
        "admission_burst": burst,
        "admission_burst_http_status_counts": status_counts,
        "cancellation": cancelled,
        "engine_abort_counter_delta": abort_delta,
        "engine_cancellation_observed": abort_delta > 0,
        "engine_cancellation_caveat": "A client close and admission release alone do not establish that engine work was interrupted.",
        "post_cancel_running": metric_total(after, "vllm:num_requests_running"),
        "post_cancel_waiting": metric_total(after, "vllm:num_requests_waiting"),
        "context_rejection_status": context_rejected.status_code,
        "warmup": "gateway readiness required backend health plus nonempty two-token chat generation",
    }


def git_state() -> dict[str, Any]:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False
    )
    dirty = subprocess.run(
        ["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True, check=False
    )
    revision = commit.stdout.strip()
    return {
        "commit": revision
        if commit.returncode == 0 and re.fullmatch(r"[a-f0-9]{40,64}", revision)
        else None,
        "unborn_or_unavailable": commit.returncode != 0,
        "dirty": bool(dirty.stdout.strip()),
    }


async def execute(args: argparse.Namespace, report: dict[str, Any]) -> None:
    runtime = inspect_runtime(args.runtime_python)
    report["runtime"] = runtime
    report["ipc_prerequisite"] = ipc_prerequisite(args.output / "ipc-prerequisite")
    if not report["ipc_prerequisite"]["passed"]:
        failure = report["ipc_prerequisite"]
        raise PrerequisiteMissing(
            f"vLLM single-engine async serving requires AF_UNIX IPC; {failure['operation']} "
            f"failed with errno {failure['errno']}. Use a provisioned host that permits this transport."
        )
    report["model"] = prepare_model(
        args.source_model, args.output / "model", runtime["supported_cpu_head_sizes"]
    )
    model_dir = args.output / "model"
    backend_port, gateway_port = free_port(), free_port()
    while gateway_port == backend_port:
        gateway_port = free_port()
    backend, gateway = f"http://127.0.0.1:{backend_port}", f"http://127.0.0.1:{gateway_port}"
    env = dict(os.environ)
    env.update(
        {
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "HF_HUB_DISABLE_TELEMETRY": "1",
            "VLLM_NO_USAGE_STATS": "1",
            "DO_NOT_TRACK": "1",
            "TOKENIZERS_PARALLELISM": "false",
            "VLLM_CPU_KVCACHE_SPACE": "1",
            "VLLM_CPU_OMP_THREADS_BIND": "nobind",
            "OMP_NUM_THREADS": "2",
            "MKL_NUM_THREADS": "2",
            "OPENBLAS_NUM_THREADS": "1",
            "PYTHONPATH": str(ROOT / "packages"),
        }
    )
    upstream_token, gateway_token = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    env["VLLM_API_KEY"] = upstream_token
    command = [
        str(args.runtime_python),
        "-m",
        "vllm.entrypoints.cli.main",
        "serve",
        str(model_dir),
        "--served-model-name",
        MODEL_NAME,
        "--host",
        "127.0.0.1",
        "--port",
        str(backend_port),
        "--dtype",
        "float32",
        "--max-model-len",
        "128",
        "--max-num-seqs",
        "2",
        "--max-num-batched-tokens",
        "128",
        "--block-size",
        "32",
        "--enable-prefix-caching",
        "--enforce-eager",
        "--chat-template",
        str(PROJECT / "chat-template.jinja"),
        "--chat-template-content-format",
        "string",
        "--api-server-count",
        "1",
        "--disable-uvicorn-access-log",
    ]
    config = GatewayConfig(
        model=MODEL_NAME,
        backends=[backend],
        max_inflight=1,
        max_queue=0,
        queue_timeout_seconds=1,
        request_timeout_seconds=20,
        health_interval_seconds=2,
        max_context_tokens=128,
        max_output_tokens=96,
    )
    config_file = args.output / "gateway-config.json"
    config_file.write_text(config.model_dump_json(indent=2) + "\n")
    gateway_command = [
        sys.executable,
        "-m",
        "uvicorn",
        "pais.inference:create_gateway_app",
        "--factory",
        "--host",
        "127.0.0.1",
        "--port",
        str(gateway_port),
        "--workers",
        "1",
        "--no-access-log",
    ]
    report.update(
        {
            "commands": {"server": command, "gateway": gateway_command},
            "profile": {
                "backend": "cpu",
                "dtype": "float32",
                "quantization": None,
                "max_model_len": 128,
                "max_num_seqs": 2,
                "max_num_batched_tokens": 128,
                "block_size": 32,
                "prefix_caching": True,
                "cpu_kv_cache_gib": 1,
                "enforce_eager": True,
                "cpu_affinity": sorted(os.sched_getaffinity(0))[:2],
                "omp_threads": 2,
                "replicas": 1,
                "gateway_inflight": 1,
                "gateway_queue": 0,
            },
            "prompts": PROMPTS,
            "prompts_sha256": hashlib.sha256(json.dumps(PROMPTS).encode()).hexdigest(),
            "chat_template_sha256": sha256(PROJECT / "chat-template.jinja"),
        }
    )
    supervisor = Supervisor(args.output, time.monotonic() + 240)
    try:
        help_command = [
            str(args.runtime_python),
            "-m",
            "vllm.entrypoints.cli.main",
            "serve",
            "--help=all",
        ]
        report["commands"]["cli_compatibility"] = help_command
        help_process = supervisor.launch("cli-help", help_command, env)
        try:
            await asyncio.to_thread(help_process.wait, timeout=35)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("Installed vLLM CLI help exceeded 35 seconds") from exc
        if help_process.returncode:
            raise RuntimeError(
                f"Installed vLLM CLI failed with exit {help_process.returncode}; see cli-help.log"
            )
        help_text = (args.output / "cli-help.log").read_text()
        flags = [argument for argument in command if argument.startswith("--")]
        missing = [flag for flag in flags if flag not in help_text]
        if missing:
            raise RuntimeError(f"Installed vLLM help did not advertise configured flags: {missing}")
        report["cli_flags_verified"] = flags
        server_process = supervisor.launch("vllm-server", command, env)
        report["backend_readiness"] = await wait_ready(
            backend + "/health", server_process, supervisor, 120
        )
        gateway_env = {
            **env,
            "PAIS_INFERENCE_GATEWAY_CONFIG": str(config_file),
            "PAIS_INFERENCE_GATEWAY_TOKEN": gateway_token,
        }
        gateway_process = supervisor.launch("gateway", gateway_command, gateway_env)
        report["gateway_readiness"] = await wait_ready(
            gateway + "/ready", gateway_process, supervisor, 25
        )
        report["measurements"] = await asyncio.wait_for(
            probes(backend, gateway, upstream_token, gateway_token, args.output), timeout=60
        )
        supervisor.check()
        report["inference_identity_verified"] = True
        report["checks"] = report["measurements"]["checks"]
    finally:
        report["resources"] = supervisor.cleanup()
        report.setdefault("checks", {}).update(
            {
                "owned_processes_stopped": report["resources"]["owned_processes_stopped"],
                "observed_within_4_gib": report["resources"]["observed_within_4_gib"],
                "watchdog_not_triggered": report["resources"]["watchdog_failure"] is None,
                "p09_original_preserved": files_manifest(args.source_model)
                == report["model"]["source_files_sha256"],
            }
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-python", required=True, type=Path)
    parser.add_argument(
        "--source-model", type=Path, default=ROOT / "artifacts/p09-smoke/base-model"
    )
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.runtime_python = args.runtime_python.absolute()
    args.source_model = args.source_model.resolve()
    args.output = args.output.absolute()
    if args.output.exists():
        parser.error("Output directory must be new; preserve earlier evidence runs")
    args.output.mkdir(parents=True)
    report: dict[str, Any] = {
        "schema_version": "pais.p14.cpu-functional.v1",
        "status": "failed",
        "started_at": datetime.now(UTC).isoformat(),
        "evidence_profile": "local-functional",
        "inference_identity_verified": False,
        "command": [sys.executable, *sys.argv],
        "git": git_state(),
        "hardware": {"platform": platform.platform(), "machine": platform.machine()},
        "runtime_lock_sha256": sha256(PROJECT / "runtime-cpu.lock.txt"),
        "supervisor_source_sha256": sha256(Path(__file__)),
        "limitations": [
            "39,456-parameter random functional derivative; no model quality or trained-adapter claim",
            "one configured CPU server; no cluster, multi-replica balancing/recovery, or GPU performance evidence",
            "prefix cache is configured; no batching/cache/quantization comparative experiment",
            "harness timings, if produced, characterize only the declared tiny workload",
            "RSS watchdog samples aggregate RSS; no kernel-enforced per-run cgroup memory boundary",
        ],
    }
    for name in ("memory.max", "cpu.max"):
        path = Path("/sys/fs/cgroup") / name
        if path.exists():
            report["hardware"][f"cgroup_{name}"] = path.read_text().strip()
    exit_code = 1
    try:
        if platform.system() != "Linux":
            raise PrerequisiteMissing(
                "The bounded CPU supervisor requires Linux /proc and affinity"
            )
        asyncio.run(execute(args, report))
        if report["inference_identity_verified"] and all(report["checks"].values()):
            report["status"] = "passed"
            exit_code = 0
    except PrerequisiteMissing as exc:
        report.update({"status": "blocked", "error": str(exc), "error_type": type(exc).__name__})
        exit_code = 2
    except (OSError, ValueError, RuntimeError, TimeoutError, KeyError, httpx.HTTPError) as exc:
        report.update({"error": str(exc), "error_type": type(exc).__name__})
    report["finished_at"] = datetime.now(UTC).isoformat()
    report["exit_code"] = exit_code
    report["logs_sha256"] = {path.name: sha256(path) for path in sorted(args.output.glob("*.log"))}
    report_path = args.output / "report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {
                "status": report["status"],
                "exit_code": exit_code,
                "report": str(report_path),
                "error": report.get("error"),
            }
        )
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
