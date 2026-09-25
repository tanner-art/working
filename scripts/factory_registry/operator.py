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
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from scripts.runner import install_launchd
from scripts.runner.registry_control import RunnerRegistryControl, queue_contract_digest

from .models import (
    DispatchSnapshot,
    Evidence,
    Feature,
    Lane,
    PackageCapacityRisk,
    PackageCapacitySize,
    PackageKind,
    ReviewOutcome,
    ReviewOutcomeState,
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
APPROVED_PRESERVATION_SHA256 = (
    "7d47f980d66bf84676cb6d0c24a7eeab0efe40bbe2451d7b27dfd1d6ed94fce6"
)
APPROVED_PRESERVATION_COUNTS = {
    "worktrees": 33,
    "dirty_worktrees": 8,
    "unmerged_branches": 7,
    "unexplained_records": 0,
    "unreleased_live_leases": 0,
}
REQUIRED_AGENT_IDS = frozenset({"codex-a", "codex-b", "claude"})
PRESERVATION_EVIDENCE_NAME = "preservation_snapshot_2026-09-24.json"
V3_TO_V4_STATEMENTS = (
    """CREATE TABLE review_outcomes (
        id TEXT PRIMARY KEY,
        review_package_id TEXT NOT NULL UNIQUE REFERENCES work_packages(id),
        target_package_id TEXT NOT NULL REFERENCES work_packages(id),
        implementer_worker_id TEXT NOT NULL REFERENCES workers(id),
        reviewer_worker_id TEXT NOT NULL REFERENCES workers(id),
        requested_at TEXT NOT NULL,
        decided_at TEXT NOT NULL,
        state TEXT NOT NULL CHECK(state IN ('CHANGES_REQUESTED', 'APPROVED')),
        findings_json TEXT NOT NULL,
        changes_requested_json TEXT NOT NULL,
        approval_evidence_ids_json TEXT NOT NULL,
        CHECK(implementer_worker_id <> reviewer_worker_id),
        CHECK(decided_at >= requested_at)
    )""",
    """CREATE TRIGGER review_outcomes_are_append_only_update
       BEFORE UPDATE ON review_outcomes BEGIN
           SELECT RAISE(ABORT, 'REVIEW_OUTCOMES_APPEND_ONLY');
       END""",
    """CREATE TRIGGER review_outcomes_are_append_only_delete
       BEFORE DELETE ON review_outcomes BEGIN
           SELECT RAISE(ABORT, 'REVIEW_OUTCOMES_APPEND_ONLY');
       END""",
)
HEARTBEAT_FRESH_SECONDS = 180
USAGE_FRESH_SECONDS = 900
SENSITIVE_KEY_PARTS = ("password", "secret", "token", "credential", "api_key", "apikey")
REQUIRED_RELEASE_FILES = frozenset({
    "scripts/factory_registry/__init__.py",
    "scripts/factory_registry/claude_telemetry.py",
    "scripts/factory_registry/claude_telemetry_cli.py",
    "scripts/factory_registry/control_center_projection.py",
    "scripts/factory_registry/control_center_server.py",
    "scripts/factory_registry/controlled_restart.py",
    "scripts/factory_registry/live_observation.py",
    "scripts/factory_registry/live_observation_cli.py",
    "scripts/factory_registry/models.py",
    "scripts/factory_registry/operator.py",
    "scripts/factory_registry/operator_cli.py",
    "scripts/factory_registry/preservation_import.py",
    "scripts/factory_registry/repository.py",
    "scripts/factory_registry/schema.sql",
    "scripts/factory_registry/shadow_dispatch.py",
    "scripts/factory_registry/sqlite_registry.py",
    "scripts/runner/claude_keychain.py",
    "scripts/runner/factory_dashboard.html",
    "scripts/runner/factory_dashboard.py",
    "scripts/runner/factory_status.py",
    "scripts/runner/github.py",
    "scripts/runner/install_launchd.py",
    "scripts/runner/provider_barrier.py",
    "scripts/runner/queue_snapshot.py",
    "scripts/runner/registry_control.py",
    "scripts/runner/review_queue.py",
    "scripts/runner/runner.py",
    "scripts/runner/usage_policy.py",
})


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
    if release.is_symlink() or not release.is_dir():
        raise OperatorError("release must be an existing non-symlink directory")
    release = release.resolve()
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
        try:
            target_mode = target.lstat().st_mode
        except OSError as error:
            raise OperatorError(f"release manifest target invalid: {relative}") from error
        if not stat.S_ISREG(target_mode):
            raise OperatorError(f"release manifest target invalid: {relative}")
        actual = hashlib.sha1(target.read_bytes()).hexdigest()  # nosec - release manifest format
        if actual != digest:
            raise OperatorError(f"release manifest mismatch: {relative}")
        checked.append(relative)
    if len(checked) != len(set(checked)):
        raise OperatorError("release manifest contains duplicate paths")
    manifested = set(checked)
    release_files = set()
    for target in release.rglob("*"):
        target_mode = target.lstat().st_mode
        if stat.S_ISLNK(target_mode):
            raise OperatorError(f"release contains a symlink: {target}")
        if stat.S_ISREG(target_mode):
            relative = target.relative_to(release).as_posix()
            if relative != "MANIFEST.sha1":
                release_files.add(relative)
        elif not stat.S_ISDIR(target_mode):
            raise OperatorError(f"release contains a special file: {target}")
    unmanifested = sorted(release_files - manifested)
    nonexistent = sorted(manifested - release_files)
    if unmanifested or nonexistent:
        raise OperatorError(
            "release manifest is incomplete: "
            + json.dumps(
                {"unmanifested": unmanifested, "nonexistent": nonexistent},
                separators=(",", ":"),
                sort_keys=True,
            )
        )
    # Complete coverage cannot reveal a runtime dependency omitted from both
    # the release and its manifest, so keep the reviewed closure explicit.
    missing = sorted((REQUIRED_RELEASE_FILES | {"COMMIT"}) - manifested)
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
    metadata = preservation_path.lstat()
    if preservation_path.is_symlink() or metadata.st_uid != os.getuid():
        raise OperatorError("preservation snapshot must be an owner-controlled regular file")
    if stat.S_IMODE(metadata.st_mode) != 0o600:
        raise OperatorError("preservation snapshot mode must be 0600")
    digest = _sha256_file(preservation_path)
    if digest != APPROVED_PRESERVATION_SHA256:
        raise OperatorError("preservation SHA-256 is not the approved cutover snapshot")
    imports = tuple(registry_snapshot.preservation_imports)
    if not imports:
        raise OperatorError("Registry has no preservation import")
    matching = [value for value in imports if value.get("source_sha256") == digest]
    if len(matching) != 1:
        raise OperatorError("preservation SHA-256 does not match exactly one Registry import")
    source = _load_object(preservation_path, "preservation snapshot")
    import_id = matching[0].get("id")
    if not isinstance(import_id, str) or not import_id:
        raise OperatorError("matching preservation import has no identity")
    reconciliation = dict(matching[0].get("reconciliation") or {})
    tasks = source.get("open_task_mapping", ())
    worktrees = source.get("worktrees", ())
    branches = source.get("unmerged_local_branches", ())
    services = source.get("services") or {}
    heartbeats = services.get("heartbeats", {}) if isinstance(services, Mapping) else {}
    expected = {
        "expected_worktrees": len(worktrees),
        "expected_branches": len(branches),
        "expected_tasks": len(tasks),
        "expected_workers": len(heartbeats),
        "unexplained_records": 0,
    }
    approved_counts = {
        "worktrees": expected["expected_worktrees"],
        "dirty_worktrees": source.get("dirty_worktree_count"),
        "unmerged_branches": expected["expected_branches"],
        "unexplained_records": reconciliation.get("unexplained_records"),
        "unreleased_live_leases": sum(
            1 for lease in registry_snapshot.leases if lease.get("released_at") is None
        ),
    }
    if approved_counts != APPROVED_PRESERVATION_COUNTS:
        raise OperatorError(
            "preservation snapshot does not match approved cutover counts: "
            + json.dumps(
                {"expected": APPROVED_PRESERVATION_COUNTS, "actual": approved_counts},
                sort_keys=True,
            )
        )
    mismatches = {
        key: {"expected": value, "registry": reconciliation.get(key)}
        for key, value in expected.items()
        if reconciliation.get(key) != value
    }
    for kind in ("tasks", "workers", "worktrees", "branches"):
        expected_key = f"expected_{kind}"
        imported_key = f"imported_{kind}"
        if reconciliation.get(imported_key) != expected[expected_key]:
            mismatches[imported_key] = {
                "expected": expected[expected_key],
                "registry": reconciliation.get(imported_key),
            }

    expected_artifacts = {
        ("WORKTREE", str(item["worktree"])): {
            "dirty": bool(item.get("dirty")),
            "metadata": dict(item),
        }
        for item in worktrees
    }
    expected_artifacts.update({
        ("BRANCH", str(branch)): {
            "dirty": False,
            "metadata": {"identity": str(branch), "branch": str(branch)},
        }
        for branch in branches
    })
    actual_artifacts = {
        (str(item.get("kind")), str(item.get("external_identity"))): {
            "dirty": bool(item.get("dirty")),
            "metadata": dict(item.get("metadata") or {}),
        }
        for item in registry_snapshot.preserved_artifacts
        if item.get("import_id") == import_id
    }
    if actual_artifacts != expected_artifacts:
        mismatches["actual_preserved_artifacts"] = {
            "expected": sorted(f"{kind}:{identity}" for kind, identity in expected_artifacts),
            "registry": sorted(f"{kind}:{identity}" for kind, identity in actual_artifacts),
        }

    expected_packages = {}
    for item in tasks:
        status_text = str(item.get("status", "ON DECK")).upper()
        status = (
            "VERIFY_REVIEW" if "VERIFY" in status_text or "REVIEW" in status_text
            else "BLOCKED" if any(
                marker in status_text for marker in ("BLOCKED", "FAILED", "ACTIVE")
            )
            else "DONE" if "DONE" in status_text
            else "READY" if "READY" in status_text
            else "ON_DECK"
        )
        task_id = str(item["task"])
        expected_packages[task_id] = {
            "id": task_id,
            "feature_id": "FACTORY-LIVE-STATE-PRESERVATION",
            "title": str(item.get("title") or task_id),
            "category": "LEGACY_IMPORT",
            "lane": None,
            "status": status,
            "branch": item.get("branch"),
            "pr_url": (
                f"https://github.com/tanner-art/working/pull/{item['pr']}"
                if item.get("pr") else None
            ),
            "source_system": "github_issue",
            "source_ref": str(item.get("issue")),
            "provider_diagnostics": {
                "legacy_worker": item.get("worker"),
                "legacy_worker_hint": item.get("worker_hint"),
                "legacy_issue": item.get("issue"),
                "legacy_status": status_text,
                "preservation_import_id": import_id,
            },
        }
    actual_packages = {
        str(item.get("id")): {
            key: item.get(key)
            for key in (
                "id", "feature_id", "title", "category", "lane", "status",
                "branch", "pr_url", "source_system", "source_ref",
                "provider_diagnostics",
            )
        }
        for item in registry_snapshot.work_packages
        if (item.get("provider_diagnostics") or {}).get("preservation_import_id")
        == import_id
    }
    if actual_packages != expected_packages:
        mismatches["actual_preserved_packages"] = {
            "expected": expected_packages,
            "registry": actual_packages,
        }

    expected_workers = {
        f"legacy-worker:{name}": {
            "id": f"legacy-worker:{name}",
            "display_name": f"Preserved {name}",
            "role": "WORKER",
            "availability": "PRESERVED",
            "capabilities": [],
            "approved_lanes": [],
            "provider_diagnostics": {"legacy_worker": name},
            "usage_state": "UNKNOWN",
        }
        for name in heartbeats
    }
    actual_workers = {
        str(item.get("id")): {
            key: item.get(key)
            for key in (
                "id", "display_name", "role", "availability", "capabilities",
                "approved_lanes", "provider_diagnostics", "usage_state",
            )
        }
        for item in registry_snapshot.workers
        if str(item.get("id", "")).startswith("legacy-worker:")
        or item.get("availability") == "PRESERVED"
    }
    if actual_workers != expected_workers:
        mismatches["actual_preserved_workers"] = {
            "expected": expected_workers,
            "registry": actual_workers,
        }
    if source.get("dirty_worktree_count") != sum(
        1 for value in worktrees if value.get("dirty")
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
        "unreleased_live_leases": 0,
        "approved_counts": dict(APPROVED_PRESERVATION_COUNTS),
    }


def store_preservation_evidence(
    database: Path,
    source: Path,
    release: Path,
    expected_commit: str,
    expected_revision: int,
    *,
    observed_at: str | None = None,
) -> Mapping[str, Any]:
    """Install the one approved preservation snapshot into owner-only storage."""
    if not database.is_absolute() or not source.is_absolute() or not source.is_file():
        raise OperatorError("database and preservation source must be existing absolute paths")
    verify_release(release, expected_commit)
    permission_failures = _release_permission_failures(release)
    if permission_failures:
        raise OperatorError(
            "private/immutable release gate failed: " + ",".join(permission_failures)
        )
    if (
        _path_mode(database.parent) != 0o700
        or _path_mode(database) != 0o600
        or database.is_symlink()
        or database.stat().st_uid != os.getuid()
    ):
        raise OperatorError("preservation install requires an owner-controlled 0600 database")
    observed_at = observed_at or utc_now()
    current = status(database, observed_at=observed_at)
    if current["database_checks"]["control_schema_version"] != str(CONTROL_SCHEMA_VERSION):
        raise OperatorError("preservation install requires reviewed control schema 1")
    control = current["control"]
    if control["revision"] != expected_revision:
        raise OperatorError(
            f"Registry revision mismatch: expected {expected_revision}, got {control['revision']}"
        )
    if control["dispatch_mode"] != "PAUSED" or not control["kill_switch_engaged"]:
        raise OperatorError("preservation install requires PAUSED with the kill switch engaged")
    source_metadata = source.lstat()
    if (
        source.is_symlink()
        or not stat.S_ISREG(source_metadata.st_mode)
        or source_metadata.st_uid != os.getuid()
        or stat.S_IMODE(source_metadata.st_mode) != 0o600
    ):
        raise OperatorError("preservation source must be an owner-controlled 0600 regular file")
    digest = _sha256_file(source)
    if digest != APPROVED_PRESERVATION_SHA256:
        raise OperatorError("preservation SHA-256 is not the approved cutover snapshot")
    evidence_directory = database.parent / "evidence"
    evidence_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    install_launchd._set_owner_only(evidence_directory, 0o700)
    destination = evidence_directory / PRESERVATION_EVIDENCE_NAME
    if destination.exists() or destination.is_symlink():
        destination_metadata = destination.lstat()
        if (
            destination.is_symlink()
            or not stat.S_ISREG(destination_metadata.st_mode)
            or _sha256_file(destination) != digest
        ):
            raise OperatorError("existing preservation evidence does not match the approved snapshot")
    elif source.resolve() != destination.resolve():
        temporary = evidence_directory / f".{destination.name}.{os.getpid()}.tmp"
        try:
            with source.open("rb") as input_file, temporary.open("xb") as output_file:
                os.fchmod(output_file.fileno(), 0o600)
                shutil.copyfileobj(input_file, output_file)
                output_file.flush()
                os.fsync(output_file.fileno())
            if _sha256_file(temporary) != digest:
                raise OperatorError("preservation evidence copy hash mismatch")
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
    install_launchd._set_owner_only(destination, 0o600)
    installed_metadata = destination.lstat()
    if (
        installed_metadata.st_uid != os.getuid()
        or stat.S_IMODE(installed_metadata.st_mode) != 0o600
        or _sha256_file(destination) != digest
    ):
        raise OperatorError("installed preservation evidence verification failed")
    reconciliation = verify_preservation(
        SQLiteRegistry(database).control_center_snapshot(observed_at=observed_at),
        destination,
    )
    return {
        "kind": "threadline-factory-preservation-evidence",
        "passed": True,
        "source": str(source),
        "path": str(destination),
        "sha256": digest,
        "directory_mode": "0700",
        "file_mode": "0600",
        "revision": expected_revision,
        "counts": dict(APPROVED_PRESERVATION_COUNTS),
        "reconciliation": reconciliation,
    }


def _database_checks(
    database: Path, *, immutable: bool = False, require_wal: bool = True
) -> Mapping[str, Any]:
    suffix = "?mode=ro&immutable=1" if immutable else "?mode=ro"
    uri = f"{database.resolve().as_uri()}{suffix}"
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
    if require_wal and journal_mode != "wal":
        raise OperatorError(f"Registry journal mode must be WAL, got {journal_mode}")
    return {
        "integrity": "ok",
        "foreign_key_violations": 0,
        "journal_mode": journal_mode,
        "schema_version": metadata.get("schema_version"),
        "control_schema_version": metadata.get("control_schema_version"),
        "revision": metadata.get("revision"),
    }


def _status_without_control_metadata(
    database: Path, checks: Mapping[str, Any], observed_at: str
) -> Mapping[str, Any]:
    """Report a legacy v3 database without pretending its control plane is usable."""
    uri = f"{database.resolve().as_uri()}?mode=ro"
    try:
        with sqlite3.connect(uri, uri=True) as connection:
            connection.row_factory = sqlite3.Row
            tables = {
                row[0] for row in connection.execute(
                    "SELECT name FROM sqlite_schema WHERE type='table'"
                )
            }

            def count(table: str, where: str = "") -> int | None:
                if table not in tables:
                    return None
                return int(connection.execute(
                    f"SELECT count(*) FROM {table} {where}"
                ).fetchone()[0])

            raw_control = None
            if "factory_control" in tables:
                row = connection.execute(
                    "SELECT dispatch_mode, kill_switch_engaged, changed_at, reason "
                    "FROM factory_control WHERE singleton=1"
                ).fetchone()
                if row is not None:
                    raw_control = dict(row)
                    raw_control["kill_switch_engaged"] = bool(
                        raw_control["kill_switch_engaged"]
                    )
    except sqlite3.Error as error:
        raise OperatorError(f"Registry v3 observation failed: {error}") from error
    return {
        "kind": "threadline-factory-operator-status",
        "observed_at": observed_at,
        "database": str(database),
        "database_checks": checks,
        "control": {
            "available": False,
            "revision": int(checks["revision"]) if str(checks.get("revision", "")).isdigit() else None,
            "raw": raw_control,
            "reason": "CONTROL_SCHEMA_METADATA_MISSING",
        },
        "counts": {
            "features": count("features"),
            "packages": count("work_packages"),
            "workers": count("workers"),
            "evidence": count("evidence"),
            "review_outcomes": count("review_outcomes") or 0,
            "preservation_imports": count("preservation_imports"),
            "active_leases": count("leases", "WHERE released_at IS NULL"),
            "active_attempts": count("attempts", "WHERE ended_at IS NULL"),
            "active_runtimes": count(
                "attempt_runtime_ownership", "WHERE released_at IS NULL"
            ),
            "active_unbound_leases": None,
            "runtime_orphans": None,
        },
        "workers": [],
    }


def status(database: Path, *, observed_at: str | None = None) -> Mapping[str, Any]:
    if not database.is_absolute() or not database.is_file():
        raise OperatorError("--database must be an existing absolute Registry path")
    observed_at = observed_at or utc_now()
    checks = _database_checks(database)
    if (
        checks["schema_version"] == "3"
        and checks["control_schema_version"] != str(CONTROL_SCHEMA_VERSION)
    ):
        return _status_without_control_metadata(database, checks, observed_at)
    registry = SQLiteRegistry(database)
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
            "evidence": len(snapshot.evidence),
            "review_outcomes": len(snapshot.review_outcomes),
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


def _require_installed_preservation(database: Path, preservation_path: Path) -> None:
    expected = database.parent / "evidence" / PRESERVATION_EVIDENCE_NAME
    if preservation_path.resolve() != expected.resolve():
        raise OperatorError(
            "preservation snapshot must use the reviewed Registry evidence path"
        )


def _total_ownership_counts(
    database: Path, *, immutable: bool = False
) -> Mapping[str, int]:
    suffix = "?mode=ro&immutable=1" if immutable else "?mode=ro"
    uri = f"{database.resolve().as_uri()}{suffix}"
    try:
        with sqlite3.connect(uri, uri=True) as connection:
            return {
                "leases": int(connection.execute("SELECT count(*) FROM leases").fetchone()[0]),
                "attempts": int(connection.execute("SELECT count(*) FROM attempts").fetchone()[0]),
                "runtimes": int(connection.execute(
                    "SELECT count(*) FROM attempt_runtime_ownership"
                ).fetchone()[0]),
            }
    except sqlite3.Error as error:
        raise OperatorError(f"Registry ownership check failed: {error}") from error


def _require_migration_state(
    current: Mapping[str, Any], *, expected_schema: int, expected_revision: int
) -> None:
    checks = current["database_checks"]
    if checks["schema_version"] != str(expected_schema):
        raise OperatorError(
            f"Registry migration requires schema {expected_schema}, got "
            f"{checks['schema_version']}"
        )
    if checks["control_schema_version"] != str(CONTROL_SCHEMA_VERSION):
        raise OperatorError("Registry migration requires reviewed control schema 1")
    control = current["control"]
    if control["revision"] != expected_revision:
        raise OperatorError(
            f"Registry revision mismatch: expected {expected_revision}, got {control['revision']}"
        )
    if control["dispatch_mode"] != "PAUSED" or not control["kill_switch_engaged"]:
        raise OperatorError("Registry migration requires PAUSED with the kill switch engaged")
    if any(current["counts"][key] for key in (
        "active_leases", "active_attempts", "active_runtimes",
        "active_unbound_leases", "runtime_orphans",
    )):
        raise OperatorError("Registry migration requires empty active ownership")


def _create_verified_registry_backup(
    database: Path,
    backup: Path,
    preservation_path: Path,
    *,
    expected_revision: int,
    observed_at: str,
) -> Mapping[str, Any]:
    evidence_directory = database.parent / "evidence"
    if (
        not backup.is_absolute()
        or backup.exists()
        or backup.parent.resolve() != evidence_directory.resolve()
    ):
        raise OperatorError(
            "Registry backup must be a new absolute file in Registry evidence storage"
        )
    backup.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    install_launchd._set_owner_only(backup.parent, 0o700)
    source_uri = f"{database.resolve().as_uri()}?mode=ro"
    try:
        with sqlite3.connect(source_uri, uri=True) as source, sqlite3.connect(backup) as target:
            source.backup(target)
            target.execute("PRAGMA journal_mode=DELETE")
    except sqlite3.Error as error:
        backup.unlink(missing_ok=True)
        raise OperatorError(f"cannot create Registry v3 backup: {error}") from error
    install_launchd._set_owner_only(backup, 0o600)
    checks = _database_checks(backup, immutable=True, require_wal=False)
    if (
        checks["schema_version"] != "3"
        or checks["control_schema_version"] != str(CONTROL_SCHEMA_VERSION)
    ):
        raise OperatorError("Registry backup schema metadata mismatch")
    backup_control = SQLiteRegistry(backup).dispatch_control()
    if (
        backup_control["revision"] != expected_revision
        or backup_control["dispatch_mode"] != "PAUSED"
        or not backup_control["kill_switch_engaged"]
    ):
        raise OperatorError("Registry backup control mismatch")
    if _total_ownership_counts(backup, immutable=True) != {
        "leases": 0, "attempts": 0, "runtimes": 0,
    }:
        raise OperatorError("Registry v3 backup contains ownership history")
    preservation = verify_preservation(
        SQLiteRegistry(backup).control_center_snapshot(observed_at=observed_at),
        preservation_path,
    )
    return {
        "path": str(backup),
        "sha256": _sha256_file(backup),
        "integrity": checks["integrity"],
        "schema_version": checks["schema_version"],
        "control_schema_version": checks["control_schema_version"],
        "revision": expected_revision,
        "mode": "0600",
        "preservation_sha256": preservation["sha256"],
    }


def _require_backup_hash(backup: Path, expected_sha256: str) -> str:
    if (
        not isinstance(expected_sha256, str)
        or len(expected_sha256) != 64
        or any(character not in "0123456789abcdef" for character in expected_sha256)
    ):
        raise OperatorError("expected Registry backup SHA-256 is invalid")
    actual = _sha256_file(backup)
    if actual != expected_sha256:
        raise OperatorError(
            "Registry backup SHA-256 mismatch: "
            f"expected {expected_sha256}, got {actual}"
        )
    return actual


def _restore_database_from_backup(
    database: Path, backup: Path, expected_backup_sha256: str
) -> None:
    _require_backup_hash(backup, expected_backup_sha256)
    source_uri = f"{backup.resolve().as_uri()}?mode=ro"
    try:
        with sqlite3.connect(source_uri, uri=True) as source, sqlite3.connect(database) as target:
            _require_backup_hash(backup, expected_backup_sha256)
            source.backup(target)
            target.execute("PRAGMA journal_mode=WAL")
    except sqlite3.Error as error:
        raise OperatorError(f"cannot restore Registry backup: {error}") from error


def _verify_migrated_v4(
    database: Path,
    preservation_path: Path,
    *,
    expected_revision: int,
    control_before: Mapping[str, Any],
    observed_at: str,
) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    final = status(database, observed_at=observed_at)
    _require_migration_state(final, expected_schema=4, expected_revision=expected_revision)
    if final["control"] != control_before:
        raise OperatorError("Registry migration changed dispatch control")
    if final["counts"]["review_outcomes"] != 0:
        raise OperatorError("Registry migration did not create an empty review outcome store")
    if _total_ownership_counts(database) != {"leases": 0, "attempts": 0, "runtimes": 0}:
        raise OperatorError("Registry migration created ownership records")
    snapshot = SQLiteRegistry(database).control_center_snapshot(observed_at=observed_at)
    return final, verify_preservation(snapshot, preservation_path)


def _verify_restored_v3(
    database: Path,
    preservation_path: Path,
    *,
    expected_revision: int,
    observed_at: str,
) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    restored = status(database, observed_at=observed_at)
    _require_migration_state(restored, expected_schema=3, expected_revision=expected_revision)
    if _total_ownership_counts(database) != {"leases": 0, "attempts": 0, "runtimes": 0}:
        raise OperatorError("restored Registry contains ownership records")
    uri = f"{database.resolve().as_uri()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        review_table = connection.execute(
            "SELECT 1 FROM sqlite_schema WHERE type='table' AND name='review_outcomes'"
        ).fetchone()
    if review_table is not None:
        raise OperatorError("restored Registry still contains review_outcomes")
    snapshot = SQLiteRegistry(database).control_center_snapshot(observed_at=observed_at)
    return restored, verify_preservation(snapshot, preservation_path)


