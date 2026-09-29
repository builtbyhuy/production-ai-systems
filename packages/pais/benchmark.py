"""P17: versioned Python maintenance tasks with fail-closed submission execution.

Only the checksum-pinned, repository-authored corpus can use the trusted reference
validator. Candidate submissions always go through P06; there is no host fallback.
Expected outputs remain in the scoring controller rather than the candidate process.
"""

from __future__ import annotations

import argparse
import ast
import copy
import hashlib
import json
import math
import platform
import re
import shutil
import subprocess
import sys
import time
import unicodedata
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pais.sandbox import SandboxLimits, SandboxRunner, SandboxUnavailable

ROOT = Path(__file__).resolve().parents[2]
DATASET_ID = "pais-python-maintenance-v1"
DATASET_PATH = ROOT / "projects/17-domain-benchmark/data/tasks-v1.jsonl"
DATASET_SHA256 = "c76215ca42e8d33254ceff5146a2f1c92833c9156ccbe5ec9b57b63ebf25a8bd"
MAX_SOURCE_BYTES = 32_768
MAX_SUBMISSION_BYTES = 4_000_000
MAX_AST_NODES = 10_000


class BenchmarkValidationError(ValueError):
    """A dataset, candidate or recorded result violates the benchmark contract."""


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _json(value: Any) -> str:
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )


def text_fingerprint(value: str) -> str:
    normalized = " ".join(unicodedata.normalize("NFKC", value).casefold().split())
    return _sha(normalized.encode())


def load_tasks() -> list[dict]:
    payload = DATASET_PATH.read_bytes()
    if _sha(payload) != DATASET_SHA256:
        raise BenchmarkValidationError(
            "Built-in corpus checksum differs; review the version and hash before executing trusted references"
        )
    tasks = [json.loads(line) for line in payload.splitlines() if line.strip()]
    validate_dataset(tasks)
    return tasks


def validate_dataset(tasks: list[dict]) -> dict:
    if not isinstance(tasks, list) or len(tasks) < 100:
        raise BenchmarkValidationError("The release corpus needs at least 100 tasks")
    ids, sources, references, splits = set(), {}, set(), Counter()
    categories, difficulties, cases = Counter(), Counter(), 0
    for task in tasks:
        required = {
            "id",
            "version",
            "source_id",
            "source_revision",
            "license",
            "category",
            "difficulty",
            "split",
            "prompt",
            "starter",
            "reference",
            "cases",
            "entrypoint",
            "provenance",
        }
        if not required <= task.keys():
            raise BenchmarkValidationError("Task metadata is incomplete")
        if task["id"] in ids or not re.fullmatch(r"ppm-\d{3}-[a-z0-9-]+", task["id"]):
            raise BenchmarkValidationError("Task ids must be unique and versionable")
        ids.add(task["id"])
        if task["license"] != "MIT" or not task["source_revision"] or not task["provenance"]:
            raise BenchmarkValidationError(
                "The authored corpus requires its license and provenance"
            )
        if task["difficulty"] not in {"easy", "medium", "hard"} or task["split"] not in {
            "train",
            "dev",
            "test",
        }:
            raise BenchmarkValidationError("Unknown task difficulty or split")
        existing = sources.setdefault(task["source_id"], task["split"])
        if existing != task["split"]:
            raise BenchmarkValidationError("A source group crosses splits")
        if task["entrypoint"] != "solve" or len(task["prompt"]) < 60:
            raise BenchmarkValidationError("Every task needs a meaningful solve contract")
        for field in ("starter", "reference"):
            _validate_source(task[field])
        tree = ast.dump(ast.parse(task["reference"]), include_attributes=False)
        if tree in references:
            raise BenchmarkValidationError("Reference programs must be structurally distinct")
        references.add(tree)
        if task["starter"] == task["reference"] or len(task["cases"]) < 3:
            raise BenchmarkValidationError("Every seeded regression needs at least three checks")
        serialized_cases = set()
        for case in task["cases"]:
            if set(case) not in ({"args", "expected"}, {"args", "raises"}):
                raise BenchmarkValidationError("Invalid check schema")
            if not isinstance(case["args"], list) or (
                "raises" in case
                and case["raises"]
                not in {"ValueError", "TypeError", "KeyError", "UnicodeDecodeError"}
            ):
                raise BenchmarkValidationError("Invalid check arguments or expected exception")
            serialized_cases.add(_json(case))
        if len(serialized_cases) != len(task["cases"]):
            raise BenchmarkValidationError("Duplicate checks do not add coverage")
        cases += len(task["cases"])
        categories[task["category"]] += 1
        difficulties[task["difficulty"]] += 1
        splits[task["split"]] += 1
    return {
        "dataset_id": DATASET_ID,
        "dataset_sha256": DATASET_SHA256,
        "tasks": len(tasks),
        "executable_checks": cases,
        "distinct_reference_asts": len(references),
        "source_groups": len(sources),
        "categories": dict(categories),
        "difficulties": dict(difficulties),
        "splits": dict(splits),
    }


