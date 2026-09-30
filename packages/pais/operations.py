"""Fail-closed operational controls shared by APIs, workers, and release tooling.

The flag database is the authority. There is deliberately no process-local cache: a worker
must recheck in its action-admission transaction. Disabling a flag does not undo work already
admitted before the disable transaction committed.
"""

from __future__ import annotations

import argparse
import builtins
import hashlib
import json
import math
import re
import sqlite3
import subprocess
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from pais.contracts import Principal, new_id, utcnow
from pais.db import Database

CAPABILITIES = ("agent.execute",)


class CapabilityDisabled(PermissionError):
    """The authoritative capability state denies this new action."""


class CapabilityStateUnavailable(RuntimeError):
    """The authoritative state could not be checked; callers must deny admission."""


class FlagConflict(ValueError):
    """Another administrator changed the flag; reread before deciding again."""


class ReleaseRejected(ValueError):
    """An artifact lacks complete release evidence or an immutable identity."""


class CapabilityFlags:
    def __init__(self, db: Database | str | Path):
        self.db = db if isinstance(db, Database) else Database(db)
        self.db.initialize("""
            CREATE TABLE IF NOT EXISTS ops_capability_flags (
              tenant_id TEXT NOT NULL, capability TEXT NOT NULL,
              enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
              version INTEGER NOT NULL CHECK(version > 0),
              updated_at TEXT NOT NULL, updated_by TEXT NOT NULL, reason TEXT NOT NULL,
              PRIMARY KEY(tenant_id, capability)
            );
            CREATE TABLE IF NOT EXISTS ops_emergency_flags (
              capability TEXT PRIMARY KEY, disabled INTEGER NOT NULL CHECK(disabled IN (0,1)),
              version INTEGER NOT NULL CHECK(version > 0),
              updated_at TEXT NOT NULL, updated_by TEXT NOT NULL, reason TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS ops_flag_audit (
              event_id TEXT PRIMARY KEY, tenant_id TEXT, capability TEXT NOT NULL,
              kind TEXT NOT NULL, value INTEGER NOT NULL, version INTEGER NOT NULL,
              actor TEXT NOT NULL, reason TEXT NOT NULL, timestamp TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS ops_control_bootstrap (
              key TEXT PRIMARY KEY, created_at TEXT NOT NULL
            );
        """)
        # The global latch only removes permission; a tenant still must explicitly opt in.
        # INSERT OR IGNORE preserves an emergency stop across process restarts.
        with self.db.transaction() as conn:
            initialized = conn.execute(
                "SELECT 1 FROM ops_control_bootstrap WHERE key='emergency-v1'"
            ).fetchone()
            if initialized is None:
                for capability in CAPABILITIES:
                    conn.execute(
                        """INSERT OR IGNORE INTO ops_emergency_flags
                           VALUES (?,0,1,?,'bootstrap','tenant flags remain disabled by default')""",
                        (capability, utcnow()),
                    )
                conn.execute(
                    "INSERT INTO ops_control_bootstrap VALUES ('emergency-v1',?)", (utcnow(),)
                )

    @staticmethod
    def _check_capability(capability: str) -> None:
        if capability not in CAPABILITIES:
            raise ValueError(f"Unknown capability: {capability}")

    @staticmethod
    def _value(value: bool) -> int:
        if type(value) is not bool:
            raise ValueError("Flag values must be boolean")
        return int(value)

    @staticmethod
    def _reason(reason: str) -> str:
        if len(reason) > 500:
            raise ValueError("Reason must be at most 500 characters")
        return reason

    def _get_tx(self, conn: sqlite3.Connection, principal: Principal, capability: str) -> dict:
        self._check_capability(capability)
        row = conn.execute(
            "SELECT * FROM ops_capability_flags WHERE tenant_id=? AND capability=?",
            (principal.tenant_id, capability),
        ).fetchone()
        latch = conn.execute(
            "SELECT * FROM ops_emergency_flags WHERE capability=?", (capability,)
        ).fetchone()
        if latch is None or latch["disabled"] not in (0, 1):
            raise CapabilityStateUnavailable("Emergency control state is unavailable")
        if row is None:
            state = {
                "tenant_id": principal.tenant_id,
                "capability": capability,
                "enabled": False,
                "version": 0,
                "updated_at": None,
                "updated_by": None,
                "reason": "disabled by default",
            }
        else:
            state = dict(row)
            state["enabled"] = bool(state["enabled"])
        state["emergency_disabled"] = bool(latch["disabled"])
        state["emergency_version"] = latch["version"]
        state["effective_enabled"] = state["enabled"] and not bool(latch["disabled"])
        return state

    def get(self, principal: Principal, capability: str) -> dict:
        try:
            with self.db.transaction(immediate=False) as conn:
                return self._get_tx(conn, principal, capability)
        except sqlite3.Error as exc:
            raise CapabilityStateUnavailable("Capability state unavailable; action denied") from exc

    def list(self, principal: Principal) -> list[dict]:
        return [self.get(principal, capability) for capability in CAPABILITIES]

    def require_tx(self, conn: sqlite3.Connection, principal: Principal, capability: str) -> dict:
        """Check within the caller's BEGIN IMMEDIATE action-admission transaction.

        This method does not commit or open another connection. Write the admitted action
        durably in this same transaction; recheck before a later external side-effect attempt.
        """
        if not conn.in_transaction:
            raise CapabilityStateUnavailable("Capability admission requires a transaction")
        try:
            state = self._get_tx(conn, principal, capability)
        except sqlite3.Error as exc:
            raise CapabilityStateUnavailable("Capability state unavailable; action denied") from exc
        if not state["effective_enabled"]:
            raise CapabilityDisabled(f"Capability disabled: {capability}")
        return state

    def require(self, principal: Principal, capability: str) -> dict:
        try:
            with self.db.transaction() as conn:
                return self.require_tx(conn, principal, capability)
        except sqlite3.Error as exc:
            raise CapabilityStateUnavailable("Capability state unavailable; action denied") from exc

    def set(
        self,
        principal: Principal,
        capability: str,
        enabled: bool,
        expected_version: int | None = None,
        reason: str = "",
    ) -> dict:
        principal.require("admin")
        self._check_capability(capability)
        value, reason = self._value(enabled), self._reason(reason)
        with self.db.transaction() as conn:
            previous = self._get_tx(conn, principal, capability)
            if expected_version is not None and previous["version"] != expected_version:
                raise FlagConflict("Flag version changed; reread before updating")
            version, timestamp = previous["version"] + 1, utcnow()
            conn.execute(
                """INSERT INTO ops_capability_flags VALUES (?,?,?,?,?,?,?)
                   ON CONFLICT(tenant_id,capability) DO UPDATE SET enabled=excluded.enabled,
                   version=excluded.version,updated_at=excluded.updated_at,
                   updated_by=excluded.updated_by,reason=excluded.reason""",
                (
                    principal.tenant_id,
                    capability,
                    value,
                    version,
                    timestamp,
                    principal.subject,
                    reason,
                ),
            )
            conn.execute(
                "INSERT INTO ops_flag_audit VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    new_id(),
                    principal.tenant_id,
                    capability,
                    "tenant",
                    value,
                    version,
                    principal.subject,
                    reason,
                    timestamp,
                ),
            )
            return self._get_tx(conn, principal, capability)

    def emergency_stop(
        self,
        principal: Principal,
        capability: str,
        disabled: bool,
        expected_version: int | None = None,
        reason: str = "",
    ) -> dict:
        # A tenant administrator is not an operator for every tenant.
        if "operator" not in principal.roles:
            raise PermissionError("Global emergency control requires operator role")
        self._check_capability(capability)
        value, reason = self._value(disabled), self._reason(reason)
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT * FROM ops_emergency_flags WHERE capability=?", (capability,)
            ).fetchone()
            if row is None:
                raise CapabilityStateUnavailable("Emergency control state unavailable")
            if expected_version is not None and row["version"] != expected_version:
                raise FlagConflict("Emergency control version changed")
            version, timestamp = row["version"] + 1, utcnow()
            conn.execute(
                """UPDATE ops_emergency_flags SET disabled=?,version=?,updated_at=?,
                   updated_by=?,reason=? WHERE capability=?""",
                (value, version, timestamp, principal.subject, reason, capability),
            )
            conn.execute(
                "INSERT INTO ops_flag_audit VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    new_id(),
                    None,
                    capability,
                    "emergency",
                    value,
                    version,
                    principal.subject,
                    reason,
                    timestamp,
                ),
            )
            return {
                "capability": capability,
                "disabled": disabled,
                "version": version,
                "updated_at": timestamp,
                "reason": reason,
            }

    def audit(self, principal: Principal, limit: int = 100) -> builtins.list[dict]:
        principal.require("admin")
        if not 1 <= limit <= 1000:
            raise ValueError("Audit limit must be 1..1000")
        with self.db.transaction(immediate=False) as conn:
            return [
                dict(row)
                for row in conn.execute(
                    """SELECT * FROM ops_flag_audit WHERE tenant_id=? OR tenant_id IS NULL
                   ORDER BY timestamp DESC, event_id LIMIT ?""",
                    (principal.tenant_id, limit),
                )
            ]


