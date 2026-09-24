"""SQLite/WAL adapter for the backend-neutral Factory registry contract.

SQLite is the migration control-plane implementation. No caller should import
SQLite types or issue SQL directly; a Postgres/Supabase adapter can implement
the same ``Registry`` protocol later.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

from .models import DispatchSnapshot, Evidence, Feature, Lease, TaskStatus, Worker, WorkPackage
from .repository import RegistryConflict, RegistryNotFound


def _json(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def _utc_now() -> str:
    return _normalize_timestamp(datetime.now(timezone.utc).isoformat())


def _normalize_timestamp(value: str) -> str:
    """Return one lexically sortable UTC representation or reject the value."""
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as error:
        raise RegistryConflict("INVALID_TIMESTAMP", value) from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise RegistryConflict("INVALID_TIMESTAMP", "timezone required")
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _legacy_heartbeat_time(value: Any) -> str | None:
    if value is None:
        return None
    try:
        if isinstance(value, (int, float)):
            return _normalize_timestamp(datetime.fromtimestamp(value, timezone.utc).isoformat())
        return _normalize_timestamp(str(value))
    except (RegistryConflict, ValueError, OverflowError):
        return None


class SQLiteRegistry:
    """Transactional registry adapter with authoritative lease invariants."""

    def __init__(self, database: str | Path) -> None:
        self.database = Path(database)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        try:
            yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        self.database.parent.mkdir(parents=True, exist_ok=True)
        schema = Path(__file__).with_name("schema.sql").read_text()
        with self._connection() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(schema)

    def journal_mode(self) -> str:
        with self._connection() as connection:
            return str(connection.execute("PRAGMA journal_mode").fetchone()[0]).lower()

    @staticmethod
    def _bump_revision(connection: sqlite3.Connection) -> int:
        connection.execute(
            "UPDATE registry_metadata SET value=CAST(value AS INTEGER)+1 WHERE key='revision'"
        )
        return int(connection.execute(
            "SELECT value FROM registry_metadata WHERE key='revision'"
        ).fetchone()[0])

    def register_feature(self, feature: Feature) -> None:
        now = _utc_now()
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute(
                    """INSERT INTO features
                       (id, title, description, priority, status, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (feature.id, feature.title, feature.description, feature.priority,
                     feature.status.value, now, now),
                )
                self._bump_revision(connection)
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def register_work_package(self, package: WorkPackage) -> None:
        if package.status == TaskStatus.ACTIVE:
            raise RegistryConflict("ACTIVE_REQUIRES_LEASE")
        now = _utc_now()
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                self._insert_package(connection, package, now)
                for dependency_id in package.dependency_ids:
                    connection.execute(
                        "INSERT INTO task_dependencies(package_id, dependency_id) VALUES (?, ?)",
                        (package.id, dependency_id),
                    )
                self._bump_revision(connection)
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    @staticmethod
    def _insert_package(
        connection: sqlite3.Connection,
        package: WorkPackage,
        now: str,
        *,
        source_system: str | None = None,
        source_ref: str | None = None,
    ) -> None:
        if package.status == TaskStatus.ACTIVE:
            raise RegistryConflict("ACTIVE_REQUIRES_LEASE")
        started_at = _normalize_timestamp(package.started_at) if package.started_at else None
        heartbeat_at = (
            _normalize_timestamp(package.last_heartbeat_at)
            if package.last_heartbeat_at else None
        )
        connection.execute(
            """INSERT INTO work_packages
                (id, feature_id, title, category, lane, kind,
                 required_capabilities_json, priority, acceptance_criteria_json,
                 status, provider_diagnostics_json, branch, pr_url, ready_at, started_at,
                 last_heartbeat_at, runtime_seconds, usage_consumption_json,
                 failure_code, failure_detail, source_system, source_ref,
                 created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                package.id, package.feature_id, package.title, package.category,
                package.lane.value if package.lane else None, package.kind.value,
                _json(package.required_capabilities), package.priority,
                _json(package.acceptance_criteria), package.status.value,
                _json(package.provider_diagnostics), package.branch, package.pr_url,
                now if package.status == TaskStatus.READY else None,
                started_at, heartbeat_at, package.runtime_seconds,
                _json(package.usage_consumption),
                package.failure_code.value if package.failure_code else None,
                package.failure_detail, source_system, source_ref, now, now,
            ),
        )

    def register_worker(self, worker: Worker) -> None:
        now = _utc_now()
        heartbeat_at = (
            _normalize_timestamp(worker.last_heartbeat_at)
            if worker.last_heartbeat_at else None
        )
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                if connection.execute(
                    "SELECT 1 FROM leases WHERE worker_id=? AND released_at IS NULL",
                    (worker.id,),
                ).fetchone():
                    raise RegistryConflict("WORKER_HAS_ACTIVE_LEASE")
                connection.execute(
                    """INSERT INTO workers
                   (id, display_name, role, availability, capabilities_json,
                    approved_lanes_json, provider_diagnostics_json,
                    last_heartbeat_at, usage_state, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET
                    display_name=excluded.display_name,
                    role=excluded.role,
                    availability=excluded.availability,
                    capabilities_json=excluded.capabilities_json,
                    approved_lanes_json=excluded.approved_lanes_json,
                    provider_diagnostics_json=excluded.provider_diagnostics_json,
                    last_heartbeat_at=excluded.last_heartbeat_at,
                    usage_state=excluded.usage_state,
                    updated_at=excluded.updated_at""",
                    (
                    worker.id, worker.display_name, worker.role, worker.availability,
                    _json(worker.capabilities), _json([lane.value for lane in worker.approved_lanes]),
                    _json(worker.provider_diagnostics), heartbeat_at,
                    worker.usage_state, now, now,
                    ),
                )
                self._bump_revision(connection)
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    @staticmethod
    def _expire_leases(connection: sqlite3.Connection, now: str) -> int:
        expired = connection.execute(
            "SELECT id, package_id, worker_id FROM leases "
            "WHERE released_at IS NULL AND expires_at <= ?",
            (now,),
        ).fetchall()
        for lease in expired:
            connection.execute(
                "UPDATE leases SET released_at=?, release_reason='LEASE_EXPIRED' WHERE id=?",
                (now, lease["id"]),
            )
            connection.execute(
                "UPDATE workers SET availability='IDLE', updated_at=? WHERE id=?",
                (now, lease["worker_id"]),
            )
            connection.execute(
                "UPDATE work_packages SET status='BLOCKED', failure_code='HEARTBEAT_MISSED', "
                "failure_detail='Lease expired before release', updated_at=? WHERE id=? AND status='ACTIVE'",
                (now, lease["package_id"]),
            )
            failure_id = str(uuid.uuid4())
            connection.execute(
                """INSERT INTO failure_observations
                   (id, package_id, worker_id, attempt_id, code, detail, observed_at, metadata_json)
                   VALUES (?, ?, ?, NULL, 'HEARTBEAT_MISSED', ?, ?, ?)""",
                (
                    failure_id, lease["package_id"], lease["worker_id"],
                    "Lease expired before release", now, _json({"lease_id": lease["id"]}),
                ),
            )
            SQLiteRegistry._insert_event(
                connection, "LEASE_EXPIRED", now, lease["package_id"], lease["worker_id"], None,
                {"lease_id": lease["id"], "failure_id": failure_id},
            )
        return len(expired)

    def expire_leases(self, *, observed_at: str) -> int:
        observed_at = _normalize_timestamp(observed_at)
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                count = self._expire_leases(connection, observed_at)
                if count:
                    self._bump_revision(connection)
                connection.commit()
                return count
            except Exception:
                connection.rollback()
                raise

    def acquire_lease(
        self,
        package_id: str,
        worker_id: str,
        *,
        acquired_at: str,
        expires_at: str,
    ) -> Lease:
        acquired_at = _normalize_timestamp(acquired_at)
        expires_at = _normalize_timestamp(expires_at)
        if expires_at <= acquired_at:
            raise RegistryConflict("INVALID_LEASE_EXPIRY")
        self.expire_leases(observed_at=acquired_at)
        lease_id = str(uuid.uuid4())
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                package = connection.execute(
                    "SELECT * FROM work_packages WHERE id=?", (package_id,)
                ).fetchone()
                worker = connection.execute(
                    "SELECT * FROM workers WHERE id=?", (worker_id,)
                ).fetchone()
                if package is None:
                    raise RegistryNotFound(f"work package {package_id}")
                if worker is None:
                    raise RegistryNotFound(f"worker {worker_id}")
                if worker["role"] != "WORKER":
                    raise RegistryConflict("ORCHESTRA_CANNOT_CLAIM")
                if package["status"] != TaskStatus.READY.value:
                    raise RegistryConflict("PACKAGE_NOT_READY", package["status"])
                if package["lane"] is None:
                    raise RegistryConflict("PACKAGE_LANE_UNASSIGNED")
                if worker["availability"] != "IDLE":
                    raise RegistryConflict("WORKER_NOT_IDLE", worker["availability"])
                approved_lanes = set(json.loads(worker["approved_lanes_json"]))
                if package["lane"] not in approved_lanes:
                    raise RegistryConflict("LANE_NOT_APPROVED", package["lane"])
                capabilities = set(json.loads(worker["capabilities_json"]))
                required = set(json.loads(package["required_capabilities_json"]))
                missing = sorted(required - capabilities)
                if missing:
                    raise RegistryConflict("CAPABILITY_MISMATCH", ",".join(missing))
                incomplete = connection.execute(
                    """SELECT dependency_id FROM task_dependencies AS dependency
                       JOIN work_packages AS required ON required.id=dependency.dependency_id
                       WHERE dependency.package_id=? AND required.status <> 'DONE'""",
                    (package_id,),
                ).fetchall()
                if incomplete:
                    raise RegistryConflict(
                        "DEPENDENCY_BLOCKED", ",".join(row["dependency_id"] for row in incomplete)
                    )
                try:
                    connection.execute(
                        """INSERT INTO leases
                           (id, package_id, worker_id, acquired_at, expires_at)
                           VALUES (?, ?, ?, ?, ?)""",
                        (lease_id, package_id, worker_id, acquired_at, expires_at),
                    )
                except sqlite3.IntegrityError as error:
                    code = str(error)
                    if "ACTIVE_PARENT_LIMIT" in code:
                        raise RegistryConflict("ACTIVE_PARENT_LIMIT") from error
                    raise RegistryConflict("LEASE_CONFLICT", code) from error
                connection.execute(
                    "UPDATE work_packages SET status='ACTIVE', started_at=COALESCE(started_at, ?), "
                    "last_heartbeat_at=?, updated_at=? WHERE id=?",
                    (acquired_at, acquired_at, acquired_at, package_id),
                )
                connection.execute(
                    "UPDATE workers SET availability='BUSY', last_heartbeat_at=?, updated_at=? WHERE id=?",
                    (acquired_at, acquired_at, worker_id),
                )
                self._insert_event(
                    connection, "LEASE_ACQUIRED", acquired_at, package_id, worker_id, None,
                    {"lease_id": lease_id, "expires_at": expires_at},
                )
                self._bump_revision(connection)
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return Lease(lease_id, package_id, worker_id, acquired_at, expires_at)

    def renew_lease(self, lease_id: str, *, now: str, expires_at: str) -> Lease:
        now = _normalize_timestamp(now)
        expires_at = _normalize_timestamp(expires_at)
        self.expire_leases(observed_at=now)
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(
                    """SELECT lease.*, package.last_heartbeat_at AS package_heartbeat_at
                       FROM leases AS lease
                       JOIN work_packages AS package ON package.id=lease.package_id
                       WHERE lease.id=?""",
                    (lease_id,),
                ).fetchone()
                if row is None:
                    raise RegistryNotFound(f"lease {lease_id}")
                if row["released_at"] is not None or row["expires_at"] <= now:
                    raise RegistryConflict("LEASE_NOT_ACTIVE")
                if now < row["acquired_at"] or (
                    row["package_heartbeat_at"] and now < row["package_heartbeat_at"]
                ):
                    raise RegistryConflict("INVALID_LEASE_CHRONOLOGY")
                if expires_at <= now:
                    raise RegistryConflict("INVALID_LEASE_EXPIRY")
                connection.execute("UPDATE leases SET expires_at=? WHERE id=?", (expires_at, lease_id))
                connection.execute(
                    "UPDATE work_packages SET last_heartbeat_at=?, updated_at=? WHERE id=?",
                    (now, now, row["package_id"]),
                )
                connection.execute(
                    "UPDATE workers SET last_heartbeat_at=?, updated_at=? WHERE id=?",
                    (now, now, row["worker_id"]),
                )
                self._insert_event(
                    connection, "LEASE_RENEWED", now, row["package_id"], row["worker_id"], None,
                    {"lease_id": lease_id, "expires_at": expires_at},
                )
                self._bump_revision(connection)
                connection.commit()
                return Lease(
                    lease_id, row["package_id"], row["worker_id"], row["acquired_at"], expires_at
                )
            except Exception:
                connection.rollback()
                raise

    def release_lease(
        self,
        lease_id: str,
        *,
        released_at: str,
        reason: str,
        next_status: TaskStatus,
    ) -> None:
        if next_status == TaskStatus.ACTIVE:
            raise RegistryConflict("INVALID_RELEASE_STATUS")
        released_at = _normalize_timestamp(released_at)
        self.expire_leases(observed_at=released_at)
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(
                    """SELECT lease.*, package.last_heartbeat_at AS package_heartbeat_at
                       FROM leases AS lease
                       JOIN work_packages AS package ON package.id=lease.package_id
                       WHERE lease.id=?""",
                    (lease_id,),
                ).fetchone()
                if row is None:
                    raise RegistryNotFound(f"lease {lease_id}")
                if row["released_at"] is not None:
                    raise RegistryConflict("LEASE_NOT_ACTIVE")
                if released_at < row["acquired_at"] or (
                    row["package_heartbeat_at"] and released_at < row["package_heartbeat_at"]
                ):
                    raise RegistryConflict("INVALID_LEASE_CHRONOLOGY")
                transitioned = connection.execute(
                    """UPDATE work_packages
                       SET status=?, ready_at=CASE WHEN ?='READY' THEN ? ELSE ready_at END,
                           updated_at=?
                       WHERE id=? AND status='ACTIVE'""",
                    (
                        next_status.value, next_status.value, released_at, released_at,
                        row["package_id"],
                    ),
                ).rowcount
                if transitioned != 1:
                    raise RegistryConflict("PACKAGE_NOT_ACTIVE")
                connection.execute(
                    "UPDATE leases SET released_at=?, release_reason=? WHERE id=?",
                    (released_at, reason, lease_id),
                )
                connection.execute(
                    "UPDATE workers SET availability='IDLE', updated_at=? WHERE id=?",
                    (released_at, row["worker_id"]),
                )
                self._insert_event(
                    connection, "LEASE_RELEASED", released_at, row["package_id"], row["worker_id"], None,
                    {"lease_id": lease_id, "reason": reason, "next_status": next_status.value},
                )
                self._bump_revision(connection)
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def transition_work_package(
        self,
        package_id: str,
        *,
        expected_status: TaskStatus,
        new_status: TaskStatus,
        changed_at: str,
    ) -> None:
        changed_at = _normalize_timestamp(changed_at)
        if new_status == TaskStatus.ACTIVE:
            raise RegistryConflict("ACTIVE_REQUIRES_LEASE")
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                if expected_status == TaskStatus.ACTIVE and connection.execute(
                    "SELECT 1 FROM leases WHERE package_id=? AND released_at IS NULL",
                    (package_id,),
                ).fetchone():
                    raise RegistryConflict("ACTIVE_TRANSITION_REQUIRES_LEASE_RELEASE")
                updated = connection.execute(
                    """UPDATE work_packages
                       SET status=?, ready_at=CASE WHEN ?='READY' THEN ? ELSE ready_at END,
                           updated_at=?
                       WHERE id=? AND status=?""",
                    (
                        new_status.value, new_status.value, changed_at, changed_at,
                        package_id, expected_status.value,
                    ),
                ).rowcount
                if updated != 1:
                    raise RegistryConflict("STATUS_COMPARE_AND_SWAP_FAILED")
                self._insert_event(
                    connection, "PACKAGE_STATUS_CHANGED", changed_at, package_id, None, None,
                    {"from": expected_status.value, "to": new_status.value},
                )
                self._bump_revision(connection)
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    @staticmethod
    def _insert_event(
        connection: sqlite3.Connection,
        event_type: str,
        recorded_at: str,
        package_id: str | None,
        worker_id: str | None,
        attempt_id: str | None,
        detail: Mapping[str, Any] | None,
    ) -> str:
        event_id = str(uuid.uuid4())
        connection.execute(
            """INSERT INTO task_events
               (id, event_type, recorded_at, package_id, worker_id, attempt_id, detail_json)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (event_id, event_type, recorded_at, package_id, worker_id, attempt_id, _json(detail or {})),
        )
        return event_id

    def append_event(
        self,
        event_type: str,
        *,
        recorded_at: str,
        package_id: str | None = None,
        worker_id: str | None = None,
        attempt_id: str | None = None,
        detail: Mapping[str, Any] | None = None,
    ) -> str:
        recorded_at = _normalize_timestamp(recorded_at)
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                event_id = self._insert_event(
                    connection, event_type, recorded_at, package_id, worker_id, attempt_id, detail
                )
                self._bump_revision(connection)
                connection.commit()
                return event_id
            except Exception:
                connection.rollback()
                raise

    def record_evidence(self, evidence: Evidence) -> None:
        recorded_at = _normalize_timestamp(evidence.recorded_at)
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute(
                    """INSERT INTO evidence
                   (id, package_id, kind, uri, summary, recorded_at, metadata_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        evidence.id, evidence.package_id, evidence.kind, evidence.uri,
                        evidence.summary, recorded_at, _json(evidence.metadata),
                    ),
                )
                self._bump_revision(connection)
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def import_preservation_snapshot(
        self,
        snapshot: Mapping[str, Any],
        *,
        source_uri: str,
        source_sha256: str,
        imported_at: str,
    ) -> bool:
        tasks, heartbeats, worktrees, branch_names = self._validate_preservation_snapshot(snapshot)
        imported_at = _normalize_timestamp(imported_at)
        import_id = f"preservation:{source_sha256[:20]}"
        feature_id = "FACTORY-LIVE-STATE-PRESERVATION"
        reconciliation = {
            "expected_tasks": len(tasks),
            "expected_workers": len(heartbeats),
            "expected_worktrees": len(worktrees),
            "expected_branches": len(branch_names),
            "unexplained_records": 0,
        }
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                if connection.execute(
                    "SELECT 1 FROM preservation_imports WHERE source_sha256=?", (source_sha256,)
                ).fetchone():
                    connection.rollback()
                    return False
                connection.execute(
                    """INSERT INTO preservation_imports
                       (id, source_uri, source_sha256, imported_at, snapshot_version,
                        reconciliation_json, raw_snapshot_json)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        import_id, source_uri, source_sha256, imported_at, 1,
                        _json(reconciliation), _json(snapshot),
                    ),
                )
                connection.execute(
                    """INSERT INTO features
                       (id, title, description, priority, status, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        feature_id, "Preserved live Factory state",
                        "Read-only import of pre-migration tasks and artifacts", 0,
                        TaskStatus.ON_DECK.value, imported_at, imported_at,
                    ),
                )
                for legacy_name, heartbeat in heartbeats.items():
                    worker_id = f"legacy-worker:{legacy_name}"
                    connection.execute(
                        """INSERT INTO workers
                           (id, display_name, role, availability, capabilities_json,
                            approved_lanes_json, provider_diagnostics_json,
                            last_heartbeat_at, usage_state, created_at, updated_at)
                           VALUES (?, ?, 'WORKER', ?, '[]', '[]', ?, ?, 'UNKNOWN', ?, ?)""",
                        (
                            worker_id, f"Preserved {legacy_name}", "PRESERVED",
                            _json({"legacy_worker": legacy_name}),
                            _legacy_heartbeat_time(heartbeat.get("time")),
                            imported_at, imported_at,
                        ),
                    )
                for task in tasks:
                    status_text = str(task.get("status", "ON DECK")).upper()
                    status = (
                        TaskStatus.VERIFY_REVIEW if "VERIFY" in status_text or "REVIEW" in status_text
                        else TaskStatus.BLOCKED if "BLOCKED" in status_text or "FAILED" in status_text
                        else TaskStatus.BLOCKED if "ACTIVE" in status_text
                        else TaskStatus.DONE if "DONE" in status_text
                        else TaskStatus.READY if "READY" in status_text
                        else TaskStatus.ON_DECK
                    )
                    task_id = str(task.get("task") or f"legacy-issue-{task.get('issue')}")
                    package = WorkPackage(
                        id=task_id,
                        feature_id=feature_id,
                        title=str(task.get("title") or task_id),
                        category="LEGACY_IMPORT",
                        lane=None,
                        required_capabilities=(),
                        priority=0,
                        acceptance_criteria=(),
                        status=status,
                        provider_diagnostics={
                            "legacy_worker": task.get("worker"),
                            "legacy_worker_hint": task.get("worker_hint"),
                            "legacy_issue": task.get("issue"),
                            "legacy_status": status_text,
                            "preservation_import_id": import_id,
                        },
                        branch=task.get("branch"),
                        pr_url=(
                            f"https://github.com/tanner-art/working/pull/{task['pr']}"
                            if task.get("pr") else None
                        ),
                        failure_detail=(
                            task.get("failure") or task.get("blocker")
                            or ("Preserved ACTIVE state requires lease reconciliation"
                                if "ACTIVE" in status_text else None)
                        ),
                    )
                    self._insert_package(
                        connection, package, imported_at,
                        source_system="github_issue",
                        source_ref=str(task.get("issue")),
                    )
                worktree_count = self._import_artifacts(
                    connection, import_id, "WORKTREE", worktrees
                )
                branches = [
                    {"identity": branch, "branch": branch}
                    for branch in branch_names
                ]
                branch_count = self._import_artifacts(connection, import_id, "BRANCH", branches)
                if worktree_count != len(worktrees) or branch_count != len(branch_names):
                    raise RegistryConflict("PRESERVATION_RECONCILIATION_MISMATCH")
                reconciliation.update({
                    "imported_tasks": len(tasks),
                    "imported_workers": len(heartbeats),
                    "imported_worktrees": worktree_count,
                    "imported_branches": branch_count,
                })
                connection.execute(
                    "UPDATE preservation_imports SET reconciliation_json=? WHERE id=?",
                    (_json(reconciliation), import_id),
                )
                self._insert_event(
                    connection, "PRESERVATION_IMPORTED", imported_at, None, None, None,
                    {"import_id": import_id, "source_sha256": source_sha256},
                )
                self._bump_revision(connection)
                connection.commit()
                return True
            except sqlite3.IntegrityError as error:
                connection.rollback()
                raise RegistryConflict("PRESERVATION_COLLISION", str(error)) from error
            except Exception:
                connection.rollback()
                raise

    @staticmethod
    def _validate_preservation_snapshot(
        snapshot: Mapping[str, Any],
    ) -> tuple[list[Mapping[str, Any]], Mapping[str, Any], list[Mapping[str, Any]], list[str]]:
        if snapshot.get("snapshot_version") != 1:
            raise RegistryConflict("UNSUPPORTED_SNAPSHOT_VERSION")
        canonical = snapshot.get("canonical_repository")
        if not isinstance(canonical, Mapping):
            raise RegistryConflict("INVALID_PRESERVATION_SNAPSHOT", "canonical_repository missing")
        if not canonical.get("path") or not Path(str(canonical["path"])).is_absolute():
            raise RegistryConflict(
                "INVALID_PRESERVATION_SNAPSHOT", "absolute canonical_repository.path required"
            )
        services = snapshot.get("services", {})
        heartbeats = services.get("heartbeats", {}) if isinstance(services, Mapping) else {}
        if not isinstance(heartbeats, Mapping):
            raise RegistryConflict("INVALID_PRESERVATION_SNAPSHOT", "heartbeats must be an object")
        for worker_name, heartbeat in heartbeats.items():
            if not isinstance(worker_name, str) or not worker_name or not isinstance(heartbeat, Mapping):
                raise RegistryConflict(
                    "INVALID_PRESERVATION_HEARTBEAT", str(worker_name)
                )
        raw_tasks = snapshot.get("open_task_mapping", [])
        raw_worktrees = snapshot.get("worktrees", [])
        raw_branches = snapshot.get("unmerged_local_branches", [])
        if not isinstance(raw_tasks, list) or not isinstance(raw_worktrees, list) or not isinstance(raw_branches, list):
            raise RegistryConflict("INVALID_PRESERVATION_SNAPSHOT", "task/artifact lists required")
        tasks: list[Mapping[str, Any]] = []
        task_ids: set[str] = set()
        issue_ids: set[str] = set()
        for task in raw_tasks:
            if not isinstance(task, Mapping) or not task.get("task") or task.get("issue") is None:
                raise RegistryConflict("INVALID_PRESERVATION_TASK")
            task_id, issue_id = str(task["task"]), str(task["issue"])
            if task_id in task_ids or issue_id in issue_ids:
                raise RegistryConflict("DUPLICATE_PRESERVATION_TASK", f"{task_id}/{issue_id}")
            task_ids.add(task_id)
            issue_ids.add(issue_id)
            tasks.append(task)
        worktrees: list[Mapping[str, Any]] = []
        worktree_ids: set[str] = set()
        for worktree in raw_worktrees:
            if not isinstance(worktree, Mapping) or not worktree.get("worktree"):
                raise RegistryConflict("INVALID_PRESERVATION_WORKTREE")
            identity = str(worktree["worktree"])
            path = Path(identity)
            if not path.is_absolute():
                raise RegistryConflict("INVALID_PRESERVATION_WORKTREE", "absolute path required")
            resolved_identity = str(path.resolve(strict=False))
            if resolved_identity in worktree_ids:
                raise RegistryConflict("DUPLICATE_PRESERVATION_ARTIFACT", identity)
            worktree_ids.add(resolved_identity)
            worktrees.append(worktree)
        if any(not isinstance(branch, str) or not branch.strip() for branch in raw_branches):
            raise RegistryConflict("INVALID_PRESERVATION_BRANCH")
        branch_names = list(raw_branches)
        if len(set(branch_names)) != len(branch_names):
            raise RegistryConflict("DUPLICATE_PRESERVATION_ARTIFACT", "branch")
        return tasks, heartbeats, worktrees, branch_names

    @staticmethod
    def _import_artifacts(
        connection: sqlite3.Connection,
        import_id: str,
        kind: str,
        artifacts: Sequence[Any],
    ) -> int:
        count = 0
        for artifact in artifacts:
            if not isinstance(artifact, Mapping):
                continue
            identity = artifact.get("worktree") or artifact.get("identity") or artifact.get("branch")
            if not identity:
                continue
            artifact_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{import_id}:{kind}:{identity}"))
            connection.execute(
                """INSERT INTO preserved_artifacts
                   (id, import_id, kind, external_identity, dirty, metadata_json)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    artifact_id, import_id, kind, str(identity),
                    1 if artifact.get("dirty") else 0, _json(artifact),
                ),
            )
            count += 1
        return count

    def feature_queue(self) -> Sequence[Mapping[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT feature.id, feature.title, feature.priority, feature.status,
                          package.id AS package_id, package.title AS package_title,
                          package.status AS package_status, package.lane,
                          package.kind, package.branch, package.pr_url
                   FROM features AS feature
                   LEFT JOIN work_packages AS package ON package.feature_id=feature.id
                   ORDER BY feature.priority DESC, feature.id,
                            package.priority DESC, package.created_at, package.id"""
            ).fetchall()
        features: dict[str, dict[str, Any]] = {}
        for row in rows:
            feature = features.setdefault(
                row["id"],
                {
                    "id": row["id"], "title": row["title"],
                    "priority": row["priority"], "status": row["status"], "packages": [],
                },
            )
            if row["package_id"]:
                feature["packages"].append(
                    {
                        "id": row["package_id"], "title": row["package_title"],
                        "status": row["package_status"], "lane": row["lane"],
                        "kind": row["kind"], "branch": row["branch"], "pr_url": row["pr_url"],
                    }
                )
        return list(features.values())

    def dispatch_snapshot(self, *, observed_at: str) -> DispatchSnapshot:
        """Return one consistent, read-only scheduler input at a registry revision."""
        observed_at = _normalize_timestamp(observed_at)
        with self._connection() as connection:
            connection.execute("BEGIN")
            metadata = {
                row["key"]: row["value"]
                for row in connection.execute(
                    "SELECT key, value FROM registry_metadata"
                ).fetchall()
            }
            features = tuple(
                dict(row) for row in connection.execute(
                    "SELECT * FROM features ORDER BY priority DESC, created_at, id"
                ).fetchall()
            )
            packages = []
            for row in connection.execute(
                """SELECT * FROM work_packages
                   ORDER BY priority DESC, COALESCE(ready_at, created_at), id"""
            ).fetchall():
                item = dict(row)
                for key in (
                    "required_capabilities_json", "acceptance_criteria_json",
                    "provider_diagnostics_json", "usage_consumption_json",
                ):
                    item[key.removesuffix("_json")] = json.loads(item.pop(key))
                packages.append(item)
            dependencies = tuple(
                dict(row) for row in connection.execute(
                    "SELECT package_id, dependency_id FROM task_dependencies ORDER BY package_id, dependency_id"
                ).fetchall()
            )
            workers = []
            for row in connection.execute("SELECT * FROM workers ORDER BY id").fetchall():
                item = dict(row)
                for key in (
                    "capabilities_json", "approved_lanes_json", "provider_diagnostics_json",
                ):
                    item[key.removesuffix("_json")] = json.loads(item.pop(key))
                workers.append(item)
            leases = []
            for row in connection.execute(
                "SELECT * FROM leases WHERE released_at IS NULL ORDER BY acquired_at, id"
            ).fetchall():
                item = dict(row)
                item["expired"] = item["expires_at"] <= observed_at
                leases.append(item)
            usage = []
            for row in connection.execute(
                "SELECT * FROM usage_observations ORDER BY observed_at, id"
            ).fetchall():
                item = dict(row)
                item["provider_diagnostics"] = json.loads(item.pop("provider_diagnostics_json"))
                usage.append(item)
            connection.commit()
        return DispatchSnapshot(
            revision=int(metadata["revision"]),
            observed_at=observed_at,
            active_parent_limit=int(metadata["active_parent_limit"]),
            orchestra_reserve_percent=float(metadata["orchestra_reserve_percent"]),
            features=features,
            work_packages=tuple(packages),
            dependencies=dependencies,
            workers=tuple(workers),
            active_leases=tuple(leases),
            usage_observations=tuple(usage),
        )
