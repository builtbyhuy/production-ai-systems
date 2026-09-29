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
import tempfile
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


def validate_release_evaluation(report: dict, expected_commit: str | None = None) -> dict:
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
    if type(total) is not int or total < 100:
        raise ReleaseRejected("Release requires at least 100 executed cases")
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
    if any(item.get("passed") is not True or item.get("error") for item in results):
        raise ReleaseRejected("Individual case results do not all pass")
    if any(item.get("profile") != "local" for item in results):
        raise ReleaseRejected("Every release result must be from the local-model profile")
    if not isinstance(manifest, dict) or not manifest:
        raise ReleaseRejected("Release evidence provenance is missing")
    commit = manifest.get("commit", manifest.get("git_commit"))
    if not re.fullmatch(r"[a-f0-9]{40}", str(commit or "")):
        raise ReleaseRejected("A full tested Git commit is required")
    if manifest.get("dirty_tree") is not False:
        raise ReleaseRejected("Release evidence must come from a clean committed source tree")
    if manifest.get("profile") != "local" or not manifest.get("timestamp_utc"):
        raise ReleaseRejected("Profile and timestamp evidence are required")
    if not re.fullmatch(r"[a-f0-9]{64}", str(manifest.get("source_snapshot_sha256", ""))):
        raise ReleaseRejected("Source snapshot hash is missing")
    if not manifest.get("dataset_hashes") or not manifest.get("dependency_versions"):
        raise ReleaseRejected("Dataset hashes and runtime versions are required")
    if not manifest.get("models") or not report.get("framework_metrics"):
        raise ReleaseRejected("Actual model provenance and required evaluator evidence are missing")
    if report.get("required_cases") != total:
        raise ReleaseRejected("The complete required suite must be executed")
    if summary.get("deployment_eligible") is not True:
        raise ReleaseRejected("The release evaluator did not mark this evidence deployable")
    if expected_commit is not None and commit != expected_commit:
        raise ReleaseRejected("Evaluation commit does not match the candidate")
    return {
        "accepted": True,
        "executed_cases": total,
        "commit": commit,
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