def migrate_registry_v3_to_v4(
    database: Path,
    release: Path,
    preservation_path: Path,
    expected_commit: str,
    expected_revision: int,
    *,
    backup_path: Path | None = None,
    observed_at: str | None = None,
) -> Mapping[str, Any]:
    """Perform the reviewed v3-to-v4 schema change with backup and rollback."""
    observed_at = observed_at or utc_now()
    verify_release(release, expected_commit)
    permission_failures = _release_permission_failures(release)
    if permission_failures:
        raise OperatorError(
            "private/immutable release gate failed: " + ",".join(permission_failures)
        )
    if (
        _path_mode(database.parent) != 0o700
        or _path_mode(database) != 0o600
        or database.is_symlink()
        or database.stat().st_uid != os.getuid()
    ):
        raise OperatorError("Registry migration requires an owner-controlled 0600 database")
    _require_installed_preservation(database, preservation_path)
    current = status(database, observed_at=observed_at)
    _require_migration_state(current, expected_schema=3, expected_revision=expected_revision)
    if _total_ownership_counts(database) != {"leases": 0, "attempts": 0, "runtimes": 0}:
        raise OperatorError("Registry migration requires zero leases, attempts, and runtimes")
    registry = SQLiteRegistry(database)
    before_snapshot = registry.control_center_snapshot(observed_at=observed_at)
    preservation = verify_preservation(before_snapshot, preservation_path)
    control_before = dict(current["control"])
    backup_path = backup_path or (
        database.parent
        / "evidence"
        / f"registry-v3-revision-{expected_revision}-{time.time_ns()}.sqlite3"
    )
    backup_evidence = _create_verified_registry_backup(
        database,
        backup_path,
        preservation_path,
        expected_revision=expected_revision,
        observed_at=observed_at,
    )
    with sqlite3.connect(database, timeout=10, isolation_level=None) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=10000")
        connection.execute("BEGIN IMMEDIATE")
        try:
            metadata = dict(connection.execute(
                "SELECT key, value FROM registry_metadata"
            ))
            if metadata.get("schema_version") != "3":
                raise OperatorError("Registry schema changed before migration")
            if metadata.get("control_schema_version") != str(CONTROL_SCHEMA_VERSION):
                raise OperatorError("Registry control schema changed before migration")
            if metadata.get("revision") != str(expected_revision):
                raise OperatorError("Registry revision changed before migration")
            control = connection.execute(
                "SELECT dispatch_mode, kill_switch_engaged, changed_at, reason "
                "FROM factory_control WHERE singleton=1"
            ).fetchone()
            if control is None or control[0] != "PAUSED" or control[1] != 1:
                raise OperatorError("Registry control changed before migration")
            if any(connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                   for table in ("leases", "attempts", "attempt_runtime_ownership")):
                raise OperatorError("Registry ownership appeared before migration")
            for statement in V3_TO_V4_STATEMENTS:
                connection.execute(statement)
            connection.execute(
                "UPDATE registry_metadata SET value='4' "
                "WHERE key='schema_version' AND value='3'"
            )
            if connection.execute("SELECT changes()").fetchone()[0] != 1:
                raise OperatorError("Registry schema version compare-and-swap failed")
            foreign_keys = tuple(connection.execute("PRAGMA foreign_key_check"))
            if foreign_keys:
                raise OperatorError("Registry migration introduced foreign-key violations")
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    try:
        final, preservation_after = _verify_migrated_v4(
            database,
            preservation_path,
            expected_revision=expected_revision,
            control_before=control_before,
            observed_at=observed_at,
        )
    except Exception as original_error:
        expected_backup_sha256 = str(backup_evidence["sha256"])
        try:
            _restore_database_from_backup(
                database, backup_path, expected_backup_sha256
            )
            restored, restored_preservation = _verify_restored_v3(
                database,
                preservation_path,
                expected_revision=expected_revision,
                observed_at=observed_at,
            )
            restore_disposition = {
                "attempted": True,
                "succeeded": True,
                "schema_version": restored["database_checks"]["schema_version"],
                "revision": restored["control"]["revision"],
                "backup_sha256": expected_backup_sha256,
                "preservation_sha256": restored_preservation["sha256"],
            }
        except Exception as restore_error:
            restore_disposition = {
                "attempted": True,
                "succeeded": False,
                "backup_sha256": expected_backup_sha256,
                "error": f"{type(restore_error).__name__}: {restore_error}",
            }
            raise OperatorError(
                "post-commit Registry verification failed; "
                f"original={type(original_error).__name__}: {original_error}; "
                f"restore={json.dumps(restore_disposition, separators=(',', ':'), sort_keys=True)}"
            ) from original_error
        raise OperatorError(
            "post-commit Registry verification failed; "
            f"original={type(original_error).__name__}: {original_error}; "
            f"restore={json.dumps(restore_disposition, separators=(',', ':'), sort_keys=True)}"
        ) from original_error
    return {
        "kind": "threadline-factory-registry-migration",
        "passed": True,
        "source_schema": 3,
        "schema_version": 4,
        "control": final["control"],
        "backup": backup_evidence,
        "preservation_before": preservation,
        "preservation_after": preservation_after,
        "review_outcomes": 0,
    }


