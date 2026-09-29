"""Reproducible local evidence; no implicit telemetry or credential export."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import re
import resource
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from pais.contracts import utcnow

ROOT = Path(__file__).resolve().parents[2]


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def hardware() -> dict:
    name = platform.processor()
    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.exists():
        name = next(
            (
                line.split(":", 1)[1].strip()
                for line in cpuinfo.read_text().splitlines()
                if line.startswith("model name")
            ),
            name,
        )
    memory = Path("/sys/fs/cgroup/memory.max")
    quota = Path("/sys/fs/cgroup/cpu.max")
    return {
        "cpu_model": name,
        "architecture": platform.machine(),
        "memory_cgroup_bytes": memory.read_text().strip() if memory.exists() else None,
        "cpu_cgroup_quota": quota.read_text().strip() if quota.exists() else None,
    }


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for part in iter(lambda: f.read(1024 * 1024), b""):
            h.update(part)
    return h.hexdigest()


def _git(*args: str) -> str:
    p = subprocess.run(["git", *args], cwd=ROOT, text=True, capture_output=True, check=False)
    return p.stdout.strip() if p.returncode == 0 else ""


def redact(value: str) -> str:
    value = re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._-]+", r"\1[REDACTED]", value)
    return re.sub(
        r"(?i)((?:api[_-]?key|token|secret|password)[=:]\s*)[^\s,;]+", r"\1[REDACTED]", value
    )


def manifest(profile: str, command: list[str] | str, config: dict | None = None) -> dict:
    files = _git("ls-files", "--cached", "--others", "--exclude-standard").splitlines()
    hashes = {
        name: sha256(ROOT / name)
        for name in files
        if (ROOT / name).is_file()
        and not name.startswith("artifacts/")
        and "/evidence/" not in name
        and not name.endswith("/EVIDENCE.json")
    }
    snapshot = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
    datasets = {
        str(p.relative_to(ROOT)): sha256(p) for p in sorted((ROOT / "evals").glob("*.json"))
    }
    deps = {
        d.metadata["Name"]: d.version
        for d in importlib.metadata.distributions()
        if d.metadata.get("Name")
    }
    model_lock = os.environ.get("PAIS_MODEL_LOCK")
    models = None
    if model_lock and Path(model_lock).is_file():
        models = {
            "lock_sha256": sha256(Path(model_lock)),
            "configuration": json.loads(Path(model_lock).read_text()),
        }
    inventory_path = os.environ.get("PAIS_MODEL_INVENTORY")
    inventory = (
        json.loads(Path(inventory_path).read_text())
        if inventory_path and Path(inventory_path).is_file()
        else None
    )
    return {
        "schema_version": 1,
        "timestamp_utc": utcnow(),
        "profile": profile,
        "command": redact(command if isinstance(command, str) else " ".join(command)),
        "git_commit": _git("rev-parse", "HEAD") or None,
        "dirty_tree": bool(_git("status", "--porcelain")),
        "source_snapshot_sha256": snapshot,
        "source_file_hashes": hashes,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "machine": platform.machine(),
        "hardware": hardware(),
        "dependency_versions": dict(sorted(deps.items())),
        "dataset_hashes": datasets,
        "models": models,
        "provisioned_model_inventory": inventory,
        "configuration": config or {},
        "api_spending_authorized_microusd": 0,
        "stochasticity": "Single-run evidence unless explicitly repeated; seed/config recorded by adapter. Stochastic variability unmeasured; no stability claim.",
    }


def write_report(path: str | Path, report: dict | list) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str) + "\n")
    tmp.replace(path)
    return path


def capture(command: list[str], profile: str, output: str | Path) -> int:
    if not command:
        raise ValueError("An executable command is required after --")
    report = {"manifest": manifest(profile, command)}
    started = time.perf_counter()
    p = subprocess.run(
        command, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False
    )
    text = redact(p.stdout)
    output = Path(output)
    log = output.with_suffix(".log")
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(text)
    report.update(
        {
            "exit_status": p.returncode,
            "elapsed_seconds": time.perf_counter() - started,
            "max_child_rss_kib": resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss,
            "output_log": str(log),
            "output_sha256": sha256(log),
            "output_tail": text[-16000:],
        }
    )
    write_report(output, report)
    print(text[-8000:])
    print(f"Evidence: {output}")
    return p.returncode


def doctor() -> dict[str, Any]:
    tools = {
        name: shutil.which(name)
        for name in [
            "python",
            "node",
            "npm",
            "uv",
            "git",
            "docker",
            "kubectl",
            "ollama",
            "redis-server",
            "bwrap",
            "nvidia-smi",
        ]
    }
    local_ollama = ROOT / ".tools/ollama/bin/ollama"
    if not tools["ollama"] and local_ollama.exists():
        tools["ollama"] = str(local_ollama)
    local_redis = ROOT / ".tools/redis-8.2.1/src/redis-server"
    if not tools["redis-server"] and local_redis.exists():
        tools["redis-server"] = str(local_redis)
    versions = {}
    for name in [
        "fastapi",
        "langgraph",
        "sqlite-vec",
        "lancedb",
        "sentence-transformers",
        "torch",
        "litellm",
        "crewai",
        "guardrails-ai",
        "celery",
        "redis",
        "qdrant-client",
        "deepeval",
        "ragas",
        "stripe",
        "supabase",
    ]:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    mem = Path("/sys/fs/cgroup/memory.max")
    limit = mem.read_text().strip() if mem.exists() else None
    return {
        "timestamp_utc": utcnow(),
        "os": platform.platform(),
        "architecture": platform.machine(),
        "python": sys.version,
        "cpu_quota": Path("/sys/fs/cgroup/cpu.max").read_text().strip()
        if Path("/sys/fs/cgroup/cpu.max").exists()
        else None,
        "memory_limit_bytes": int(limit) if limit and limit.isdigit() else None,
        "disk_free_bytes": shutil.disk_usage(ROOT).free,
        "executables": tools,
        "dependencies": versions,
        "credential_presence": {
            key: bool(os.environ.get(key))
            for key in [
                "OPENAI_API_KEY",
                "ANTHROPIC_API_KEY",
                "LANGSMITH_API_KEY",
                "STRIPE_SECRET_KEY",
                "SUPABASE_URL",
            ]
        },
        "model_lock_present": Path(
            os.environ.get("PAIS_MODEL_LOCK", ROOT / "models/local-models.lock.json")
        ).is_file(),
        "model_lock_explicitly_configured": bool(os.environ.get("PAIS_MODEL_LOCK")),
        "budget_microusd": 0,
        "warning": "Presence checks are capabilities, not acceptance evidence. Sandbox and services need active verification.",
    }