def _validate_source(source: Any) -> None:
    if (
        not isinstance(source, str)
        or not 0 < len(source.encode()) <= MAX_SOURCE_BYTES
        or "\0" in source
    ):
        raise BenchmarkValidationError("Python source must contain 1..32768 UTF-8 bytes and no NUL")
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError, MemoryError) as exc:
        raise BenchmarkValidationError("Invalid or excessively nested Python syntax") from exc
    if sum(1 for _ in ast.walk(tree)) > MAX_AST_NODES:
        raise BenchmarkValidationError("Source exceeds the AST size limit")
    definitions = [
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "solve"
    ]
    if len(definitions) != 1:
        raise BenchmarkValidationError(
            "Submission must define one synchronous top-level solve function"
        )


def contamination_fingerprints() -> set[str]:
    """Fingerprints for P09 exclusion. This catches exact normalized overlap, not paraphrases."""
    return {
        text_fingerprint(task[field])
        for task in load_tasks()
        for field in ("prompt", "starter", "reference")
    }


def _equivalent(actual: Any, expected: Any) -> bool:
    if type(expected) is bool or expected is None:
        return actual is expected
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        if type(actual) is int and type(expected) is int:
            return actual == expected
        if type(actual) not in {int, float}:
            return False
        try:
            finite = math.isfinite(actual)
        except OverflowError:
            return False
        return finite and math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-9)
    if isinstance(expected, list):
        return (
            isinstance(actual, list)
            and len(actual) == len(expected)
            and all(_equivalent(a, b) for a, b in zip(actual, expected, strict=True))
        )
    if isinstance(expected, dict):
        return (
            isinstance(actual, dict)
            and actual.keys() == expected.keys()
            and all(_equivalent(actual[k], v) for k, v in expected.items())
        )
    return type(actual) is type(expected) and actual == expected


def _outcome_matches(outcome: dict, case: dict) -> bool:
    if "raises" in case:
        classes = outcome.get("classes")
        return (
            set(outcome) == {"kind", "classes"}
            and outcome.get("kind") == "exception"
            and isinstance(classes, list)
            and 1 <= len(classes) <= 32
            and all(isinstance(item, str) for item in classes)
            and case["raises"] in classes
        )
    return (
        set(outcome) == {"kind", "value"}
        and outcome.get("kind") == "return"
        and _equivalent(outcome.get("value"), case["expected"])
    )


def validate_trusted_references() -> dict:
    """Execute only checksum-pinned code written in this repository.

    This is corpus authoring QA. It is never a model/candidate benchmark run, and
    its results cannot be accepted by the leaderboard generator.
    """
    tasks = load_tasks()
    failures, references_passed, defects_reproduced = [], 0, 0
    started = time.perf_counter()
    for task in tasks:
        field_results = {}
        for field in ("reference", "starter"):
            namespace: dict = {}
            exec(  # noqa: S102 -- Only checksum-pinned, repository-authored corpus QA.
                compile(task[field], f"<trusted-authored-{task['id']}-{field}>", "exec"), namespace
            )
            fn = namespace["solve"]
            passed = []
            for case in task["cases"]:
                try:
                    value = fn(*copy.deepcopy(case["args"]))
                except Exception as exc:  # noqa: BLE001 -- Record deliberately raised corpus errors.
                    outcome = {
                        "kind": "exception",
                        "classes": [cls.__name__ for cls in type(exc).__mro__],
                    }
                else:
                    try:
                        outcome = {"kind": "return", "value": json.loads(_json(value))}
                    except (ValueError, TypeError):
                        outcome = {"kind": "invalid_return"}
                passed.append(_outcome_matches(outcome, case))
            field_results[field] = passed
        references_passed += all(field_results["reference"])
        defects_reproduced += not all(field_results["starter"])
        if not all(field_results["reference"]) or all(field_results["starter"]):
            failures.append({"task_id": task["id"], "checks": field_results})
    result = {
        **validate_dataset(tasks),
        "verification_kind": "trusted-corpus-authoring-QA",
        "reference_contracts_passed": references_passed,
        "seeded_defects_reproduced": defects_reproduced,
        "failures": failures,
        "duration_seconds": time.perf_counter() - started,
        "untrusted_submissions_executed": 0,
        "leaderboard_eligible": False,
    }
    if failures:
        raise BenchmarkValidationError(_json(result))
    return result