def restore_registry_v3_backup(
    database: Path,
    backup_path: Path,
    release: Path,
    preservation_path: Path,
    expected_commit: str,
    expected_backup_sha256: str,
    expected_revision: int,
    *,
    observed_at: str | None = None,
) -> Mapping[str, Any]:
    """Restore a reviewed v3 backup after a v4 cutover rollback decision."""
    observed_at = observed_at or utc_now()
    verify_release(release, expected_commit)
    permission_failures = _release_permission_failures(release)
    if permission_failures:
        raise OperatorError(
            "private/immutable release gate failed: " + ",".join(permission_failures)
        )
    if (
        _path_mode(database.parent) != 0o700
        or _path_mode(database) != 0o600
        or database.is_symlink()
        or database.stat().st_uid != os.getuid()
    ):
        raise OperatorError("Registry restore requires an owner-controlled 0600 database")
    _require_installed_preservation(database, preservation_path)
    if backup_path.parent.resolve() != (database.parent / "evidence").resolve():
        raise OperatorError("Registry backup must come from Registry evidence storage")
    backup_metadata = backup_path.lstat()
    if (
        backup_path.is_symlink()
        or backup_metadata.st_uid != os.getuid()
        or stat.S_IMODE(backup_metadata.st_mode) != 0o600
    ):
        raise OperatorError("Registry backup must be an owner-controlled 0600 file")
    _require_backup_hash(backup_path, expected_backup_sha256)
    backup_checks = _database_checks(
        backup_path, immutable=True, require_wal=False
    )
    if (
        backup_checks["schema_version"] != "3"
        or backup_checks["control_schema_version"] != str(CONTROL_SCHEMA_VERSION)
    ):
        raise OperatorError("Registry backup schema metadata mismatch")
    backup_control = SQLiteRegistry(backup_path).dispatch_control()
    if (
        backup_control["revision"] != expected_revision
        or backup_control["dispatch_mode"] != "PAUSED"
        or not backup_control["kill_switch_engaged"]
    ):
        raise OperatorError("Registry backup control mismatch")
    if _total_ownership_counts(backup_path, immutable=True) != {
        "leases": 0, "attempts": 0, "runtimes": 0,
    }:
        raise OperatorError("Registry backup contains ownership records")
    verify_preservation(
        SQLiteRegistry(backup_path).control_center_snapshot(observed_at=observed_at),
        preservation_path,
    )
    current = status(database, observed_at=observed_at)
    _require_migration_state(current, expected_schema=4, expected_revision=expected_revision)
    if current["counts"]["review_outcomes"] != 0:
        raise OperatorError("cannot restore v3 after review outcomes have been recorded")
    if _total_ownership_counts(database) != {"leases": 0, "attempts": 0, "runtimes": 0}:
        raise OperatorError("cannot restore v3 while ownership records exist")
    _restore_database_from_backup(
        database, backup_path, expected_backup_sha256
    )
    restored, restored_preservation = _verify_restored_v3(
        database,
        preservation_path,
        expected_revision=expected_revision,
        observed_at=observed_at,
    )
    return {
        "kind": "threadline-factory-registry-restore",
        "passed": True,
        "schema_version": 3,
        "revision": expected_revision,
        "backup": str(backup_path),
        "backup_sha256": expected_backup_sha256,
        "preservation_sha256": restored_preservation["sha256"],
        "control": restored["control"],
    }