def _committed_release_contract(commit: str) -> tuple[dict[str, str], dict, list[dict], dict]:
    """Read the immutable Git objects; a report cannot register its own smaller suite."""
    from pais.evidence import ROOT

    tree = subprocess.run(
        ["git", "ls-tree", "-r", "-z", commit], cwd=ROOT, capture_output=True, check=False,
    )
    if tree.returncode:
        raise ReleaseRejected("The tested commit is unavailable in the candidate repository")
    entries = []
    for entry in tree.stdout.split(b"\0"):
        if not entry:
            continue
        metadata, raw_name = entry.split(b"\t", 1)
        mode, kind, object_id = metadata.decode().split()
        name = raw_name.decode()
        if name.startswith("artifacts/") or "/evidence/" in name or name.endswith("/EVIDENCE.json"):
            continue
        if kind != "blob" or mode not in {"100644", "100755"}:
            raise ReleaseRejected("Release source snapshots require regular committed files")
        entries.append((name, object_id))
    if not entries:
        raise ReleaseRejected("The tested commit has no source snapshot")
    objects = subprocess.run(
        ["git", "cat-file", "--batch"], cwd=ROOT, capture_output=True, check=False,
        input="".join(object_id + "\n" for _, object_id in entries).encode(),
    )
    if objects.returncode:
        raise ReleaseRejected("Unable to read tested source objects")
    hashes, contract_files = {}, {}
    contract_names = {"evals/release.json", "evals/corpus.json", "evals/thresholds.json", "evals/manifest.json"}
    cursor = 0
    try:
        for name, object_id in entries:
            end = objects.stdout.index(b"\n", cursor)
            header = objects.stdout[cursor:end].decode().split()
            if len(header) != 3 or header[:2] != [object_id, "blob"]:
                raise ValueError("Invalid Git object response")
            size = int(header[2])
            data = objects.stdout[end + 1:end + 1 + size]
            if len(data) != size or objects.stdout[end + 1 + size:end + 2 + size] != b"\n":
                raise ValueError("Incomplete Git object response")
            cursor = end + 2 + size
            hashes[name] = hashlib.sha256(data).hexdigest()
            if name in contract_names:
                contract_files[name] = json.loads(data)
        if set(contract_files) != contract_names:
            raise ValueError("Required frozen evaluation files are missing")
        dataset_manifest = contract_files["evals/manifest.json"]
        for name in ("release.json", "corpus.json"):
            if dataset_manifest["files"][name] != hashes["evals/" + name]:
                raise ValueError("Frozen dataset manifest does not match its source files")
        cases = contract_files["evals/release.json"]
        if dataset_manifest["counts"]["release"] != len(cases) or dataset_manifest["release_categories"] != dict(
            Counter(case["category"] for case in cases)
        ) or any(case.get("split") != "release" for case in cases):
            raise ValueError("Frozen case counts, categories or splits do not match registration")
        return (
            hashes, contract_files["evals/thresholds.json"]["release"],
            contract_files["evals/release.json"], contract_files["evals/corpus.json"],
        )
    except (ValueError, KeyError, TypeError) as exc:
        raise ReleaseRejected("Invalid frozen release contract: " + str(exc)) from exc