def validate_submission(submission: dict, tasks: list[dict] | None = None) -> dict:
    tasks = tasks or load_tasks()
    if not isinstance(submission, dict) or set(submission) != {
        "schema_version",
        "dataset_id",
        "dataset_sha256",
        "metadata",
        "solutions",
    }:
        raise BenchmarkValidationError("Submission must follow the exact v1 JSON schema")
    if len(_json(submission).encode()) > MAX_SUBMISSION_BYTES:
        raise BenchmarkValidationError("Submission exceeds the 4 MB limit")
    if (
        submission["schema_version"] != 1
        or submission["dataset_id"] != DATASET_ID
        or submission["dataset_sha256"] != DATASET_SHA256
    ):
        raise BenchmarkValidationError("Submission references the wrong dataset release")
    metadata = submission["metadata"]
    required = {"name", "origin", "version", "configuration", "model", "generation_cost_usd"}
    if (
        not isinstance(metadata, dict)
        or set(metadata) != required
        or metadata["origin"] not in {"hand-authored-rule-engine", "model", "human"}
    ):
        raise BenchmarkValidationError("Generator metadata is missing or invalid")
    if (
        not isinstance(metadata["name"], str)
        or not 1 <= len(metadata["name"]) <= 100
        or not isinstance(metadata["version"], str)
        or not metadata["version"]
    ):
        raise BenchmarkValidationError("Generator name and immutable version are required")
    if not isinstance(metadata["configuration"], dict):
        raise BenchmarkValidationError("Generator configuration must be an object")
    if metadata["origin"] == "model" and (
        not isinstance(metadata["model"], dict)
        or not {"id", "revision", "provider"} <= metadata["model"].keys()
    ):
        raise BenchmarkValidationError("A model generator needs its id, revision and provider")
    cost = metadata["generation_cost_usd"]
    if cost is not None and (type(cost) not in {int, float} or not math.isfinite(cost) or cost < 0):
        raise BenchmarkValidationError("Generation cost must be nonnegative or explicitly unknown")
    known_ids = {task["id"] for task in tasks}
    solutions = submission["solutions"]
    if not isinstance(solutions, dict) or not solutions or not solutions.keys() <= known_ids:
        raise BenchmarkValidationError("Solutions must map known task ids to Python modules")
    for source in solutions.values():
        _validate_source(source)
    return {
        "valid": True,
        "solutions": len(solutions),
        "missing_tasks": len(known_ids - solutions.keys()),
        "submission_sha256": _sha(_json(submission).encode()),
    }


# Rules were authored against train-split starter idioms. This deliberately weak
# baseline reads no reference solutions, expected outputs, or task-id answer table.
REPAIR_RULES = (
    ("return sorted(set(values))", "return list(dict.fromkeys(values))"),
    ("range(0, len(values)-size+1, size)", "range(0, len(values), size)"),
    ("text.split('=')", "text.split('=', 1)"),
    ("text.lstrip(prefix)", "text.removeprefix(prefix)"),
    ("left.strip().lower()", "left.strip().casefold()"),
    ("name.rstrip(suffix)", "name.removesuffix(suffix)"),
    ("text.split(' ')", "text.split()"),
    ("max(high, min(low, value))", "min(high, max(low, value))"),
    ("Decimal(float(amount))", "Decimal(amount)"),
    ("isinstance(value, int) and 0 <= value <= 100", "type(value) is int and 0 <= value <= 100"),
    ("key==name", "key.lower()==name.lower()"),
    ("parts[0]=='Bearer'", "parts[0].lower()=='bearer'"),
)


