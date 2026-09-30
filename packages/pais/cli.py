"""Documented command interface. Missing prerequisites are failures, never silent skips."""

from __future__ import annotations

import argparse
import importlib
import inspect
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from pais.evidence import ROOT, capture, doctor, manifest, write_report

PROJECT_MODULES = {
    "01": "pais.rag",
    "02": "pais.reliability",
    "03": "pais.research",
    "05": "pais.observability",
    "06": "pais.security",
    "07": "pais.retrieval",
    "09": "pais.training",
    "10": "pais.tenancy",
    "11": "pais.operations",
    "12": "pais.vectors",
    "13": "pais.memory",
    "14": "pais.inference",
    "15": "pais.workflows",
    "16": "pais.jobs",
    "17": "pais.benchmark",
}


def _offline_defaults() -> None:
    for key, value in {
        "LANGSMITH_TRACING": "false",
        "LANGCHAIN_TRACING_V2": "false",
        "DEEPEVAL_TELEMETRY_OPT_OUT": "YES",
        "RAGAS_DO_NOT_TRACK": "true",
        "LITELLM_LOCAL_MODEL_COST_MAP": "True",
        "HF_HUB_DISABLE_TELEMETRY": "1",
        "TOKENIZERS_PARALLELISM": "false",
        "OMP_NUM_THREADS": "2",
    }.items():
        os.environ.setdefault(key, value)


def _demo(project: str, profile: str, output: Path, backend: str) -> int:
    project = project.removeprefix("P").zfill(2)
    # Research and training keep independently locked environments. Preserve their
    # arguments and exit status when dispatching from the public CLI.
    isolated = {
        "03": "03-multi-agent-research",
        "09": "09-lora-training" if profile == "local" else None,
    }.get(project)
    if isolated:
        environment = ROOT / "projects" / isolated / ".venv"
        if Path(sys.prefix).absolute() != environment.absolute():
            python = environment / (
                "Scripts/python.exe" if sys.platform == "win32" else "bin/python"
            )
            if not python.is_file():
                raise RuntimeError(f"Run: uv sync --frozen --project projects/{isolated}")
            env = dict(os.environ)
            env["PYTHONPATH"] = os.pathsep.join(
                [str(ROOT / "packages"), str(ROOT), env.get("PYTHONPATH", "")]
            ).rstrip(os.pathsep)
            return subprocess.run(
                [
                    str(python),
                    "-m",
                    "pais",
                    "demo",
                    project,
                    "--profile",
                    profile,
                    "--backend",
                    backend,
                    "--output",
                    str(output.absolute()),
                ],
                cwd=ROOT,
                env=env,
                check=False,
            ).returncode
    if project == "04":
        from pais.evaluation import run_suite

        report, code = run_suite(profile, "release", output)
        print(json.dumps(report["summary"], indent=2))
        return code
    if project == "08":
        module_name = "services.api.demo"
    elif project == "18":
        module_name = "pais.upstream"
    else:
        module_name = PROJECT_MODULES.get(project)
    if not module_name:
        raise ValueError("Project must be 01 through 18")
    module = importlib.import_module(module_name)
    demo = getattr(module, "demo", None)
    if demo is None:
        raise RuntimeError(
            f"P{project} has no generic demo entrypoint; inspect its project README for the concrete verification command"
        )
    info = manifest(profile, sys.argv, {"project": project, "backend": backend})
    with tempfile.TemporaryDirectory(prefix=f"pais-p{project}-") as tmp:
        params = inspect.signature(demo).parameters
        candidates = {
            "profile": profile,
            "db_path": str(Path(tmp) / "demo.db"),
            "output_dir": str(output.parent / f"p{project}-outputs"),
            "backend": backend,
        }
        kwargs = {key: value for key, value in candidates.items() if key in params}
        result = demo(**kwargs)
    report = {"manifest": info, "project": project, "profile": profile, "result": result}
    blocked = isinstance(result, dict) and result.get("status") in {"blocked", "not-run", "not_run"}
    failed = isinstance(result, dict) and (
        result.get("status") == "failed" or result.get("passed") is False
    )
    if isinstance(result, dict) and isinstance(result.get("checks"), dict):
        failed = failed or any(value is not True for value in result["checks"].values())
    code = 2 if blocked else (1 if failed else 0)
    report["exit_status"] = code
    write_report(output, report)
    print(json.dumps(result, indent=2, default=str))
    print(f"Evidence: {output}")
    return code