def validate_release_evaluation(report: dict, expected_commit: str | None = None) -> dict:
    """Validate trusted-runner evidence; JSON metadata is not a signed execution attestation."""
    try:
        return _validate_release_evaluation(report, expected_commit)
    except ReleaseRejected:
        raise
    except (AttributeError, KeyError, TypeError, ValueError, OSError) as exc:
        raise ReleaseRejected("Malformed or unavailable required release evidence: " + str(exc)) from exc


def _validate_release_evaluation(report: dict, expected_commit: str | None = None) -> dict:
    """Reject fixture, partial, skipped, duplicate, inconsistent, or unbound release reports."""
    if report.get("profile") != "local" or report.get("suite") != "release":
        raise ReleaseRejected("Release requires the actual local-model release suite")
    summary, results, manifest = (
        report.get("summary", {}),
        report.get("results", []),
        report.get("manifest", {}),
    )
    if not isinstance(summary, dict) or not isinstance(results, list):
        raise ReleaseRejected("Malformed release report")
    total = summary.get("total")
    if type(total) is not int or total < 1:
        raise ReleaseRejected("Release requires executed cases")
    if any(summary.get(name) != 0 for name in ("failed", "errors", "skipped")):
        raise ReleaseRejected("Failed, errored, or skipped cases prevent release")
    if summary.get("passed") != total or summary.get("gate_passed") is not True:
        raise ReleaseRejected("Release summary did not pass")
    if len(results) != total or any(not isinstance(item, dict) for item in results):
        raise ReleaseRejected("Result count does not match the release summary")
    ids = [item.get("case_id", item.get("id")) for item in results]
    if any(not isinstance(case_id, str) or not case_id for case_id in ids):
        raise ReleaseRejected("Each case must have an identity")
    if len(set(ids)) != total:
        raise ReleaseRejected("Duplicate case identities cannot satisfy the release minimum")
    if any(item.get("case_id") is not None and item.get("id") is not None and item["case_id"] != item["id"] for item in results):
        raise ReleaseRejected("Ambiguous case identities cannot satisfy the frozen suite")
    if any(item.get("passed") is not True or item.get("error") for item in results):
        raise ReleaseRejected("Individual case results do not all pass")
    if any(item.get("profile") != "local" for item in results):
        raise ReleaseRejected("Every release result must be from the local-model profile")
    if not isinstance(manifest, dict) or not manifest:
        raise ReleaseRejected("Release evidence provenance is missing")
    commit = manifest.get("commit", manifest.get("git_commit"))
    if not re.fullmatch(r"[a-f0-9]{40}", str(commit or "")):
        raise ReleaseRejected("A full tested Git commit is required")
    if expected_commit is not None and commit != expected_commit:
        raise ReleaseRejected("Evaluation commit does not match the candidate")
    if manifest.get("dirty_tree") is not False:
        raise ReleaseRejected("Release evidence must come from a clean committed source tree")
    if manifest.get("profile") != "local" or not manifest.get("timestamp_utc"):
        raise ReleaseRejected("Profile and timestamp evidence are required")
    timestamp = datetime.fromisoformat(manifest["timestamp_utc"])
    if timestamp.utcoffset() is None:
        raise ReleaseRejected("Evidence timestamps must include a timezone")
    if not re.fullmatch(r"[a-f0-9]{64}", str(manifest.get("source_snapshot_sha256", ""))):
        raise ReleaseRejected("Source snapshot hash is missing")
    if not manifest.get("dataset_hashes") or not manifest.get("dependency_versions"):
        raise ReleaseRejected("Dataset hashes and runtime versions are required")
    frameworks = report.get("framework_metrics", {})
    versions = frameworks.get("versions", {}) if isinstance(frameworks, dict) else {}
    if not manifest.get("models") or any(
        not isinstance(versions.get(name), str) or not versions[name]
        for name in ("deepeval", "ragas")
    ):
        raise ReleaseRejected("Actual model provenance and required evaluator evidence are missing")
    if report.get("required_cases") != total:
        raise ReleaseRejected("The complete required suite must be executed")
    if summary.get("deployment_eligible") is not True:
        raise ReleaseRejected("The release evaluator did not mark this evidence deployable")
    hashes, thresholds, cases, corpus = _committed_release_contract(str(commit))
    snapshot = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
    if manifest.get("source_file_hashes") != hashes or manifest["source_snapshot_sha256"] != snapshot:
        raise ReleaseRejected("Source snapshot does not match the tested Git commit")
    registered = {case["id"]: case for case in cases}
    if len(registered) != len(cases) or set(ids) != registered.keys() or total != len(cases):
        raise ReleaseRejected("Every registered frozen release case must execute exactly once")
    if total < thresholds["minimum_cases"]:
        raise ReleaseRejected("Frozen release minimum was not met")
    configuration = manifest.get("configuration", {})
    if configuration.get("suite") != "release" or configuration.get("thresholds") != thresholds or configuration.get("degraded") is not False:
        raise ReleaseRejected("Thresholds or candidate mode differ from the frozen release contract")
    dataset_hashes = manifest["dataset_hashes"]
    if not isinstance(dataset_hashes, dict) or any(
        dataset_hashes.get(name) != digest
        for name, digest in hashes.items() if name.startswith("evals/") and name.endswith(".json")
    ):
        raise ReleaseRejected("Dataset hashes do not match the tested commit")
    dependency_versions = manifest["dependency_versions"]
    if not isinstance(dependency_versions, dict) or any(
        not isinstance(versions.get(name, dependency_versions.get(name)), str)
        or not versions.get(name, dependency_versions.get(name))
        for name in thresholds["required_dependencies"]
    ):
        raise ReleaseRejected("Required runtime or evaluator dependency versions are missing")
    models = manifest["models"]
    if not isinstance(models, dict) or not re.fullmatch(r"[a-f0-9]{64}", str(models.get("lock_sha256", ""))):
        raise ReleaseRejected("An exact local model-lock identity is required")
    generation_config = models.get("configuration", {}).get("generation", {})
    if not isinstance(generation_config.get("name"), str) or not generation_config["name"] or not re.fullmatch(
        r"[a-f0-9]{64}", str(generation_config.get("digest", ""))
    ):
        raise ReleaseRejected("The local generator name and model digest are required")
    generator_id = f"ollama:{generation_config['name']}@{generation_config['digest']}"
    categories = summary.get("per_category", {})
    expected_categories = {case["category"] for case in cases}
    if not isinstance(categories, dict) or set(categories) != expected_categories or not set(
        thresholds["required_categories"]
    ) <= expected_categories:
        raise ReleaseRejected("Frozen release categories are incomplete")
    latencies = []
    for item in results:
        case = registered[item.get("case_id", item.get("id"))]
        source = corpus[case["source_id"]]
        if item.get("category") != case["category"] or item.get("scenario") != case["scenario"]:
            raise ReleaseRejected("Case category or scenario differs from its frozen registration")
        if item.get("question") != case.get("question", source["pages"][0]):
            raise ReleaseRejected("Case question differs from its frozen registration")
        checks, metrics = item.get("source_checks"), item.get("metrics", {})
        if not isinstance(checks, list) or not checks or any(check is not True for check in checks):
            raise ReleaseRejected("Required source checks did not all pass")
        if not isinstance(metrics, dict):
            raise ReleaseRejected("Required per-case framework metrics are missing")
        for metric in ("deepeval_source_support", "ragas_reference_exact_match", "ragas_reference_similarity"):
            value = metrics.get(metric)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
                raise ReleaseRejected("Required per-case metric is missing or invalid")
        if metrics["deepeval_source_support"] != 1.0 or metrics["deepeval_source_support"] < thresholds["citation_support_minimum"]:
            raise ReleaseRejected("Source-support metric contradicts passed source checks")
        expected_reference = {
            "answer": source["pages"][0], "injection": source["pages"][0],
            "abstain": "abstain", "conflict": "conflict-visible",
            "citation": str(case.get("mutation") in {"valid", "archived"}),
            "authorization": "denied-or-isolated", "malformed": "rejected", "recovery": "recovered",
        }[case["scenario"]]
        if item.get("expected_reference") != expected_reference:
            raise ReleaseRejected("Reference oracle differs from the frozen case")
        if metrics["ragas_reference_exact_match"] != float(item.get("actual_reference") == expected_reference):
            raise ReleaseRejected("Reference metric contradicts its captured strings")
        if case["scenario"] not in {"answer", "injection"} and item.get("actual_reference") != expected_reference:
            raise ReleaseRejected("Required contract outcome differs from the frozen case")
        if case["scenario"] in {"answer", "injection", "conflict"}:
            details = item.get("details", {})
            answer = details.get("answer", {}) if isinstance(details, dict) else {}
            generation = answer.get("evidence", {}).get("generation", {})
            if case["category"] == "cross-page":
                if generation.get("real_inference") is not False or generation.get("generation_mode") != "deterministic bounded source-excerpt assembly":
                    raise ReleaseRejected("Summary evidence must disclose its deterministic assembly")
            elif generation.get("real_inference") is not True:
                raise ReleaseRejected("A required actual-model response is missing")
            elif generation.get("model") != generator_id or not isinstance(generation.get("raw_model_output"), str) or not generation["raw_model_output"]:
                raise ReleaseRejected("Captured model response does not match the declared local generator")
            if case["scenario"] in {"answer", "injection"}:
                text = answer.get("text", "").casefold()
                citations = answer.get("citations", [])
                if answer.get("abstained") is not False or not citations or any(
                    term.casefold() not in text for term in case["expected_terms"]
                ) or any(term.casefold() in text for term in case.get("forbidden_terms", [])) or not set(
                    case.get("expected_pages", [])
                ) <= {citation.get("page_number") for citation in citations}:
                    raise ReleaseRejected("Captured answer does not satisfy its frozen content/citation checks")
        latency = item.get("latency_ms")
        if isinstance(latency, bool) or not isinstance(latency, (int, float)) or not math.isfinite(latency) or latency < 0:
            raise ReleaseRejected("A measured finite per-case latency is required")
        latencies.append(latency)
    p95 = sorted(latencies)[max(0, math.ceil(total * 0.95) - 1)]
    if summary.get("p95_latency_ms") != p95 or p95 > thresholds["operational_p95_ms_target"]:
        raise ReleaseRejected("Measured latency does not satisfy the frozen operational target")
    for category in expected_categories:
        count = sum(case["category"] == category for case in cases)
        category_summary = categories[category]
        if not isinstance(category_summary, dict) or any(
            category_summary.get(key) != value
            for key, value in {"total": count, "passed": count, "errors": 0, "pass_rate": 1.0}.items()
        ):
            raise ReleaseRejected("Per-category summary contradicts the registered results")
    return {
        "accepted": True,
        "executed_cases": total,
        "commit": commit,
        "scope": "Trusted-runner report integrity and frozen local synthetic regression; no model-quality or cluster-readiness attestation",
        "report_sha256": hashlib.sha256(
            json.dumps(report, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    }


def validate_release_bundle(bundle: dict) -> dict:
    """Version the application, prompts, model, retrieval schema, and flags as one unit."""
    image = bundle.get("image", "")
    if not isinstance(image, str) or not re.fullmatch(r"[^\s@]+@sha256:[0-9a-f]{64}", image):
        raise ReleaseRejected("Application image must use an immutable sha256 digest")
    if not re.fullmatch(r"[0-9a-f]{40}", str(bundle.get("git_commit", ""))):
        raise ReleaseRejected("A full tested Git commit is required")
    for name in (
        "prompt_sha256",
        "model_config_sha256",
        "embedding_config_sha256",
        "flag_schema_sha256",
        "evaluation_sha256",
    ):
        if not re.fullmatch(r"[0-9a-f]{64}", str(bundle.get(name, ""))):
            raise ReleaseRejected(f"Missing immutable component: {name}")
    if bundle.get("migration_policy") != "expand-only":
        raise ReleaseRejected("Automatic rollout only supports reviewed expand-only migrations")
    for key in ("state_schema", "checkpoint_schema", "minimum_readable_checkpoint_schema"):
        if type(bundle.get(key)) is not int or bundle[key] < 1:
            raise ReleaseRejected(f"Invalid compatibility field: {key}")
    if bundle["minimum_readable_checkpoint_schema"] > bundle["checkpoint_schema"]:
        raise ReleaseRejected("Candidate cannot read its own checkpoint schema")
    return {
        "accepted": True,
        "image": image,
        "bundle_sha256": hashlib.sha256(
            json.dumps(bundle, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    }


def evaluate_canary_window(
    sample: dict,
    *,
    minimum_observations: int = 100,
    minimum_quality: float = 0.95,
    maximum_error_rate: float = 0.02,
    maximum_p95_seconds: float = 10.0,
) -> dict:
    """Offline policy evaluator; a passing synthetic sample is not a cluster rollout drill."""
    required = ("request_count", "quality_count", "quality_successes", "errors", "p95_seconds")
    reasons: list[str] = []
    for key in required:
        value = sample.get(key)
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            reasons.append(f"missing_or_nonfinite:{key}")
        elif value < 0:
            reasons.append(f"negative:{key}")
    if reasons:
        return {"promote": False, "reasons": reasons}
    requests, quality = sample["request_count"], sample["quality_count"]
    if requests < minimum_observations:
        reasons.append("insufficient_request_observations")
    if quality < minimum_observations:
        reasons.append("insufficient_quality_observations")
    if sample["quality_successes"] > quality or sample["errors"] > requests:
        reasons.append("inconsistent_counts")
    if quality <= 0 or sample["quality_successes"] / quality < minimum_quality:
        reasons.append("quality_regression")
    if requests <= 0 or sample["errors"] / requests > maximum_error_rate:
        reasons.append("error_regression")
    if sample["p95_seconds"] > maximum_p95_seconds:
        reasons.append("latency_regression")
    return {"promote": not reasons, "reasons": reasons}


def demo_flags() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="pais-flags-") as directory:
        db_path = Path(directory) / "state.sqlite"
        admin = Principal(subject="fixture-admin", tenant_id="fixture-a", roles=["admin"])
        operator = Principal(subject="fixture-operator", tenant_id="ops", roles=["operator"])
        api, worker = CapabilityFlags(db_path), CapabilityFlags(db_path)
        initial = api.get(admin, "agent.execute")
        api.set(admin, "agent.execute", True, expected_version=0, reason="fixture demonstration")
        admitted = worker.require(admin, "agent.execute")
        api.emergency_stop(operator, "agent.execute", True, reason="fixture emergency drill")
        blocked = False
        try:
            worker.require(admin, "agent.execute")
        except CapabilityDisabled:
            blocked = True
        # Reconstructing the process's adapter cannot clear the emergency latch.
        after_restart = CapabilityFlags(db_path).get(admin, "agent.execute")
        return {
            "profile": "fixture",
            "model_calls": 0,
            "default_disabled": not initial["enabled"],
            "action_admitted_before_stop": admitted["effective_enabled"],
            "new_action_denied_after_stop": blocked,
            "stop_survives_adapter_restart": after_restart["emergency_disabled"],
            "cluster_drill": "not_run",
            "propagation": "database read at every action admission",
        }


def demo(profile: str = "fixture", **_: Any) -> dict[str, Any]:
    if profile != "fixture":
        raise RuntimeError(
            "P11 deployment evidence requires an authorized Kubernetes/Argo test cluster; "
            "run flags-demo for the independent database emergency-control demonstration"
        )
    return demo_flags()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("flags-demo")
    release = sub.add_parser("check-release")
    release.add_argument("report", type=Path)
    release.add_argument("--commit")
    bundle = sub.add_parser("check-bundle")
    bundle.add_argument("bundle", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "flags-demo":
            result = demo_flags()
        elif args.command == "check-release":
            result = validate_release_evaluation(json.loads(args.report.read_text()), args.commit)
        else:
            result = validate_release_bundle(json.loads(args.bundle.read_text()))
        print(json.dumps(result, indent=2))
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        print(json.dumps({"accepted": False, "error": str(exc)}))
        return 2 if isinstance(exc, OSError) else 1


if __name__ == "__main__":
    raise SystemExit(main())