def make_baseline(name: str = "no-op") -> dict:
    if name not in {"no-op", "mechanical-repair"}:
        raise BenchmarkValidationError(
            "Available real baseline implementations: no-op, mechanical-repair"
        )
    solutions = {}
    for task in load_tasks():
        source = task["starter"]
        if name == "mechanical-repair":
            for broken, repaired in REPAIR_RULES:
                source = source.replace(broken, repaired)
        solutions[task["id"]] = source
    return {
        "schema_version": 1,
        "dataset_id": DATASET_ID,
        "dataset_sha256": DATASET_SHA256,
        "metadata": {
            "name": name,
            "origin": "hand-authored-rule-engine",
            "version": "1.0.0",
            "configuration": {
                "rules": len(REPAIR_RULES) if name == "mechanical-repair" else 0,
                "rule_source_split": "train",
                "model_inference": False,
            },
            "model": None,
            "generation_cost_usd": 0,
        },
        "solutions": solutions,
    }


def _candidate_harness(source: str) -> str:
    # Candidate sees only case arguments, never scorer expected outputs. A fresh
    # sandbox is used per task. Its entire stdout must be one bounded JSON array.
    return (
        source
        + "\n"
        + """
import json as _pais_json
import sys as _pais_sys
_pais_inputs = _pais_json.load(_pais_sys.stdin)
_pais_outcomes = []
for _pais_args in _pais_inputs:
    try:
        _pais_value = solve(*_pais_args)
        _pais_outcomes.append({"kind":"return","value":_pais_value})
    except Exception as _pais_exc:
        _pais_outcomes.append({"kind":"exception","classes":[c.__name__ for c in type(_pais_exc).__mro__]})
print(_pais_json.dumps(_pais_outcomes,allow_nan=False,separators=(",",":")))
"""
    )