def _validate_config(config: Mapping[str, Any], database: Path, release: Path) -> None:
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
    release = release.resolve()
    expected_github = release / "scripts" / "runner" / "github.py"
    expected_claude_wrapper = release / "scripts" / "runner" / "claude_keychain.py"
    if config.get("gh") != str(expected_github):
        raise OperatorError("config gh must name github.py in the selected immutable release")
    agents = config.get("agents")
    if not isinstance(agents, Mapping) or set(agents) != REQUIRED_AGENT_IDS:
        raise OperatorError("config agents must be exactly codex-a, codex-b, and claude")
    for worker_id, value in agents.items():
        if not isinstance(value, Mapping):
            raise OperatorError(f"config agent {worker_id} must be an object")
        if value.get("slots") != 1:
            raise OperatorError(f"config agent {worker_id} must have exactly one slot")
        mode = value.get("capacity_mode")
        scopes = value.get("capacity_scopes")
        if mode == "provider_signal":
            valid = scopes == ["provider_signal"]
        else:
            valid = mode == "percentage" and isinstance(scopes, list) and bool(scopes) and "provider_signal" not in scopes
        if not valid or len(scopes) != len(set(scopes)):
            raise OperatorError(f"config agent {worker_id} has invalid capacity mode/scopes")
        commands = ("command", "fallback_command") if "fallback_command" in value else ("command",)
        for command_field in commands:
            command = value.get(command_field)
            if not isinstance(command, list) or not command or not all(
                isinstance(token, str) and token for token in command
            ):
                raise OperatorError(f"config agent {worker_id} has an invalid {command_field}")
            forbidden_roots = tuple(
                Path(str(config[field])).resolve()
                for field in ("repo", "state", "worktrees")
            ) + (release, Path(tempfile.gettempdir()).resolve())
            if worker_id.startswith("codex-"):
                executable = Path(command[0])
                resolved_executable = executable.resolve()
                if (
                    not executable.is_absolute()
                    or executable.name != "codex"
                    or any(
                        resolved_executable == root or root in resolved_executable.parents
                        for root in forbidden_roots
                    )
                ):
                    raise OperatorError(f"config agent {worker_id} must invoke codex")
            else:
                if len(command) < 4:
                    raise OperatorError("Claude command must use the reviewed Keychain wrapper")
                python = Path(command[0])
                wrapper = Path(command[1])
                claude = Path(command[3])
                if (
                    not python.is_absolute()
                    or python.resolve() != Path(sys.executable).resolve()
                    or wrapper != expected_claude_wrapper
                    or command[2] != "exec"
                    or not claude.is_absolute()
                    or claude.name != "claude"
                    or any(
                        claude.resolve() == root or root in claude.resolve().parents
                        for root in forbidden_roots
                    )
                ):
                    raise OperatorError("Claude command must use claude_keychain.py from the selected release")
    sensitive = _sensitive_paths(config)
    if sensitive:
        raise OperatorError("config contains secret-shaped fields: " + ",".join(sensitive))


