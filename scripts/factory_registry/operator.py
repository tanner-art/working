"""Fail-closed operator operations for the local Factory Registry cutover."""

from __future__ import annotations

import hashlib
import json
import os
import plistlib
import re
import shutil
import sqlite3
import stat
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from scripts.runner import install_launchd
from scripts.runner.registry_control import RunnerRegistryControl, queue_contract_digest

from .models import (
    DispatchSnapshot,
    Feature,
    Lane,
    PackageCapacityRisk,
    PackageCapacitySize,
    PackageKind,
    TaskStatus,
    Worker,
    WorkPackage,
)
from .repository import RegistryConflict
from .shadow_dispatch import decide_shadow
from .sqlite_registry import CONTROL_SCHEMA_VERSION, CURRENT_SCHEMA_VERSION, SQLiteRegistry


EXPECTED_USAGE_POLICY = {
    "caution_percent": 90,
    "checkpoint_percent": 95,
    "hard_stop_percent": 98,
    "stale_after_seconds": 3600,
    "unknown_behavior": "defer",
}
HEARTBEAT_FRESH_SECONDS = 180
USAGE_FRESH_SECONDS = 900
SENSITIVE_KEY_PARTS = ("password", "secret", "token", "credential", "api_key", "apikey")


class OperatorError(RuntimeError):
    """An operator gate failed before an unsafe transition."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _parse_time(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise OperatorError(f"{field} must be a timezone-aware timestamp")
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as error:
        raise OperatorError(f"{field} is invalid") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise OperatorError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _age_seconds(value: Any, observed_at: str, field: str) -> float:
    return (_parse_time(observed_at, "observed_at") - _parse_time(value, field)).total_seconds()


def _load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise OperatorError(f"cannot read {label}: {error}") from error
    if not isinstance(value, dict):
        raise OperatorError(f"{label} must be a JSON object")
    return value


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json_digest(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _sensitive_paths(value: Any, prefix: str = "") -> tuple[str, ...]:
    found = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            normalized = str(key).lower().replace("-", "_")
            if any(part in normalized for part in SENSITIVE_KEY_PARTS):
                found.append(path)
            found.extend(_sensitive_paths(item, path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(_sensitive_paths(item, f"{prefix}[{index}]"))
    return tuple(found)


def verify_release(release: Path, expected_commit: str) -> Mapping[str, Any]:
    release = release.resolve()
    if not release.is_dir() or release.is_symlink():
        raise OperatorError("release must be an existing non-symlink directory")
    commit_path = release / "COMMIT"
    manifest_path = release / "MANIFEST.sha1"
    try:
        commit = commit_path.read_text().strip()
        lines = manifest_path.read_text().splitlines()
    except OSError as error:
        raise OperatorError(f"release metadata unavailable: {error}") from error
    if commit != expected_commit:
        raise OperatorError(f"release commit mismatch: expected {expected_commit}, got {commit}")
    checked = []
    for line in lines:
        if not line:
            continue
        try:
            digest, relative = line.split("  ", 1)
        except ValueError as error:
            raise OperatorError("release manifest is malformed") from error
        if len(digest) != 40 or any(value not in "0123456789abcdef" for value in digest):
            raise OperatorError("release manifest contains an invalid SHA-1")
        relative_path = Path(relative)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise OperatorError("release manifest path escapes the release")
        target = release / relative_path
        if target.is_symlink() or not target.is_file():
            raise OperatorError(f"release manifest target invalid: {relative}")
        actual = hashlib.sha1(target.read_bytes()).hexdigest()  # nosec - release manifest format
        if actual != digest:
            raise OperatorError(f"release manifest mismatch: {relative}")
        checked.append(relative)
    required = {
        "scripts/runner/runner.py",
        "scripts/runner/install_launchd.py",
        "scripts/factory_registry/sqlite_registry.py",
        "scripts/factory_registry/operator.py",
        "scripts/factory_registry/operator_cli.py",
    }
    # An older staged release can be inspected but cannot be used by this new
    # operator package. The release builder must include the operator itself.
    missing = sorted(required - set(checked))
    if missing:
        raise OperatorError("release manifest missing operator files: " + ",".join(missing))
    return {
        "path": str(release),
        "commit": commit,
        "manifest_sha256": _sha256_file(manifest_path),
        "manifest_files": len(checked),
    }


def verify_preservation(
    registry_snapshot: Any,
    preservation_path: Path,
) -> Mapping[str, Any]:
    if not preservation_path.is_absolute() or not preservation_path.is_file():
        raise OperatorError("preservation snapshot must be an existing absolute file")
    digest = _sha256_file(preservation_path)
    imports = tuple(registry_snapshot.preservation_imports)
    if not imports:
        raise OperatorError("Registry has no preservation import")
    matching = [value for value in imports if value.get("source_sha256") == digest]
    if len(matching) != 1:
        raise OperatorError("preservation SHA-256 does not match exactly one Registry import")
    source = _load_object(preservation_path, "preservation snapshot")
    reconciliation = dict(matching[0].get("reconciliation") or {})
    expected = {
        "expected_worktrees": len(source.get("worktrees", ())),
        "expected_branches": len(source.get("unmerged_local_branches", ())),
        "expected_tasks": len(source.get("open_task_mapping", ())),
        "expected_workers": len((source.get("services") or {}).get("heartbeats", {})),
        "unexplained_records": 0,
    }
    mismatches = {
        key: {"expected": value, "registry": reconciliation.get(key)}
        for key, value in expected.items()
        if reconciliation.get(key) != value
    }
    if source.get("dirty_worktree_count") != sum(
        1 for value in source.get("worktrees", ()) if value.get("dirty")
    ):
        mismatches["dirty_worktree_count"] = "snapshot-internal-mismatch"
    if mismatches:
        raise OperatorError("preservation reconciliation mismatch: " + json.dumps(mismatches, sort_keys=True))
    return {
        "path": str(preservation_path),
        "sha256": digest,
        "worktrees": expected["expected_worktrees"],
        "dirty_worktrees": source.get("dirty_worktree_count"),
        "unmerged_branches": expected["expected_branches"],
        "tasks": expected["expected_tasks"],
        "workers": expected["expected_workers"],
        "unexplained_records": 0,
    }


def _database_checks(database: Path) -> Mapping[str, Any]:
    uri = f"{database.resolve().as_uri()}?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True)
        try:
            integrity = tuple(row[0] for row in connection.execute("PRAGMA integrity_check"))
            foreign_keys = tuple(connection.execute("PRAGMA foreign_key_check"))
            journal_mode = str(connection.execute("PRAGMA journal_mode").fetchone()[0]).lower()
            metadata = dict(connection.execute("SELECT key, value FROM registry_metadata"))
        finally:
            connection.close()
    except sqlite3.Error as error:
        raise OperatorError(f"Registry database check failed: {error}") from error
    if integrity != ("ok",) or foreign_keys:
        raise OperatorError("Registry integrity or foreign-key check failed")
    if journal_mode != "wal":
        raise OperatorError(f"Registry journal mode must be WAL, got {journal_mode}")
    return {
        "integrity": "ok",
        "foreign_key_violations": 0,
        "journal_mode": journal_mode,
        "schema_version": metadata.get("schema_version"),
        "control_schema_version": metadata.get("control_schema_version"),
    }


def status(database: Path, *, observed_at: str | None = None) -> Mapping[str, Any]:
    if not database.is_absolute() or not database.is_file():
        raise OperatorError("--database must be an existing absolute Registry path")
    observed_at = observed_at or utc_now()
    registry = SQLiteRegistry(database)
    checks = _database_checks(database)
    control = dict(registry.dispatch_control())
    snapshot = registry.control_center_snapshot(observed_at=observed_at)
    active_leases = [value for value in snapshot.leases if value.get("released_at") is None]
    active_attempts = [value for value in snapshot.attempts if value.get("ended_at") is None]
    runtimes = registry.active_attempt_runtimes()
    unbound = registry.active_unbound_leases()
    orphans = registry.runtime_orphans(observed_at=observed_at)
    return {
        "kind": "threadline-factory-operator-status",
        "observed_at": observed_at,
        "database": str(database),
        "database_checks": checks,
        "control": control,
        "counts": {
            "features": len(snapshot.features),
            "packages": len(snapshot.work_packages),
            "workers": len(snapshot.workers),
            "preservation_imports": len(snapshot.preservation_imports),
            "active_leases": len(active_leases),
            "active_attempts": len(active_attempts),
            "active_runtimes": len(runtimes),
            "active_unbound_leases": len(unbound),
            "runtime_orphans": len(orphans),
        },
        "workers": [
            {
                "id": value.get("id"),
                "role": value.get("role"),
                "availability": value.get("availability"),
                "last_heartbeat_at": value.get("last_heartbeat_at"),
                "usage_state": value.get("usage_state"),
            }
            for value in snapshot.workers
        ],
    }


def _validate_config(config: Mapping[str, Any], database: Path) -> None:
    if config.get("registry_database") != str(database):
        raise OperatorError("config registry_database does not name the authoritative Registry")
    if config.get("registry_lease_seconds") != 2100:
        raise OperatorError("config registry_lease_seconds must be 2100")
    if config.get("registry_renew_interval_seconds") != 30:
        raise OperatorError("config registry_renew_interval_seconds must be 30")
    if config.get("usage_policy") != EXPECTED_USAGE_POLICY:
        raise OperatorError("config usage policy does not match the reviewed 90/95/98/defer policy")
    for field in ("repo", "state", "worktrees"):
        value = config.get(field)
        if not isinstance(value, str) or not Path(value).is_absolute():
            raise OperatorError(f"config {field} must be an absolute path")
    agents = config.get("agents")
    if not isinstance(agents, Mapping) or not agents:
        raise OperatorError("config agents must be a non-empty object")
    for worker_id, value in agents.items():
        if not isinstance(value, Mapping):
            raise OperatorError(f"config agent {worker_id} must be an object")
        mode = value.get("capacity_mode")
        scopes = value.get("capacity_scopes")
        if mode == "provider_signal":
            valid = scopes == ["provider_signal"]
        else:
            valid = mode == "percentage" and isinstance(scopes, list) and bool(scopes) and "provider_signal" not in scopes
        if not valid or len(scopes) != len(set(scopes)):
            raise OperatorError(f"config agent {worker_id} has invalid capacity mode/scopes")
    sensitive = _sensitive_paths(config)
    if sensitive:
        raise OperatorError("config contains secret-shaped fields: " + ",".join(sensitive))


def migrate_config(
    config: Mapping[str, Any], database: Path, migration: Mapping[str, Any]
) -> dict[str, Any]:
    result = json.loads(json.dumps(config))
    agents = result.get("agents")
    migration_agents = migration.get("agents")
    if not isinstance(agents, dict) or not isinstance(migration_agents, Mapping):
        raise OperatorError("config migration requires an agents mapping")
    if set(agents) != set(migration_agents):
        raise OperatorError("config migration must explicitly cover every configured agent")
    for worker_id, requested in migration_agents.items():
        if not isinstance(requested, Mapping):
            raise OperatorError(f"migration agent {worker_id} must be an object")
        if set(requested) != {"capacity_mode", "capacity_scopes"}:
            raise OperatorError(
                f"migration agent {worker_id} may set only capacity_mode/capacity_scopes"
            )
        agents[worker_id]["capacity_mode"] = requested["capacity_mode"]
        agents[worker_id]["capacity_scopes"] = requested["capacity_scopes"]
    result["registry_database"] = str(database)
    result["registry_lease_seconds"] = 2100
    result["registry_renew_interval_seconds"] = 30
    result["usage_policy"] = dict(EXPECTED_USAGE_POLICY)
    _validate_config(result, database)
    return result


def _path_mode(path: Path) -> int | None:
    try:
        return stat.S_IMODE(path.lstat().st_mode)
    except FileNotFoundError:
        return None


def verify_permissions(
    database: Path, config_path: Path, release: Path
) -> Mapping[str, Any]:
    failures = []
    registry_dir = database.parent
    if _path_mode(registry_dir) != 0o700:
        failures.append(f"{registry_dir}:expected-0700")
    for path in (database, Path(f"{database}-wal"), Path(f"{database}-shm"), config_path):
        mode = _path_mode(path)
        if mode is not None and mode != 0o600:
            failures.append(f"{path}:expected-0600")
    config = _load_object(config_path, "runner config")
    for field in ("state", "worktrees"):
        value = config.get(field)
        if not isinstance(value, str) or not Path(value).is_absolute():
            failures.append(f"config-{field}:expected-absolute-path")
            continue
        path = Path(value)
        if _path_mode(path) != 0o700:
            failures.append(f"{path}:expected-0700")
    release_mode = _path_mode(release)
    if release_mode is None or release_mode & 0o222 or release_mode & 0o077:
        failures.append(f"{release}:release-root-not-private-immutable")
    for path in release.rglob("*"):
        metadata = path.lstat()
        if path.is_symlink():
            failures.append(f"{path}:symlink")
        elif stat.S_IMODE(metadata.st_mode) & 0o222:
            failures.append(f"{path}:writable")
        elif stat.S_IMODE(metadata.st_mode) & 0o077:
            failures.append(f"{path}:group-or-world-access")
    if failures:
        raise OperatorError("private/immutable permission gate failed: " + ",".join(failures))
    return {
        "registry_directory_mode": "0700",
        "database_mode": "0600",
        "config_mode": "0600",
        "release_write_bits": 0,
    }


def harden_paths(database: Path, config_path: Path, release: Path) -> None:
    for directory in (database.parent, database.parent / "evidence"):
        if directory.exists():
            install_launchd._set_owner_only(directory, 0o700)
    for path in (database, Path(f"{database}-wal"), Path(f"{database}-shm"), config_path):
        if path.exists():
            install_launchd._set_owner_only(path, 0o600)
    paths = sorted(release.rglob("*"), key=lambda value: len(value.parts), reverse=True)
    for path in paths:
        if path.is_symlink():
            raise OperatorError(f"release contains symlink: {path}")
        mode = 0o500 if path.is_dir() or os.access(path, os.X_OK) else 0o400
        install_launchd._set_owner_only(path, mode)
    install_launchd._set_owner_only(release, 0o500)


def _worker_gate(snapshot: Any, *, canary_feature_id: str | None = None) -> Mapping[str, Any]:
    decision = decide_shadow(snapshot)
    if decision.global_rejections:
        raise OperatorError(
            "global worker/capacity gate failed: "
            + ",".join(value.code for value in decision.global_rejections)
        )
    evaluations = {value.id: value for value in decision.worker_evaluations}
    eligible = {
        worker_id for worker_id, value in evaluations.items()
        if value.eligible and not worker_id.startswith("legacy-worker:")
    }
    worker_by_id = {str(value.get("id")): value for value in snapshot.workers}
    reviewers = {
        worker_id for worker_id in eligible
        if "ASSURANCE" in worker_by_id[worker_id].get("approved_lanes", ())
        and (
            "review" in {str(value).lower() for value in worker_by_id[worker_id].get("capabilities", ())}
            or "independent-review" in {str(value).lower() for value in worker_by_id[worker_id].get("capabilities", ())}
        )
    }
    implementers = set(eligible)
    canary_ids = []
    if canary_feature_id is not None:
        packages = [
            value for value in snapshot.work_packages
            if value.get("feature_id") == canary_feature_id
        ]
        if len(packages) != 2:
            raise OperatorError("canary feature must contain exactly two packages")
        implementation = next((value for value in packages if value.get("kind") == "PARENT"), None)
        review = next((value for value in packages if value.get("kind") == "REVIEW"), None)
        if implementation is None or review is None:
            raise OperatorError("canary feature requires one PARENT and one REVIEW package")
        canary_ids = [str(implementation["id"]), str(review["id"])]
        unrelated = [
            str(value.get("id")) for value in snapshot.work_packages
            if value.get("status") in {"READY", "ACTIVE"}
            and value.get("feature_id") != canary_feature_id
        ]
        if unrelated:
            raise OperatorError("unrelated dispatchable packages present: " + ",".join(unrelated))
        implementation_pairs = {
            value.worker_id for value in decision.pair_evaluations
            if value.package_id == implementation["id"] and value.eligible
        }
        implementers &= implementation_pairs
        review_required = {str(value) for value in review.get("required_capabilities", ())}
        review_lane = review.get("lane")
        reviewers = {
            worker_id for worker_id in reviewers
            if review_lane in worker_by_id[worker_id].get("approved_lanes", ())
            and review_required <= set(worker_by_id[worker_id].get("capabilities", ()))
        }
    if not implementers:
        raise OperatorError("no eligible implementation worker")
    if not reviewers:
        raise OperatorError("no eligible independent reviewer")
    independent_pairs = sorted(
        (implementer, reviewer)
        for implementer in implementers for reviewer in reviewers
        if implementer != reviewer
    )
    if not independent_pairs:
        raise OperatorError("reviewer is not independent from every eligible implementer")
    return {
        "eligible_implementers": sorted(implementers),
        "eligible_reviewers": sorted(reviewers),
        "independent_pairs": [list(value) for value in independent_pairs],
        "canary_package_ids": canary_ids,
        "decision_id": decision.decision_id,
    }


def canary_worker_gate(
    snapshot: DispatchSnapshot,
    implementation: WorkPackage,
    review: WorkPackage,
    *,
    observed_at: str,
) -> Mapping[str, Any]:
    """Evaluate an unregistered canary against the current worker snapshot."""

    def package_record(package: WorkPackage) -> Mapping[str, Any]:
        return {
            "id": package.id,
            "feature_id": package.feature_id,
            "title": package.title,
            "category": package.category,
            "lane": package.lane.value,
            "required_capabilities": list(package.required_capabilities),
            "priority": package.priority,
            "acceptance_criteria": list(package.acceptance_criteria),
            "status": package.status.value,
            "kind": package.kind.value,
            "capacity_size": package.capacity_size.value,
            "capacity_risk": package.capacity_risk.value,
            "provider_diagnostics": dict(package.provider_diagnostics),
            "usage_consumption": dict(package.usage_consumption),
            "created_at": observed_at,
            "ready_at": observed_at,
        }

    candidate = DispatchSnapshot(
        revision=snapshot.revision,
        observed_at=snapshot.observed_at,
        active_parent_limit=snapshot.active_parent_limit,
        orchestra_reserve_percent=snapshot.orchestra_reserve_percent,
        features=snapshot.features,
        work_packages=(
            *snapshot.work_packages,
            package_record(implementation),
            package_record(review),
        ),
        dependencies=(
            *snapshot.dependencies,
            {"package_id": review.id, "dependency_id": implementation.id},
        ),
        workers=snapshot.workers,
        active_leases=snapshot.active_leases,
        usage_observations=snapshot.usage_observations,
    )
    return _worker_gate(candidate, canary_feature_id=implementation.feature_id)


def preflight(
    database: Path,
    config_path: Path,
    release: Path,
    preservation_path: Path,
    expected_commit: str,
    expected_revision: int,
    *,
    observed_at: str | None = None,
    allowed_modes: Sequence[str] = ("PAUSED",),
    require_config: bool = True,
    require_permissions_gate: bool = True,
    require_empty_ownership: bool = True,
    require_workers: bool = False,
    require_kill_switch: bool = True,
    canary_feature_id: str | None = None,
) -> Mapping[str, Any]:
    observed_at = observed_at or utc_now()
    current = status(database, observed_at=observed_at)
    database_checks = current["database_checks"]
    if database_checks["schema_version"] != str(CURRENT_SCHEMA_VERSION):
        raise OperatorError(
            "Registry schema version does not match the reviewed release: "
            f"expected {CURRENT_SCHEMA_VERSION}, got {database_checks['schema_version']}"
        )
    if database_checks["control_schema_version"] != str(CONTROL_SCHEMA_VERSION):
        raise OperatorError(
            "Registry control schema version does not match the reviewed release: "
            f"expected {CONTROL_SCHEMA_VERSION}, got {database_checks['control_schema_version']}"
        )
    control = current["control"]
    if control["revision"] != expected_revision:
        raise OperatorError(
            f"Registry revision mismatch: expected {expected_revision}, got {control['revision']}"
        )
    if control["dispatch_mode"] not in set(allowed_modes) or (
        require_kill_switch and not control["kill_switch_engaged"]
    ):
        raise OperatorError("Registry control is not in an allowed fail-closed mode")
    if require_empty_ownership and any(current["counts"][key] for key in (
        "active_leases", "active_attempts", "active_runtimes",
        "active_unbound_leases", "runtime_orphans",
    )):
        raise OperatorError("active or orphaned Registry ownership is present")
    registry = SQLiteRegistry(database)
    snapshot = registry.control_center_snapshot(observed_at=observed_at)
    preservation = verify_preservation(snapshot, preservation_path)
    release_evidence = verify_release(release, expected_commit)
    config = _load_object(config_path, "runner config")
    if require_config:
        _validate_config(config, database)
    permissions = (
        verify_permissions(database, config_path, release)
        if require_permissions_gate else {"gate": "deferred-to-prepare-dry-run"}
    )
    workers = (
        _worker_gate(
            registry.dispatch_snapshot(observed_at=observed_at),
            canary_feature_id=canary_feature_id,
        )
        if require_workers else {"gate": "not-requested"}
    )
    return {
        "kind": "threadline-factory-operator-preflight",
        "passed": True,
        "observed_at": observed_at,
        "registry": current,
        "preservation": preservation,
        "release": release_evidence,
        "config_sha256": _sha256_file(config_path),
        "permissions": permissions,
        "worker_gate": workers,
    }


def validate_telemetry_payload(value: Mapping[str, Any], observed_at: str) -> tuple[Worker, tuple[Mapping[str, Any], ...]]:
    sensitive = _sensitive_paths(value)
    if sensitive:
        raise OperatorError("telemetry contains secret-shaped fields: " + ",".join(sensitive))
    raw_worker = value.get("worker")
    raw_usage = value.get("usage_observations")
    if not isinstance(raw_worker, Mapping) or not isinstance(raw_usage, list):
        raise OperatorError("telemetry requires worker and usage_observations")
    try:
        lanes = tuple(Lane(str(item)) for item in raw_worker.get("approved_lanes", ()))
        worker = Worker(
            id=str(raw_worker["id"]),
            display_name=str(raw_worker["display_name"]),
            capabilities=tuple(str(item) for item in raw_worker.get("capabilities", ())),
            approved_lanes=lanes,
            role=str(raw_worker.get("role", "WORKER")),
            availability=str(raw_worker.get("availability", "IDLE")),
            provider_diagnostics=dict(raw_worker.get("provider_diagnostics") or {}),
            last_heartbeat_at=str(raw_worker["last_heartbeat_at"]),
            usage_state=str(raw_worker.get("usage_state", "UNKNOWN")),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise OperatorError("telemetry worker is invalid") from error
    if not worker.id or worker.id.startswith("legacy-worker:"):
        raise OperatorError("active telemetry requires a non-preservation worker id")
    if worker.role not in {"WORKER", "ORCHESTRA"} or worker.availability != "IDLE":
        raise OperatorError("telemetry worker must be an idle WORKER or ORCHESTRA")
    heartbeat_age = _age_seconds(worker.last_heartbeat_at, observed_at, "worker heartbeat")
    if heartbeat_age < 0 or heartbeat_age > HEARTBEAT_FRESH_SECONDS:
        raise OperatorError("worker heartbeat is future-dated or stale")
    diagnostics = worker.provider_diagnostics
    for key, expected in (
        ("service_state", "healthy"),
        ("authentication_state", "valid"),
        ("live_invocation_state", "succeeded"),
    ):
        if diagnostics.get(key) != expected:
            raise OperatorError(f"worker diagnostic {key} is not {expected}")
    if not isinstance(diagnostics.get("provider"), str) or not diagnostics["provider"]:
        raise OperatorError("worker provider diagnostic is missing")
    mode = diagnostics.get("capacity_mode")
    scopes = diagnostics.get("capacity_scopes")
    if not isinstance(scopes, list) or not scopes or len(scopes) != len(set(scopes)):
        raise OperatorError("worker capacity scopes are invalid")
    if mode == "provider_signal":
        if scopes != ["provider_signal"] or worker.role == "ORCHESTRA":
            raise OperatorError("provider-signal capacity is invalid for this worker")
    elif mode != "percentage" or "provider_signal" in scopes:
        raise OperatorError("percentage capacity scopes are invalid")
    if len(raw_usage) != len(scopes):
        raise OperatorError("telemetry must contain exactly one observation per capacity scope")
    observations = []
    by_scope = {}
    rank = {"NORMAL": 0, "CAUTION": 1, "CHECKPOINT": 2, "HARD_STOP": 3}
    highest = "NORMAL"
    for raw in raw_usage:
        if not isinstance(raw, Mapping) or raw.get("worker_id") != worker.id:
            raise OperatorError("usage observation worker mismatch")
        item = dict(raw)
        scope = item.get("capacity_scope")
        if scope not in scopes or scope in by_scope:
            raise OperatorError("usage observation scope mismatch or duplicate")
        age = _age_seconds(item.get("observed_at"), observed_at, "usage observed_at")
        if age < 0 or age > USAGE_FRESH_SECONDS:
            raise OperatorError("usage observation is future-dated or stale")
        if item.get("capacity_mode") != mode:
            raise OperatorError("usage observation capacity mode mismatch")
        if mode == "provider_signal":
            if not (
                item.get("service_state") == "healthy"
                and item.get("authentication_state") == "valid"
                and item.get("live_invocation_state") == "succeeded"
                and item.get("limit_signal") == "NONE"
                and item.get("state") == "NORMAL"
            ):
                raise OperatorError("provider-signal observation is not healthy")
        else:
            consumed = item.get("consumed_percent")
            if isinstance(consumed, bool) or not isinstance(consumed, (int, float)) or not 0 <= float(consumed) <= 100:
                raise OperatorError("percentage observation is invalid")
            expected_state = (
                "HARD_STOP" if consumed >= 98 else
                "CHECKPOINT" if consumed >= 95 else
                "CAUTION" if consumed >= 90 else "NORMAL"
            )
            if item.get("state") != expected_state:
                raise OperatorError("percentage observation state does not match thresholds")
            highest = max((highest, expected_state), key=lambda value: rank[value])
            if worker.role == "ORCHESTRA" and 100 - float(consumed) < 20:
                raise OperatorError("Orchestra capacity reserve is below 20 percent")
        by_scope[scope] = item
        observations.append(item)
    expected_worker_state = "NORMAL" if mode == "provider_signal" else highest
    if worker.usage_state != expected_worker_state:
        raise OperatorError("worker usage_state does not match its observations")
    return worker, tuple(observations)


def _package(value: Mapping[str, Any], *, queue_contract: Mapping[str, Any]) -> WorkPackage:
    diagnostics = dict(value.get("provider_diagnostics") or {})
    diagnostics["queue_contract_sha256"] = queue_contract_digest(dict(queue_contract))
    try:
        return WorkPackage(
            id=str(value["id"]),
            feature_id=str(value["feature_id"]),
            title=str(value["title"]),
            category=str(value["category"]),
            lane=Lane(str(value["lane"])),
            required_capabilities=tuple(str(item) for item in value.get("required_capabilities", ())),
            priority=int(value["priority"]),
            acceptance_criteria=tuple(str(item) for item in value.get("acceptance_criteria", ())),
            status=TaskStatus.READY,
            kind=PackageKind(str(value["kind"])),
            capacity_size=PackageCapacitySize(str(value["capacity_size"])),
            capacity_risk=PackageCapacityRisk(str(value["capacity_risk"])),
            dependency_ids=tuple(str(item) for item in value.get("dependency_ids", ())),
            provider_diagnostics=diagnostics,
        )
    except (KeyError, TypeError, ValueError) as error:
        raise OperatorError("canary package is invalid") from error


def parse_canary_spec(value: Mapping[str, Any]) -> tuple[Feature, WorkPackage, WorkPackage]:
    sensitive = _sensitive_paths(value)
    if sensitive:
        raise OperatorError("canary spec contains secret-shaped fields: " + ",".join(sensitive))
    raw_feature = value.get("feature")
    raw_impl = value.get("implementation")
    raw_review = value.get("review")
    if not all(isinstance(item, Mapping) for item in (raw_feature, raw_impl, raw_review)):
        raise OperatorError("canary spec requires feature, implementation, and review objects")
    try:
        feature = Feature(
            id=str(raw_feature["id"]),
            title=str(raw_feature["title"]),
            priority=int(raw_feature["priority"]),
            status=TaskStatus.READY,
            description=str(raw_feature.get("description", "")),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise OperatorError("canary feature is invalid") from error
    impl_contract = raw_impl.get("queue_contract")
    review_contract = raw_review.get("queue_contract")
    if not isinstance(impl_contract, Mapping) or not isinstance(review_contract, Mapping):
        raise OperatorError("each canary package requires a normalized queue_contract")
    implementation = _package(raw_impl, queue_contract=impl_contract)
    review = _package(raw_review, queue_contract=review_contract)
    for package, contract in ((implementation, impl_contract), (review, review_contract)):
        expected = {
            "task": package.id,
            "lane": package.lane.value,
            "kind": package.kind.value,
            "capacity_size": package.capacity_size.value,
            "capacity_risk": package.capacity_risk.value,
        }
        mismatched = [key for key, expected_value in expected.items() if contract.get(key) != expected_value]
        if mismatched:
            raise OperatorError("queue contract/package mismatch: " + ",".join(mismatched))
        paths = contract.get("paths")
        if not isinstance(paths, list) or not paths or any(
            not isinstance(path, str) or path.startswith(("/", ".")) or ".." in Path(path).parts
            for path in paths
        ):
            raise OperatorError("canary queue contract requires safe relative paths")
        if not isinstance(contract.get("instructions"), str) or not contract["instructions"].strip():
            raise OperatorError("canary queue contract instructions are required")
        if not re.fullmatch(r"TASK-\d+", package.id):
            raise OperatorError("canary package ids must match the runner TASK-number contract")
    implementation_issue = int(implementation.id.removeprefix("TASK-"))
    if impl_contract.get("depends_on") != []:
        raise OperatorError("implementation queue contract must have no issue dependencies")
    if review_contract.get("depends_on") != [implementation_issue]:
        raise OperatorError("review queue contract must depend on the implementation issue")
    return feature, implementation, review


def _atomic_write_config(config_path: Path, value: Mapping[str, Any], state: Path) -> Path:
    backup_dir = state / "config-backups"
    backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    backup_dir.chmod(0o700)
    backup = backup_dir / f"config-{time.time_ns()}.json"
    shutil.copy2(config_path, backup)
    backup.chmod(0o600)
    content = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")
    descriptor, temporary_name = tempfile.mkstemp(prefix=config_path.name + ".", dir=config_path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        temporary.replace(config_path)
        directory_fd = os.open(config_path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)
    return backup


def _validate_plan(plan: Sequence[tuple[str, Mapping[str, Any]]], release: Path, *, live: bool) -> None:
    release = release.resolve()
    for label, data in plan:
        arguments = data.get("ProgramArguments", ())
        if label != install_launchd.DASHBOARD_LABEL:
            if ("--dry-run" in arguments) == live:
                raise OperatorError("service plan live/dry-run mismatch")
        scripts = [str(value) for value in arguments if str(value).endswith(".py")]
        if not scripts or any(
            release not in Path(value).resolve().parents for value in scripts
        ):
            raise OperatorError(f"service plan is not pinned to release: {label}")


def _verify_installed_dry_run(
    plan: Sequence[tuple[str, Mapping[str, Any]]],
    *,
    home: Path | None,
    run: Any,
    uid: int,
) -> None:
    failures = []
    for label, expected in plan:
        destination = install_launchd.label_path(label, home)
        if not destination.is_file():
            failures.append(f"{label}:definition-missing")
            continue
        try:
            installed = plistlib.loads(destination.read_bytes())
        except (OSError, plistlib.InvalidFileException):
            failures.append(f"{label}:definition-invalid")
            continue
        if installed != expected:
            failures.append(f"{label}:definition-mismatch")
        if not install_launchd.is_loaded(label, uid, run):
            failures.append(f"{label}:not-loaded")
    if failures:
        raise OperatorError("installed dry-run service gate failed: " + ",".join(failures))


def prepare_dry_run(
    database: Path,
    config_path: Path,
    release: Path,
    preservation_path: Path,
    expected_commit: str,
    expected_revision: int,
    migration: Mapping[str, Any],
    *,
    mode: str = "lanes",
    dashboard_port: int = 8787,
    home: Path | None = None,
    run=None,
    uid: int | None = None,
) -> Mapping[str, Any]:
    preflight(
        database, config_path, release, preservation_path, expected_commit,
        expected_revision, allowed_modes=("PAUSED", "LIVE"), require_config=False,
        require_permissions_gate=False, require_empty_ownership=False,
        require_kill_switch=False,
    )
    initial_control = SQLiteRegistry(database).dispatch_control()
    if (
        initial_control["dispatch_mode"] == "PAUSED"
        and not initial_control["kill_switch_engaged"]
    ):
        raise OperatorError("PAUSED dry-run preparation requires the kill switch")
    source_config = _load_object(config_path, "runner config")
    migrated = migrate_config(source_config, database, migration)
    root = release / "scripts" / "runner"
    plan = install_launchd.service_plan(
        migrated, config_path.resolve(), root, mode, False, dashboard_port
    )
    _validate_plan(plan, release, live=False)
    state = Path(migrated["state"])
    backup_holder: dict[str, Path] = {}

    def commit_prepared_configuration() -> None:
        backup_holder["config"] = _atomic_write_config(config_path, migrated, state)
        install_launchd.prepare_private_storage(config_path, migrated, plan)
        harden_paths(database, config_path, release)
        verify_release(release, expected_commit)

    control = RunnerRegistryControl(database)
    kwargs = {}
    if run is not None:
        kwargs["run"] = run
    result = install_launchd.pause_to_dry_run(
        plan,
        mode=mode,
        registry_control=control,
        state=state,
        home=home,
        uid=uid,
        after_reconcile=commit_prepared_configuration,
        **kwargs,
    )
    final = status(database)
    if final["control"]["dispatch_mode"] != "PAUSED" or not final["control"]["kill_switch_engaged"]:
        raise OperatorError("dry-run preparation did not finish PAUSED")
    if any(final["counts"][key] for key in (
        "active_leases", "active_attempts", "active_runtimes", "active_unbound_leases", "runtime_orphans"
    )):
        raise OperatorError("dry-run preparation left active ownership")
    return {
        "kind": "threadline-factory-prepare-dry-run",
        "passed": True,
        "expected_revision": expected_revision,
        "final_revision": final["control"]["revision"],
        "config_sha256": _sha256_file(config_path),
        "config_backup": str(backup_holder["config"]),
        "plist_backup_directory": str(result["backup_dir"]),
        "services": sorted(result["destinations"]),
        "control": final["control"],
    }


def enable_live(
    database: Path,
    config_path: Path,
    release: Path,
    preservation_path: Path,
    expected_commit: str,
    expected_revision: int,
    canary_feature_id: str,
    *,
    mode: str = "lanes",
    dashboard_port: int = 8787,
    home: Path | None = None,
    run=None,
    uid: int | None = None,
) -> Mapping[str, Any]:
    evidence = preflight(
        database, config_path, release, preservation_path, expected_commit,
        expected_revision, require_workers=True, canary_feature_id=canary_feature_id,
    )
    config = _load_object(config_path, "runner config")
    root = release / "scripts" / "runner"
    dry_plan = install_launchd.service_plan(config, config_path.resolve(), root, mode, False, dashboard_port)
    live_plan = install_launchd.service_plan(config, config_path.resolve(), root, mode, True, dashboard_port)
    _validate_plan(dry_plan, release, live=False)
    _validate_plan(live_plan, release, live=True)
    kwargs = {}
    if run is not None:
        kwargs["run"] = run
    effective_run = run if run is not None else install_launchd.subprocess.run
    effective_uid = os.getuid() if uid is None else uid
    _verify_installed_dry_run(
        dry_plan, home=home, run=effective_run, uid=effective_uid
    )
    install_launchd.install(
        live_plan, mode=mode, replace_mode=False, replace_current=True,
        state=Path(config["state"]), home=home, uid=uid, **kwargs,
    )
    registry = SQLiteRegistry(database)
    try:
        evidence = preflight(
            database, config_path, release, preservation_path, expected_commit,
            expected_revision, require_workers=True,
            canary_feature_id=canary_feature_id,
        )
        revision = registry.set_dispatch_control(
            expected_revision=expected_revision,
            expected_mode="PAUSED",
            new_mode="LIVE",
            kill_switch_engaged=False,
            changed_at=utc_now(),
            reason=f"owner-approved bounded canary {canary_feature_id}",
        )
    except Exception:
        # A stale revision after service promotion is handled as an emergency
        # stop. Live definitions cannot claim while the Registry is PAUSED;
        # if another actor changed it, this kill closes that race first.
        install_launchd.pause_to_dry_run(
            dry_plan,
            mode=mode,
            registry_control=RunnerRegistryControl(database),
            state=Path(config["state"]),
            home=home,
            uid=uid,
            **kwargs,
        )
        raise
    return {
        "kind": "threadline-factory-enable-live",
        "passed": True,
        "previous_revision": expected_revision,
        "revision": revision,
        "canary_feature_id": canary_feature_id,
        "services": sorted(label for label, _ in live_plan),
        "worker_gate": evidence["worker_gate"],
    }


def stop(database: Path, reason: str) -> Mapping[str, Any]:
    if not database.is_absolute() or not database.is_file():
        raise OperatorError("--database must be an existing absolute Registry path")
    revision = RunnerRegistryControl(database).engage_stop(reason)
    return {
        "kind": "threadline-factory-stop",
        "passed": True,
        "revision": revision,
        "control": dict(SQLiteRegistry(database).dispatch_control()),
    }


def reconcile(database: Path, *, expected_revision: int) -> Mapping[str, Any]:
    control = SQLiteRegistry(database).dispatch_control()
    if control["revision"] != expected_revision:
        raise OperatorError("Registry revision mismatch before reconciliation")
    result = RunnerRegistryControl(database).reconcile_stopping_runtimes()
    if result["unresolved"]:
        raise OperatorError("runtime reconciliation is incomplete")
    registry = SQLiteRegistry(database)
    if registry.active_attempt_runtimes() or registry.active_unbound_leases() or registry.runtime_orphans():
        raise OperatorError("runtime reconciliation post-read is not empty")
    return {
        "kind": "threadline-factory-reconcile",
        "passed": True,
        "expected_revision": expected_revision,
        "resolved": list(result["resolved"]),
        "control": dict(registry.dispatch_control()),
    }


def return_paused(database: Path, *, expected_revision: int, reason: str) -> Mapping[str, Any]:
    registry = SQLiteRegistry(database)
    control = registry.dispatch_control()
    if control["revision"] != expected_revision:
        raise OperatorError("Registry revision mismatch before return-paused")
    if control["dispatch_mode"] not in {"STOPPING", "RECOVERY_REQUIRED"} or not control["kill_switch_engaged"]:
        raise OperatorError("return-paused requires STOPPING or RECOVERY_REQUIRED")
    if registry.active_attempt_runtimes() or registry.active_unbound_leases() or registry.runtime_orphans():
        raise OperatorError("return-paused requires empty ownership")
    revision = registry.set_dispatch_control(
        expected_revision=expected_revision,
        expected_mode=str(control["dispatch_mode"]),
        new_mode="PAUSED",
        kill_switch_engaged=True,
        changed_at=utc_now(),
        reason=reason,
    )
    return {
        "kind": "threadline-factory-return-paused",
        "passed": True,
        "revision": revision,
        "control": dict(registry.dispatch_control()),
    }
