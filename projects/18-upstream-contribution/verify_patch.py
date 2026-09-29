"""Run an unchanged upstream baseline and the same regression checks with the patch.

Only the pinned, MIT-licensed LangGraph package snapshot is executed. No third-party
submission, network fetch, account operation or public write occurs in this command.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from pais.evidence import manifest, sha256, write_report

PROJECT = Path(__file__).resolve().parent
UPSTREAM_COMMIT = "07b33185eab893be2ed031eedae52f09314bf77c"


def run(output: Path) -> tuple[dict, int]:
    sources = json.loads((PROJECT / "vendor-manifest.json").read_text())
    for relative, digest in sources["files"].items():
        if sha256(PROJECT / "vendor" / relative) != digest:
            raise RuntimeError(f"Pinned upstream source changed: {relative}")
    evidence = {
        "manifest": manifest(
            "local",
            [sys.executable, *sys.argv],
            {
                "upstream_commit": UPSTREAM_COMMIT,
                "upstream_package": "langgraph-checkpoint-sqlite",
                "upstream_snapshot": sources,
                "patch_sha256": sha256(PROJECT / "upstream.patch"),
            },
        ),
        "publication": {
            "patch_prepared": True,
            "pr_submitted": False,
            "maintainer_response": None,
            "merged": False,
        },
        "runs": {},
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="pais-upstream-") as temporary:
        for variant in ["baseline", "patched"]:
            root = Path(temporary) / variant
            shutil.copytree(PROJECT / "vendor", root)
            regression = root / "libs/checkpoint-sqlite/tests/test_transaction_atomicity.py"
            if variant == "patched":
                applied = subprocess.run(
                    ["git", "apply", "--check", str(PROJECT / "upstream.patch")],
                    cwd=root,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                if applied.returncode:
                    raise RuntimeError(
                        "Patch no longer applies to pinned source: " + applied.stderr
                    )
                subprocess.run(
                    ["git", "apply", str(PROJECT / "upstream.patch")], cwd=root, check=True
                )
            else:
                shutil.copyfile(PROJECT / "regression_test.py", regression)
            if regression.read_bytes() != (PROJECT / "regression_test.py").read_bytes():
                raise RuntimeError("Baseline and patched regression tests must be byte-identical")
            environment = dict(
                os.environ,
                PYTHONPATH=str(root / "libs/checkpoint-sqlite"),
                PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",
                LANGSMITH_TRACING="false",
            )
            tests = [str(regression)]
            if variant == "patched":
                tests += [str(root / "libs/checkpoint-sqlite/tests/test_sqlite.py")]
            command = [
                sys.executable,
                "-m",
                "pytest",
                "-p",
                "pytest_asyncio.plugin",
                "-o",
                "asyncio_mode=auto",
                "-c",
                os.devnull,
                "--import-mode=importlib",
                "-q",
                *tests,
            ]
            started = time.perf_counter()
            process = subprocess.run(
                command,
                cwd=root,
                env=environment,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=120,
                check=False,
            )
            log = output.parent / f"upstream-{variant}.log"
            log.write_text(process.stdout)
            evidence["runs"][variant] = {
                "command": command,
                "exit_status": process.returncode,
                "elapsed_seconds": time.perf_counter() - started,
                "output_log": str(log),
                "output_sha256": sha256(log),
                "output_tail": process.stdout[-12000:],
            }
    passed = (
        evidence["runs"]["baseline"]["exit_status"] == 1
        and evidence["runs"]["patched"]["exit_status"] == 0
    )
    code = 0 if passed else 1
    evidence.update(
        passed=passed,
        exit_status=code,
        scope="Four focused transaction tests plus upstream synchronous SqliteSaver test module",
        limits=[
            "Full upstream make format/lint/test and asynchronous saver paths are not verified",
            "Maintainer-approved assigned issue required before an external PR",
        ],
    )
    write_report(output, evidence)
    return evidence, code


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("artifacts/p18-upstream.json"))
    args = parser.parse_args()
    try:
        report, code = run(args.output.resolve())
        print(
            json.dumps(
                {
                    "passed": report["passed"],
                    "runs": {
                        name: {"exit_status": row["exit_status"], "seconds": row["elapsed_seconds"]}
                        for name, row in report["runs"].items()
                    },
                    "output": str(args.output),
                },
                indent=2,
            )
        )
        return code
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print(json.dumps({"status": "blocked", "reason": str(exc)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