def migrate_config(
    config: Mapping[str, Any], database: Path, release: Path, migration: Mapping[str, Any]
) -> dict[str, Any]:
    result = json.loads(json.dumps(config))
    agents = result.get("agents")
    migration_agents = migration.get("agents")
    if not isinstance(agents, dict) or not isinstance(migration_agents, Mapping):
        raise OperatorError("config migration requires an agents mapping")
    if set(agents) != REQUIRED_AGENT_IDS:
        raise OperatorError("config migration requires exactly codex-a, codex-b, and claude")
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
        agents[worker_id]["slots"] = 1
    release = release.resolve()
    result["gh"] = str(release / "scripts" / "runner" / "github.py")
    claude = agents["claude"]
    wrapper = str(release / "scripts" / "runner" / "claude_keychain.py")
    for field in ("command", "fallback_command"):
        if field not in claude:
            continue
        command = claude[field]
        if not isinstance(command, list) or not command:
            raise OperatorError(f"config agent claude has an invalid {field}")
        if len(command) >= 4 and Path(str(command[1])).name == "claude_keychain.py" and command[2] == "exec":
            command = [command[0], wrapper, "exec", *command[3:]]
        elif Path(str(command[0])).name == "claude":
            command = [sys.executable, wrapper, "exec", *command]
        else:
            raise OperatorError("Claude migration source command must invoke claude directly or through claude_keychain.py")
        claude[field] = command
    result["registry_database"] = str(database)
    result["registry_lease_seconds"] = 2100
    result["registry_renew_interval_seconds"] = 30
    result["usage_policy"] = dict(EXPECTED_USAGE_POLICY)
    _validate_config(result, database, release)
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
    failures.extend(_release_permission_failures(release))
    if failures:
        raise OperatorError("private/immutable permission gate failed: " + ",".join(failures))
    return {
        "registry_directory_mode": "0700",
        "database_mode": "0600",
        "config_mode": "0600",
        "release_write_bits": 0,
    }