def _git_metadata() -> dict:
    git = shutil.which("git")
    if git is None:
        return {"commit": None, "dirty": None}
    try:
        commit = subprocess.run(
            [git, "rev-parse", "HEAD"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=3,
            check=False,
        )
        dirty = subprocess.run(
            [git, "status", "--porcelain"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=3,
            check=False,
        )
        return {
            "commit": commit.stdout.strip() if commit.returncode == 0 else None,
            "dirty": bool(dirty.stdout.strip()) if dirty.returncode == 0 else None,
        }
    except (OSError, subprocess.TimeoutExpired):
        return {"commit": None, "dirty": None}


def run_benchmark(
    submission: dict,
    sandbox: SandboxRunner,
    output_dir: str | Path,
    split: str = "test",
    limits: SandboxLimits | None = None,
) -> dict:
    if not isinstance(sandbox, SandboxRunner):
        raise SandboxUnavailable(
            "Scoring requires the established P06 SandboxRunner, never a host executor"
        )
    tasks = load_tasks()
    validated = validate_submission(submission, tasks)
    if split not in {"train", "dev", "test", "all"}:
        raise BenchmarkValidationError("Unknown scoring split")
    out = Path(output_dir)
    if out.exists() and any(out.iterdir()):
        raise BenchmarkValidationError(
            "Use a fresh output directory; scored evidence must not be overwritten"
        )
    preflight = sandbox.preflight()  # Deny before directory writes or code execution.
    selected = [task for task in tasks if split == "all" or task["split"] == split]
    results, start = [], time.perf_counter()
    for task in selected:
        source = submission["solutions"].get(task["id"])
        result = {
            "task_id": task["id"],
            "category": task["category"],
            "difficulty": task["difficulty"],
            "checks": len(task["cases"]),
            "passed": False,
            "case_passes": [False] * len(task["cases"]),
            "source_sha256": _sha(source.encode()) if source else None,
        }
        if source is None:
            result["failure"] = "missing_solution"
        else:
            inputs = json.dumps(
                [case["args"] for case in task["cases"]],
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            )
            execution = sandbox.run_python(_candidate_harness(source), stdin=inputs, limits=limits)
            result["execution"] = asdict(execution)
            if execution.timed_out or execution.truncated or execution.exit_code != 0:
                result["failure"] = (
                    "timeout"
                    if execution.timed_out
                    else "output_limit"
                    if execution.truncated
                    else "execution_error"
                )
            else:
                try:
                    outcomes = json.loads(execution.stdout)
                    if (
                        not isinstance(outcomes, list)
                        or len(outcomes) != len(task["cases"])
                        or not all(isinstance(x, dict) for x in outcomes)
                    ):
                        raise ValueError("invalid outcome schema")
                    result["case_passes"] = [
                        _outcome_matches(outcome, case)
                        for outcome, case in zip(outcomes, task["cases"], strict=True)
                    ]
                    result["passed"] = all(result["case_passes"])
                    result["failure"] = None if result["passed"] else "contract_failure"
                except (ValueError, TypeError, RecursionError):
                    result["failure"] = "invalid_stdout_protocol"
        results.append(result)
    report = {
        "schema_version": 1,
        "dataset_id": DATASET_ID,
        "dataset_sha256": DATASET_SHA256,
        "verification_kind": "sandbox-scored-submission",
        "status": "executed",
        "profile": "local",
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "command": sys.argv,
        "git": _git_metadata(),
        "python": sys.version,
        "hardware": platform.platform(),
        "sandbox": preflight,
        "limits": asdict(limits or sandbox.limits),
        "split": split,
        "submission_sha256": validated["submission_sha256"],
        "generator": submission["metadata"],
        "generation_cost_basis": "self-reported submission metadata",
        "scoring_infrastructure_cost_usd": None,
        "duration_seconds": time.perf_counter() - start,
        "results": results,
        "passed_tasks": sum(row["passed"] for row in results),
        "total_tasks": len(results),
        "exit_status": 0,
    }
    report["raw_results_sha256"] = _sha(_json(results).encode())
    out.mkdir(parents=True, exist_ok=True)
    (out / "submission.json").write_text(json.dumps(submission, indent=2, ensure_ascii=False))
    (out / "raw-results.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
    return report


def _wilson(successes: int, total: int) -> list[float]:
    z = 1.959963984540054
    p = successes / total
    denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return [max(0, center - half), min(1, center + half)]


def build_leaderboard(raw_files: list[str | Path], output_path: str | Path | None = None) -> dict:
    rows = []
    known = {task["id"]: task for task in load_tasks()}
    for path in raw_files:
        raw_bytes = Path(path).read_bytes()
        report = json.loads(raw_bytes)
        if (
            report.get("verification_kind") != "sandbox-scored-submission"
            or report.get("status") != "executed"
        ):
            raise BenchmarkValidationError(
                "Only actual sandbox-scored submissions enter the leaderboard"
            )
        if (
            report.get("dataset_sha256") != DATASET_SHA256
            or report.get("sandbox", {}).get("boundary") != "rootless-docker-cgroupv2"
        ):
            raise BenchmarkValidationError("Dataset or sandbox provenance mismatch")
        results = report["results"]
        expected = {
            task_id
            for task_id, task in known.items()
            if report["split"] == "all" or task["split"] == report["split"]
        }
        if len(results) != len(expected) or {row["task_id"] for row in results} != expected:
            raise BenchmarkValidationError("Raw results must cover exactly the declared split")
        for result in results:
            task = known[result["task_id"]]
            if len(result["case_passes"]) != len(task["cases"]) or any(
                type(p) is not bool for p in result["case_passes"]
            ):
                raise BenchmarkValidationError("Invalid raw case outcomes")
            if result["passed"] != all(result["case_passes"]):
                raise BenchmarkValidationError(
                    "Task summary differs from executable check outcomes"
                )
        passed, total = sum(row["passed"] for row in results), len(results)
        if (
            passed != report["passed_tasks"]
            or total != report["total_tasks"]
            or _sha(_json(results).encode()) != report["raw_results_sha256"]
        ):
            raise BenchmarkValidationError("Score or raw results digest was altered")
        slices = defaultdict(lambda: [0, 0])
        for result in results:
            for dimension in ("category", "difficulty"):
                key = f"{dimension}:{known[result['task_id']][dimension]}"
                slices[key][0] += result["passed"]
                slices[key][1] += 1
        rows.append(
            {
                "name": report["generator"]["name"],
                "generator": report["generator"],
                "split": report["split"],
                "passed": passed,
                "total": total,
                "pass_at_1": passed / total,
                "wilson_95_task_interval": _wilson(passed, total),
                "slices": dict(slices),
                "duration_seconds": report["duration_seconds"],
                "hardware": report["hardware"],
                "raw_file": str(path),
                "raw_file_sha256": _sha(raw_bytes),
                "submission_sha256": report["submission_sha256"],
            }
        )
    rows.sort(key=lambda row: (row["split"], -row["pass_at_1"], row["name"]))
    leaderboard = {
        "dataset_id": DATASET_ID,
        "dataset_sha256": DATASET_SHA256,
        "rows": rows,
        "uncertainty_note": "Wilson intervals describe this task sample, not model stochasticity. One completion per task; repeated-seed model uncertainty is unmeasured.",
        "contamination_note": "All v1 tasks and checks are public and original synthetic cases. Prior exposure, template familiarity, and benchmark-specific fitting cannot be excluded. No hidden-test claim.",
    }
    if output_path is not None:
        Path(output_path).write_text(json.dumps(leaderboard, indent=2, ensure_ascii=False))
    return leaderboard


def demo(profile: str = "fixture", output_dir: str | Path | None = None) -> dict:
    if profile != "fixture":
        raise SandboxUnavailable(
            "Use the explicit score command with --sandbox-image and --enable-sandbox on a verified rootless Docker host; this environment has no verified boundary"
        )
    validation = validate_trusted_references()
    rejected = False
    invalid = make_baseline()
    invalid["solutions"][next(iter(invalid["solutions"]))] = "def broken(:"
    try:
        validate_submission(invalid)
    except BenchmarkValidationError:
        rejected = True
    denied = False
    try:
        SandboxRunner().run_python("raise RuntimeError('must never execute on host')")
    except SandboxUnavailable:
        denied = True
    result = {
        "project": "P17",
        "profile": "fixture",
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "command": sys.argv,
        "git": _git_metadata(),
        "python": sys.version,
        "source_sha256": _sha(Path(__file__).read_bytes()),
        "exit_status": 0,
        "corpus": validation,
        "malformed_submission_rejected": rejected,
        "disabled_sandbox_rejected": denied,
        "scored_baselines": [],
        "leaderboard_rows": 0,
        "acceptance": "incomplete: actual sandbox scoring and reproduction await a verified rootless Docker host",
    }
    if output_dir is not None:
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / "fixture-validation.json").write_text(
            json.dumps(result, indent=2, ensure_ascii=False)
        )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    fixture = sub.add_parser("fixture")
    fixture.add_argument("--output", default="artifacts/p17-fixture")
    baseline = sub.add_parser("baseline")
    baseline.add_argument("name", choices=["no-op", "mechanical-repair"])
    baseline.add_argument("--output", required=True)
    score = sub.add_parser("score")
    score.add_argument("submission")
    score.add_argument("--output", required=True)
    score.add_argument("--split", choices=["train", "dev", "test", "all"], default="test")
    score.add_argument("--sandbox-image", required=True)
    score.add_argument("--enable-sandbox", action="store_true")
    leaderboard = sub.add_parser("leaderboard")
    leaderboard.add_argument("raw", nargs="+")
    leaderboard.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        if args.command == "fixture":
            result = demo(output_dir=args.output)
        elif args.command == "baseline":
            result = make_baseline(args.name)
            validate_submission(result)
            Path(args.output).parent.mkdir(parents=True, exist_ok=True)
            Path(args.output).write_text(json.dumps(result, indent=2, ensure_ascii=False))
            result = {
                "baseline_written": args.output,
                "solutions": len(result["solutions"]),
                "scored": False,
            }
        elif args.command == "score":
            if Path(args.submission).stat().st_size > MAX_SUBMISSION_BYTES:
                raise BenchmarkValidationError("Submission exceeds file-size limit")
            submission = json.loads(Path(args.submission).read_text())
            result = run_benchmark(
                submission,
                SandboxRunner(image=args.sandbox_image, enabled=args.enable_sandbox),
                args.output,
                split=args.split,
            )
            result = {key: value for key, value in result.items() if key != "results"}
        else:
            result = build_leaderboard(args.raw, args.output)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except (BenchmarkValidationError, SandboxUnavailable, FileNotFoundError) as exc:
        print(json.dumps({"error": str(exc), "exit_status": 2}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
