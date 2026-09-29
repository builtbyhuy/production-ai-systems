"""Verify this trusted local application in an existing loopback-only network namespace.

This is an offline execution check, not a hostile-code sandbox. A managed loopback
proxy may still exist; every proxy environment variable is removed for the entire
Ollama/application subtree. On a normal networked host the command fails closed.
"""
from __future__ import annotations

import argparse
import json
import os
import resource
import socket
import subprocess
import sys
import time
from pathlib import Path

from pais.evidence import manifest, write_report
from pais.models import MissingPrerequisite
from pais.retrieval import demo

ROOT = Path(__file__).resolve().parents[2]


def network_boundary() -> dict:
    if not Path("/proc/net/dev").is_file():
        return {"verified": False, "reason": "Linux /proc network evidence unavailable"}
    interfaces = [line.split(":", 1)[0].strip() for line in Path("/proc/net/dev").read_text().splitlines()
                  if ":" in line]
    ipv4 = Path("/proc/net/route").read_text()
    ipv6 = Path("/proc/net/ipv6_route").read_text() if Path("/proc/net/ipv6_route").is_file() else ""
    routes4 = [line.split()[0] for line in ipv4.splitlines()[1:] if line.split()]
    routes6 = [line.split()[-1] for line in ipv6.splitlines() if line.split()]
    proxies = sorted(key for key in os.environ if "proxy" in key.casefold())
    negative_probes = []
    for family, address in [(socket.AF_INET, ("1.1.1.1", 443)),
                            (socket.AF_INET6, ("2606:4700:4700::1111", 443))]:
        try:
            with socket.socket(family, socket.SOCK_STREAM) as connection:
                connection.settimeout(1.0)
                connection.connect(address)
            negative_probes.append({"family": family.name, "blocked": False})
        except OSError as exc:
            negative_probes.append({"family": family.name, "blocked": True,
                                    "errno": exc.errno, "error_type": type(exc).__name__})
    verified = (interfaces == ["lo"] and not any(name != "lo" for name in routes4 + routes6)
                and all(probe["blocked"] for probe in negative_probes) and not proxies)
    return {
        "verified": verified, "network_namespace": os.readlink("/proc/self/ns/net"),
        "interfaces": interfaces, "ipv4_routes": ipv4, "ipv6_routes": ipv6,
        "proxy_environment_variables_present": proxies, "external_connection_probes": negative_probes,
        "scope": "Trusted application offline profile in existing loopback-only namespace",
        "limitation": "Managed loopback proxy endpoints may exist; this is not a hostile-code network sandbox.",
    }


def subtree_rss_kib(root_pid: int) -> int:
    """Aggregate resident memory; shared pages can be counted more than once."""
    parents = {}
    statuses = {}
    namespace_pids = {}
    own_proc_pid = int(os.readlink("/proc/self"))
    for path in Path("/proc").iterdir():
        if not path.name.isdigit():
            continue
        try:
            fields = (path / "stat").read_text().rsplit(")", 1)[1].split()
            parents[int(path.name)] = int(fields[1])
            statuses[int(path.name)] = path / "status"
            status = (path / "status").read_text().splitlines()
            nspid = next((line.split()[1:] for line in status if line.startswith("NSpid:")), [])
            namespace_pids[int(path.name)] = int(nspid[-1]) if nspid else int(path.name)
        except (OSError, ValueError, IndexError):
            continue
    # /proc can be mounted from the host PID namespace while Popen returns a PID in
    # this process's nested namespace. Match a direct child through PPid + NSpid.
    children = {pid for pid, parent in parents.items()
                if parent == own_proc_pid and namespace_pids[pid] == root_pid}
    if not children:
        return 0
    while True:
        new = {pid for pid, parent in parents.items() if parent in children} - children
        if not new:
            break
        children.update(new)
    rss = 0
    for pid in children:
        try:
            lines = statuses[pid].read_text().splitlines()
            rss += next((int(line.split()[1]) for line in lines if line.startswith("VmRSS:")), 0)
        except (KeyError, OSError, ValueError):
            continue
    return rss


def worker(backend: str, output: Path) -> int:
    proof = network_boundary()
    report = {"manifest": manifest("local", [sys.executable, *sys.argv], {"backend": backend}),
              "network_boundary": proof}
    if not proof["verified"]:
        report.update({"exit_status": 2, "status": "blocked",
                       "error": "No verified loopback-only namespace with proxy environment removed"})
        write_report(output, report)
        return 2
    started = time.perf_counter()
    try:
        result = demo(profile="local", backend=backend)
        result["offline_network_isolation_verified"] = True
        result["offline_verification_note"] = proof["scope"] + "; " + proof["limitation"]
        report["result"] = result
        status = 0 if all(result["checks"].values()) else 1
    except MissingPrerequisite as exc:
        status = 2
        report.update({"status": "blocked", "error": str(exc)})
    report.update({"exit_status": status, "elapsed_seconds": time.perf_counter() - started,
                   "application_peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                   "model_directory_disk_bytes": sum(path.stat().st_size for path in (ROOT / "models").rglob("*")
                                                     if path.is_file())})
    report["network_boundary_after"] = network_boundary()
    if "result" in report:
        report["result"]["offline_network_isolation_verified"] = bool(
            proof["verified"] and report["network_boundary_after"]["verified"])
    if not report["network_boundary_after"]["verified"]:
        status = report["exit_status"] = 1
    write_report(output, report)
    print(json.dumps({"report": str(output), "exit_status": status}), flush=True)
    return status


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=["sqlite", "lancedb"], default="sqlite")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        return worker(args.backend, args.output)
    removed = sorted(key for key in os.environ if "proxy" in key.casefold())
    child_env = {key: value for key, value in os.environ.items() if "proxy" not in key.casefold()}
    child_env.update({"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
                      "HF_HUB_DISABLE_TELEMETRY": "1", "OLLAMA_NO_CLOUD": "1",
                      "LANGSMITH_TRACING": "false", "LANGCHAIN_TRACING_V2": "false",
                      "OTEL_SDK_DISABLED": "true", "DO_NOT_TRACK": "1"})
    command = [sys.executable, str(ROOT / "scripts/with_local_models.py"), "--",
               sys.executable, str(Path(__file__).resolve()), "--worker", "--backend", args.backend,
               "--output", str(args.output.resolve())]
    log = args.output.with_suffix(".log")
    log.parent.mkdir(parents=True, exist_ok=True)
    peak = 0
    with log.open("w") as handle:
        process = subprocess.Popen(command, cwd=ROOT, env=child_env, stdout=handle,
                                   stderr=subprocess.STDOUT, close_fds=True)
        while process.poll() is None:
            peak = max(peak, subtree_rss_kib(process.pid))
            time.sleep(0.1)
        status = process.returncode
    if args.output.is_file():
        report = json.loads(args.output.read_text())
    else:
        report = {"manifest": manifest("local", [sys.executable, *sys.argv]),
                  "exit_status": status, "status": "blocked",
                  "error": "Local runner did not produce its worker report; inspect the log"}
    report.update({"launch_command": command, "proxy_variables_removed": removed,
                   "native_stack_peak_rss_kib": peak,
                   "rss_measurement": "Sampled sum of Ollama/application subprocess RSS; shared pages may count twice.",
                   "output_log": str(log)})
    write_report(args.output, report)
    print(json.dumps({"report": str(args.output), "exit_status": status, "native_stack_peak_rss_kib": peak}))
    return status


if __name__ == "__main__":
    raise SystemExit(main())