def _release_permission_failures(release: Path) -> list[str]:
    failures = []
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
    return failures


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
    _require_installed_preservation(database, preservation_path)
    preservation = verify_preservation(snapshot, preservation_path)
    release_evidence = verify_release(release, expected_commit)
    config = _load_object(config_path, "runner config")
    if require_config:
        _validate_config(config, database, release)
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


def parse_review_outcome_spec(
    value: Mapping[str, Any],
) -> tuple[Evidence, ReviewOutcome]:
    sensitive = _sensitive_paths(value)
    if sensitive:
        raise OperatorError(
            "review outcome contains secret-shaped fields: " + ",".join(sensitive)
        )
    raw_evidence = value.get("evidence")
    raw_outcome = value.get("outcome")
    if not isinstance(raw_evidence, Mapping) or not isinstance(raw_outcome, Mapping):
        raise OperatorError("review outcome spec requires evidence and outcome objects")
    try:
        evidence = Evidence(
            id=str(raw_evidence["id"]),
            package_id=str(raw_evidence["package_id"]),
            kind=str(raw_evidence["kind"]),
            uri=(str(raw_evidence["uri"]) if raw_evidence.get("uri") else None),
            summary=str(raw_evidence["summary"]),
            recorded_at=str(raw_evidence["recorded_at"]),
            metadata=dict(raw_evidence.get("metadata") or {}),
        )
        outcome = ReviewOutcome(
            id=str(raw_outcome["id"]),
            review_package_id=str(raw_outcome["review_package_id"]),
            target_package_id=str(raw_outcome["target_package_id"]),
            implementer_worker_id=str(raw_outcome["implementer_worker_id"]),
            reviewer_worker_id=str(raw_outcome["reviewer_worker_id"]),
            requested_at=str(raw_outcome["requested_at"]),
            decided_at=str(raw_outcome["decided_at"]),
            state=ReviewOutcomeState(str(raw_outcome["state"])),
            findings=tuple(str(item) for item in raw_outcome.get("findings", ())),
            changes_requested=tuple(
                str(item) for item in raw_outcome.get("changes_requested", ())
            ),
            approval_evidence_ids=tuple(
                str(item) for item in raw_outcome.get("approval_evidence_ids", ())
            ),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise OperatorError("review outcome spec is invalid") from error
    attempt_id = evidence.metadata.get("attempt_id")
    if (
        not evidence.id
        or evidence.package_id != outcome.review_package_id
        or evidence.kind.lower() != "review"
        or not evidence.summary
        or not isinstance(attempt_id, str)
        or not attempt_id
    ):
        raise OperatorError("review evidence must bind the review package and attempt")
    requested_at = _parse_time(outcome.requested_at, "review requested_at")
    recorded_at = _parse_time(evidence.recorded_at, "review evidence recorded_at")
    decided_at = _parse_time(outcome.decided_at, "review decided_at")
    if not requested_at <= recorded_at <= decided_at:
        raise OperatorError("review evidence timestamp is outside the review interval")
    if outcome.state is ReviewOutcomeState.APPROVED:
        if outcome.approval_evidence_ids != (evidence.id,):
            raise OperatorError("approval must name exactly the bound review evidence")
    elif outcome.approval_evidence_ids:
        raise OperatorError("changes-requested outcome cannot name approval evidence")
    return evidence, outcome


def record_review_decision(
    database: Path,
    config_path: Path,
    release: Path,
    preservation_path: Path,
    expected_commit: str,
    expected_revision: int,
    spec: Mapping[str, Any],
) -> Mapping[str, Any]:
    evidence, outcome = parse_review_outcome_spec(spec)
    preflight(
        database,
        config_path,
        release,
        preservation_path,
        expected_commit,
        expected_revision,
    )
    revision = SQLiteRegistry(database).record_review_outcome(
        outcome,
        evidence=evidence,
        expected_revision=expected_revision,
    )
    return {
        "kind": "threadline-factory-record-review-outcome",
        "passed": True,
        "review_outcome_id": outcome.id,
        "review_package_id": outcome.review_package_id,
        "target_package_id": outcome.target_package_id,
        "reviewer_worker_id": outcome.reviewer_worker_id,
        "reviewer_attempt_id": evidence.metadata["attempt_id"],
        "evidence_id": evidence.id,
        "state": outcome.state.value,
        "previous_revision": expected_revision,
        "revision": revision,
    }


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
    migrated = migrate_config(source_config, database, release, migration)
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
    install_launchd.install_operator_plan(
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