def main(argv: list[str] | None = None) -> int:
    _offline_defaults()
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    parser = argparse.ArgumentParser(prog="pais", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("doctor", help="Inspect hardware/dependencies without exposing credentials")
    p.add_argument("--output", type=Path)
    p = sub.add_parser(
        "setup", help="Install locked dependencies; model downloads are a separate explicit action"
    )
    p.add_argument("--profile", choices=["fixture", "local"], default="fixture")
    p = sub.add_parser("dev", help="Run the API; launch the Next.js app in another terminal")
    p.add_argument("--profile", choices=["fixture", "local"], default="fixture")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p = sub.add_parser("demo", help="Run one project's repeatable demonstration")
    p.add_argument("project")
    p.add_argument(
        "--profile", choices=["fixture", "local", "connected", "deployment"], default="fixture"
    )
    p.add_argument("--backend", choices=["sqlite", "lancedb"], default="sqlite")
    p.add_argument("--output", type=Path)
    p = sub.add_parser(
        "eval", help="Run mandatory versioned evaluations; fixture cannot authorize deployment"
    )
    p.add_argument("--profile", choices=["fixture", "local"], default="fixture")
    p.add_argument("--suite", choices=["release", "development", "audit"], default="release")
    p.add_argument("--output", type=Path, default=ROOT / "artifacts/evals/release.json")
    p.add_argument("--degraded", action="store_true")
    p.add_argument("--limit", type=int, help="Diagnostic subset only; incomplete release fails")
    for name in ["smoke", "test", "security"]:
        sub.add_parser(name)
    p = sub.add_parser("evidence", help="Capture a command's real output and provenance")
    p.add_argument(
        "--profile", choices=["fixture", "local", "connected", "deployment"], required=True
    )
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("exec_command", nargs=argparse.REMAINDER)
    sub.add_parser("status", help="Read the 18-project implementation/verification ledger")
    args = parser.parse_args(argv)
    try:
        if args.command == "doctor":
            result = doctor()
            if args.output:
                write_report(args.output, result)
            print(json.dumps(result, indent=2))
            return 0
        if args.command == "setup":
            command = [
                "uv",
                "sync",
                "--frozen",
                "--group",
                "dev",
                "--extra",
                "vectors",
                "--extra",
                "router",
                "--extra",
                "workflows",
            ]
            if args.profile == "local":
                command += ["--extra", "local"]
            p = subprocess.run(command, cwd=ROOT, check=False)
            if p.returncode:
                return p.returncode
            projects = ["03-multi-agent-research", "04-eval-harness", "06-security-guardrails"]
            if args.profile == "local":
                projects.append("09-lora-training")
            for project in projects:
                result = subprocess.run(
                    ["uv", "sync", "--frozen", "--project", f"projects/{project}"],
                    cwd=ROOT,
                    check=False,
                )
                if result.returncode:
                    return result.returncode
            return 0
        if args.command == "dev":
            env = dict(os.environ, PAIS_PROFILE=args.profile)
            if args.profile == "fixture":
                env["PAIS_ALLOW_FIXTURE_AUTH"] = "1"
            else:
                env.setdefault("PAIS_GUARDRAILS_PYTHON", str(
                    ROOT / "projects/06-security-guardrails/.venv" /
                    ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
                ))
                env.setdefault("PAIS_MODEL_LOCK", str(ROOT / "models/local-models.lock.json"))
            return subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "services.api.app:app",
                    "--host",
                    args.host,
                    "--port",
                    str(args.port),
                ],
                cwd=ROOT,
                env=env,
                check=False,
            ).returncode
        if args.command == "demo":
            output = (
                args.output or ROOT / "artifacts" / f"p{args.project.zfill(2)}-{args.profile}.json"
            )
            return _demo(args.project, args.profile, output, args.backend)
        if args.command == "eval":
            from pais.evaluation import run_suite

            report, code = run_suite(
                args.profile, args.suite, args.output, args.degraded, args.limit
            )
            print(json.dumps(report["summary"], indent=2))
            print(f"Evidence: {args.output}")
            return code
        if args.command in {"smoke", "test", "security"}:
            if args.command == "security":
                paths = [
                    str(p.relative_to(ROOT)) for p in (ROOT / "tests").glob("test_security*.py")
                ]
                paths += [
                    str(p.relative_to(ROOT)) for p in (ROOT / "tests").glob("test_sandbox*.py")
                ]
            elif args.command == "smoke":
                paths = ["tests/test_contracts.py", "tests/test_evaluation.py"]
            else:
                paths = [
                    "tests",
                    "projects/13-agent-memory/test_comparison.py",
                    "projects/14-inference-server/test_supervisor.py",
                ]
            if not paths:
                raise RuntimeError("No required tests found")
            return subprocess.run(
                [sys.executable, "-m", "pytest", *paths, "-q"], cwd=ROOT, check=False
            ).returncode
        if args.command == "evidence":
            command = (
                args.exec_command[1:] if args.exec_command[:1] == ["--"] else args.exec_command
            )
            return capture(command, args.profile, args.output)
        if args.command == "status":
            ledger = ROOT / "docs/PROJECT_LEDGER.json"
            if not ledger.exists():
                raise RuntimeError("Project ledger is being assembled; see STATE.md")
            print(ledger.read_text())
            return 0
    except (ImportError, RuntimeError, ValueError, FileNotFoundError) as exc:
        print(
            json.dumps({"status": "blocked-or-failed", "error": f"{type(exc).__name__}: {exc}"}),
            file=sys.stderr,
        )
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
