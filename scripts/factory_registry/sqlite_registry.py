"""SQLite/WAL adapter for the backend-neutral Factory registry contract.

SQLite is the migration control-plane implementation. No caller should import
SQLite types or issue SQL directly; a Postgres/Supabase adapter can implement
the same ``Registry`` protocol later.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import uuid
import re
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

from .models import (
    Attempt,
    ControlCenterReadSnapshot,
    DispatchSnapshot,
    Evidence,
    Feature,
    Lane,
    Lease,
    PackageKind,
    ReviewOutcome,
    ReviewOutcomeState,
    ReviewInput,
    TaskStatus,
    UsageLedgerEntry,
    UsageLedgerWrite,
    UsageObservationClass,
    UsageSource,
    Worker,
    WorkPackage,
)
from .repository import RegistryConflict, RegistryNotFound
from .lifecycle import (
    TransitionAuthority,
    validate_attempt_completion,
    validate_dispatch_transition,
    validate_package_transition,
)


CURRENT_SCHEMA_VERSION = 5
MINIMUM_MIGRATABLE_SCHEMA_VERSION = 1
CONTROL_SCHEMA_VERSION = 1
def _json(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True, ensure_ascii=False)


def _utc_now() -> str:
    return _normalize_timestamp(datetime.now(timezone.utc).isoformat())


def _request_sha256(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


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

    def _preflight_schema_version(self) -> int | None:
        """Validate an existing Registry without opening it read-write.

        A normal connection to a WAL-mode database may create ``-wal`` or
        ``-shm`` sidecars before the first statement. SQLite's immutable mode
        avoids that mutation but ignores an active WAL. Instead, copy a stable
        main/WAL/SHM file set and let SQLite inspect only the temporary copy.
        """
        if not self.database.exists() or self.database.stat().st_size == 0:
            return None
        sources = tuple(
            Path(f"{self.database}{suffix}") for suffix in ("", "-wal", "-shm")
        )
        captured: dict[str, bytes] | None = None
        for _attempt in range(3):
            try:
                before = {
                    str(path): (path.stat().st_size, path.stat().st_mtime_ns)
                    for path in sources if path.exists()
                }
                candidate = {
                    str(path): path.read_bytes() for path in sources if path.exists()
                }
                after = {
                    str(path): (path.stat().st_size, path.stat().st_mtime_ns)
                    for path in sources if path.exists()
                }
            except OSError:
                continue
            if before == after and set(candidate) == set(after):
                captured = candidate
                break
        if captured is None:
            raise RegistryConflict("SCHEMA_SNAPSHOT_UNSTABLE")

        with tempfile.TemporaryDirectory(prefix="factory-registry-preflight-") as temporary:
            snapshot = Path(temporary) / self.database.name
            for source_name, content in captured.items():
                source = Path(source_name)
                suffix = source.name.removeprefix(self.database.name)
                Path(f"{snapshot}{suffix}").write_bytes(content)
            try:
                connection = sqlite3.connect(snapshot, timeout=10, isolation_level=None)
            except sqlite3.Error as error:
                raise RegistryConflict("SCHEMA_METADATA_INVALID") from error
            try:
                connection.row_factory = sqlite3.Row
                if not connection.execute(
                    "SELECT 1 FROM sqlite_schema "
                    "WHERE type='table' AND name='registry_metadata'"
                ).fetchone():
                    raise RegistryConflict("SCHEMA_VERSION_MISSING")
                try:
                    row = connection.execute(
                        "SELECT value FROM registry_metadata WHERE key='schema_version'"
                    ).fetchone()
                except sqlite3.Error as error:
                    raise RegistryConflict("SCHEMA_METADATA_INVALID") from error
                if row is None:
                    raise RegistryConflict("SCHEMA_VERSION_MISSING")
                raw_version = row[0]
                if not isinstance(raw_version, str) or not raw_version.isdecimal():
                    raise RegistryConflict("SCHEMA_VERSION_INVALID", str(raw_version))
                version = int(raw_version)
                if not MINIMUM_MIGRATABLE_SCHEMA_VERSION <= version <= CURRENT_SCHEMA_VERSION:
                    raise RegistryConflict("SCHEMA_VERSION_UNSUPPORTED", raw_version)
                control_row = connection.execute(
                    "SELECT value FROM registry_metadata "
                    "WHERE key='control_schema_version'"
                ).fetchone()
                if control_row is None:
                    control_tables = connection.execute(
                        "SELECT name FROM sqlite_schema "
                        "WHERE type='table' AND name IN "
                        "('factory_control', 'attempt_runtime_ownership')"
                    ).fetchall()
                    if control_tables:
                        raise RegistryConflict("CONTROL_SCHEMA_METADATA_MISSING")
                else:
                    self._require_control_schema(connection)
                return version
            except sqlite3.Error as error:
                raise RegistryConflict("SCHEMA_METADATA_INVALID") from error
            finally:
                connection.close()

    def initialize(self) -> None:
        self.database.parent.mkdir(parents=True, exist_ok=True)
        schema = Path(__file__).with_name("schema.sql").read_text()
        existing_version = self._preflight_schema_version()
        if existing_version == 3:
            raise RegistryConflict("REGISTRY_V3_OPERATOR_MIGRATION_REQUIRED")
        if existing_version == 4:
            raise RegistryConflict("REGISTRY_V4_OPERATOR_MIGRATION_REQUIRED")
        with self._connection() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(schema)
            package_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(work_packages)")
            }
            if "capacity_size" not in package_columns:
                connection.execute(
                    "ALTER TABLE work_packages ADD COLUMN capacity_size TEXT NOT NULL "
                    "DEFAULT 'SUBSTANTIAL' CHECK(capacity_size IN "
                    "('VERY_SMALL','SMALL','SUBSTANTIAL'))"
                )
            if "capacity_risk" not in package_columns:
                connection.execute(
                    "ALTER TABLE work_packages ADD COLUMN capacity_risk TEXT NOT NULL "
                    "DEFAULT 'UNCERTAIN' CHECK(capacity_risk IN "
                    "('BOUNDED','UNCERTAIN','EMERGENCY_RECOVERY'))"
                )
            usage_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(usage_ledger)")
            }
            if "observation_class" not in usage_columns:
                connection.execute("DROP TRIGGER IF EXISTS usage_ledger_is_append_only_update")
                connection.execute(
                    """ALTER TABLE usage_ledger ADD COLUMN observation_class TEXT NOT NULL
                       DEFAULT 'LEGACY_UNCLASSIFIED' CHECK(observation_class IN (
                           'AUTONOMOUS', 'DIAGNOSTIC', 'LEGACY_UNCLASSIFIED'
                       ))"""
                )
                connection.execute(
                    """UPDATE usage_ledger AS ledger
                       SET observation_class='AUTONOMOUS'
                       WHERE ledger.package_id IS NOT NULL
                         AND ledger.attempt_id IS NOT NULL
                         AND EXISTS (
                             SELECT 1
                             FROM attempts AS attempt
                             JOIN work_packages AS package
                               ON package.id=attempt.package_id
                             JOIN workers AS worker
                               ON worker.id=ledger.worker_id
                             WHERE attempt.id=ledger.attempt_id
                               AND attempt.package_id=ledger.package_id
                               AND (
                                   attempt.worker_id IS NULL
                                   OR attempt.worker_id=ledger.worker_id
                               )
                         )"""
                )
                connection.execute(
                    """CREATE TRIGGER usage_ledger_is_append_only_update
                       BEFORE UPDATE ON usage_ledger BEGIN
                           SELECT RAISE(ABORT, 'USAGE_LEDGER_APPEND_ONLY');
                       END"""
                )
            connection.execute(
                """CREATE TRIGGER IF NOT EXISTS usage_ledger_provenance_insert
                   BEFORE INSERT ON usage_ledger
                   WHEN NOT (
                       (NEW.observation_class='AUTONOMOUS'
                        AND NEW.package_id IS NOT NULL AND NEW.attempt_id IS NOT NULL)
                       OR (NEW.observation_class='DIAGNOSTIC'
                           AND NEW.package_id IS NULL AND NEW.attempt_id IS NULL)
                   )
                   BEGIN
                       SELECT RAISE(ABORT, 'USAGE_PROVENANCE_REQUIRED');
                   END"""
            )
            connection.execute(
                "UPDATE registry_metadata SET value=? "
                "WHERE key='schema_version' AND CAST(value AS INTEGER) < ?",
                (str(CURRENT_SCHEMA_VERSION), CURRENT_SCHEMA_VERSION),
            )
            self._require_control_schema(connection)

    def journal_mode(self) -> str:
        with self._connection() as connection:
            return str(connection.execute("PRAGMA journal_mode").fetchone()[0]).lower()

    @staticmethod
    def _operation_replay(
        connection: sqlite3.Connection,
        *,
        operation_id: str | None,
        operation_kind: str,
        request: Mapping[str, Any],
    ) -> Mapping[str, Any] | None:
        """Return an exact prior result or reject operation-ID reuse."""
        if operation_id is None:
            return None
        if not operation_id.strip():
            raise RegistryConflict("INVALID_OPERATION_ID")
        row = connection.execute(
            """SELECT operation_kind, request_sha256, result_json
               FROM control_operation_receipts WHERE operation_id=?""",
            (operation_id,),
        ).fetchone()
        if row is None:
            return None
        digest = _request_sha256(request)
        if row["operation_kind"] != operation_kind or row["request_sha256"] != digest:
            raise RegistryConflict("OPERATION_ID_REUSED", operation_id)
        result = json.loads(row["result_json"])
        if result.get("error_type") == "RegistryConflict":
            raise RegistryConflict(
                str(result["error_code"]), str(result.get("error_detail", ""))
            )
        if result.get("error_type") == "RegistryNotFound":
            raise RegistryNotFound(str(result.get("error_detail", "not found")))
        return result

    @staticmethod
    def _record_operation(
        connection: sqlite3.Connection,
        *,
        operation_id: str | None,
        operation_kind: str,
        request: Mapping[str, Any],
        result: Mapping[str, Any],
        recorded_at: str,
    ) -> None:
        if operation_id is None:
            return
        connection.execute(
            """INSERT INTO control_operation_receipts
               (operation_id, operation_kind, request_sha256, result_json, recorded_at)
               VALUES (?, ?, ?, ?, ?)""",
            (
                operation_id,
                operation_kind,
                _request_sha256(request),
                _json(result),
                recorded_at,
            ),
        )

    def _record_operation_rejection(
        self,
        *,
        operation_id: str | None,
        operation_kind: str,
        request: Mapping[str, Any],
        error: Exception,
        recorded_at: str,
    ) -> None:
        """Best-effort durable audit for a named, authoritatively rejected mutation."""
        if operation_id is None or not isinstance(error, (RegistryConflict, RegistryNotFound)):
            return
        if isinstance(error, RegistryConflict):
            result = {
                "error_type": "RegistryConflict",
                "error_code": error.code,
                "error_detail": error.detail,
            }
        else:
            result = {
                "error_type": "RegistryNotFound",
                "error_detail": str(error),
            }
        try:
            with self._connection() as connection:
                connection.execute("BEGIN IMMEDIATE")
                existing = connection.execute(
                    "SELECT 1 FROM control_operation_receipts WHERE operation_id=?",
                    (operation_id,),
                ).fetchone()
                if existing is not None:
                    connection.rollback()
                    return
                self._record_operation(
                    connection,
                    operation_id=operation_id,
                    operation_kind=operation_kind,
                    request=request,
                    result=result,
                    recorded_at=recorded_at,
                )
                self._insert_event(
                    connection,
                    "CONTROL_OPERATION_REJECTED",
                    recorded_at,
                    None,
                    None,
                    None,
                    {
                        "operation_id": operation_id,
                        "operation_kind": operation_kind,
                        **result,
                    },
                )
                self._bump_revision(connection)
                connection.commit()
        except Exception:
            # Audit failure must never replace the authoritative rejection.
            return

    def dispatch_control(self) -> Mapping[str, Any]:
        """Return the durable, fail-closed runner dispatch gate."""
        with self._connection() as connection:
            self._require_control_schema(connection)
            row = connection.execute(
                """SELECT control.dispatch_mode, control.kill_switch_engaged,
                          control.changed_at, control.reason, metadata.value AS revision
                   FROM factory_control AS control
                   JOIN registry_metadata AS metadata ON metadata.key='revision'
                   WHERE control.singleton=1"""
            ).fetchone()
        if row is None:
            raise RegistryConflict("DISPATCH_CONTROL_MISSING")
        return {
            "dispatch_mode": row["dispatch_mode"],
            "kill_switch_engaged": bool(row["kill_switch_engaged"]),
            "changed_at": row["changed_at"],
            "reason": row["reason"],
            "revision": int(row["revision"]),
        }

    def require_live_dispatch(self, *, expected_revision: int | None = None) -> int:
        """Fail closed unless the authoritative Registry currently permits work."""
        control = self.dispatch_control()
        if control["dispatch_mode"] != "LIVE" or control["kill_switch_engaged"]:
            raise RegistryConflict("DISPATCH_PAUSED", str(control["dispatch_mode"]))
        revision = int(control["revision"])
        if expected_revision is not None and revision != expected_revision:
            raise RegistryConflict(
                "DISPATCH_REVISION_CHANGED", f"expected {expected_revision}, got {revision}"
            )
        return revision

    def set_dispatch_control(
        self,
        *,
        expected_revision: int,
        expected_mode: str,
        new_mode: str,
        kill_switch_engaged: bool,
        changed_at: str,
        reason: str,
        operation_id: str | None = None,
    ) -> int:
        """Atomically compare-and-swap the persistent dispatch gate."""
        if new_mode not in {"PAUSED", "LIVE", "STOPPING", "RECOVERY_REQUIRED"}:
            raise RegistryConflict("INVALID_DISPATCH_MODE", new_mode)
        if new_mode == "LIVE" and kill_switch_engaged:
            raise RegistryConflict("INVALID_DISPATCH_CONTROL")
        if new_mode != "LIVE" and not kill_switch_engaged:
            raise RegistryConflict("INVALID_DISPATCH_CONTROL")
        changed_at = _normalize_timestamp(changed_at)
        request = {
            "expected_revision": expected_revision,
            "expected_mode": expected_mode,
            "new_mode": new_mode,
            "kill_switch_engaged": kill_switch_engaged,
            "reason": reason,
        }
        with self._connection() as connection:
            self._require_control_schema(connection)
            connection.execute("BEGIN IMMEDIATE")
            try:
                replay = self._operation_replay(
                    connection,
                    operation_id=operation_id,
                    operation_kind="SET_DISPATCH_CONTROL",
                    request=request,
                )
                if replay is not None:
                    connection.rollback()
                    return int(replay["revision"])
                revision = int(connection.execute(
                    "SELECT value FROM registry_metadata WHERE key='revision'"
                ).fetchone()[0])
                control = connection.execute(
                    "SELECT dispatch_mode FROM factory_control WHERE singleton=1"
                ).fetchone()
                if revision != expected_revision or control is None or control[0] != expected_mode:
                    raise RegistryConflict("DISPATCH_CONTROL_COMPARE_AND_SWAP_FAILED")
                if new_mode == "LIVE":
                    active = connection.execute(
                        "SELECT 1 FROM leases WHERE released_at IS NULL LIMIT 1"
                    ).fetchone()
                    running = connection.execute(
                        "SELECT 1 FROM attempts WHERE ended_at IS NULL LIMIT 1"
                    ).fetchone()
                    runtimes = connection.execute(
                        """SELECT 1 FROM attempt_runtime_ownership
                           WHERE released_at IS NULL LIMIT 1"""
                    ).fetchone()
                    if active or running or runtimes:
                        raise RegistryConflict("ACTIVE_OWNERSHIP_PRESENT")
                if new_mode == "PAUSED":
                    active = connection.execute(
                        "SELECT 1 FROM leases WHERE released_at IS NULL LIMIT 1"
                    ).fetchone()
                    running = connection.execute(
                        "SELECT 1 FROM attempts WHERE ended_at IS NULL LIMIT 1"
                    ).fetchone()
                    runtimes = connection.execute(
                        """SELECT 1 FROM attempt_runtime_ownership
                           WHERE released_at IS NULL LIMIT 1"""
                    ).fetchone()
                    if active or running or runtimes:
                        raise RegistryConflict("ACTIVE_OWNERSHIP_PRESENT")
                validate_dispatch_transition(expected_mode, new_mode)
                connection.execute(
                    """UPDATE factory_control
                       SET dispatch_mode=?, kill_switch_engaged=?, changed_at=?, reason=?
                       WHERE singleton=1""",
                    (new_mode, int(kill_switch_engaged), changed_at, reason),
                )
                self._insert_event(
                    connection,
                    "DISPATCH_CONTROL_CHANGED",
                    changed_at,
                    None,
                    None,
                    None,
                    {
                        "from": expected_mode,
                        "to": new_mode,
                        "kill_switch_engaged": kill_switch_engaged,
                        "reason": reason,
                    },
                )
                result = self._bump_revision(connection)
                self._record_operation(
                    connection,
                    operation_id=operation_id,
                    operation_kind="SET_DISPATCH_CONTROL",
                    request=request,
                    result={"revision": result},
                    recorded_at=changed_at,
                )
                connection.commit()
                return result
            except Exception as error:
                connection.rollback()
                self._record_operation_rejection(
                    operation_id=operation_id,
                    operation_kind="SET_DISPATCH_CONTROL",
                    request=request,
                    error=error,
                    recorded_at=changed_at,
                )
                raise

    def engage_dispatch_kill_switch(self, *, changed_at: str, reason: str) -> int:
        """Engage the kill switch without relying on a stale caller revision."""
        changed_at = _normalize_timestamp(changed_at)
        with self._connection() as connection:
            self._require_control_schema(connection)
            connection.execute("BEGIN IMMEDIATE")
            try:
                control = connection.execute(
                    "SELECT dispatch_mode FROM factory_control WHERE singleton=1"
                ).fetchone()
                if control is None:
                    raise RegistryConflict("DISPATCH_CONTROL_MISSING")
                connection.execute(
                    """UPDATE factory_control
                       SET dispatch_mode='STOPPING', kill_switch_engaged=1,
                           changed_at=?, reason=? WHERE singleton=1""",
                    (changed_at, reason),
                )
                self._insert_event(
                    connection,
                    "DISPATCH_KILL_SWITCH_ENGAGED",
                    changed_at,
                    None,
                    None,
                    None,
                    {"from": control["dispatch_mode"], "reason": reason},
                )
                revision = self._bump_revision(connection)
                connection.commit()
                return revision
            except Exception:
                connection.rollback()
                raise

    def stop_for_worker_disappearance(
        self, worker_id: str, *, observed_at: str, reason: str
    ) -> Sequence[Mapping[str, Any]]:
        """Atomically stop global dispatch and mark one missing worker offline."""
        observed_at = _normalize_timestamp(observed_at)
        with self._connection() as connection:
            self._require_control_schema(connection)
            connection.execute("BEGIN IMMEDIATE")
            try:
                worker = connection.execute(
                    "SELECT id FROM workers WHERE id=?", (worker_id,)
                ).fetchone()
                if worker is None:
                    raise RegistryNotFound(f"worker {worker_id}")
                control = connection.execute(
                    "SELECT dispatch_mode FROM factory_control WHERE singleton=1"
                ).fetchone()
                if control is None:
                    raise RegistryConflict("DISPATCH_CONTROL_MISSING")
                connection.execute(
                    """UPDATE factory_control
                       SET dispatch_mode='STOPPING', kill_switch_engaged=1,
                           changed_at=?, reason=? WHERE singleton=1""",
                    (observed_at, reason),
                )
                connection.execute(
                    """UPDATE workers SET availability='OFFLINE', updated_at=?
                       WHERE id=?""",
                    (observed_at, worker_id),
                )
                self._insert_event(
                    connection,
                    "DISPATCH_KILL_SWITCH_ENGAGED",
                    observed_at,
                    None,
                    worker_id,
                    None,
                    {"from": control["dispatch_mode"], "reason": reason},
                )
                self._insert_event(
                    connection,
                    "WORKER_DISAPPEARED",
                    observed_at,
                    None,
                    worker_id,
                    None,
                    {"availability": "OFFLINE", "reason": reason},
                )
                rows = connection.execute(
                    """SELECT runtime.attempt_id, runtime.runner_pid,
                              runtime.agent_pid, runtime.agent_pgid,
                              attempt.package_id, attempt.worker_id,
                              attempt.lease_id
                       FROM attempt_runtime_ownership AS runtime
                       JOIN attempts AS attempt ON attempt.id=runtime.attempt_id
                       WHERE runtime.released_at IS NULL
                       ORDER BY runtime.attempt_id"""
                ).fetchall()
                self._bump_revision(connection)
                connection.commit()
                return tuple(dict(row) for row in rows)
            except Exception:
                connection.rollback()
                raise

    def begin_attempt_runtime(
        self,
        attempt_id: str,
        *,
        package_id: str,
        worker_id: str,
        runner_pid: int,
        started_at: str,
        expected_revision: int,
        operation_id: str | None = None,
    ) -> None:
        """Persist attempt and runner ownership before any provider launch."""
        if runner_pid <= 0:
            raise RegistryConflict("INVALID_PROCESS_ID")
        started_at = _normalize_timestamp(started_at)
        request = {
            "attempt_id": attempt_id,
            "package_id": package_id,
            "worker_id": worker_id,
            "runner_pid": runner_pid,
            "expected_revision": expected_revision,
        }
        with self._connection() as connection:
            self._require_control_schema(connection)
            connection.execute("BEGIN IMMEDIATE")
            try:
                replay = self._operation_replay(
                    connection,
                    operation_id=operation_id,
                    operation_kind="BEGIN_ATTEMPT_RUNTIME",
                    request=request,
                )
                if replay is not None:
                    connection.rollback()
                    return
                control = connection.execute(
                    """SELECT control.dispatch_mode, control.kill_switch_engaged,
                              metadata.value AS revision
                       FROM factory_control AS control
                       JOIN registry_metadata AS metadata ON metadata.key='revision'
                       WHERE control.singleton=1"""
                ).fetchone()
                if (
                    control is None
                    or control["dispatch_mode"] != "LIVE"
                    or control["kill_switch_engaged"]
                    or int(control["revision"]) != expected_revision
                ):
                    raise RegistryConflict("DISPATCH_NOT_AUTHORIZED")
                lease = connection.execute(
                    """SELECT id FROM leases
                       WHERE package_id=? AND worker_id=? AND released_at IS NULL
                         AND expires_at > ?""",
                    (package_id, worker_id, started_at),
                ).fetchone()
                package = connection.execute(
                    "SELECT status FROM work_packages WHERE id=?", (package_id,)
                ).fetchone()
                if lease is None or package is None or package["status"] != "ACTIVE":
                    raise RegistryConflict("REGISTRY_OWNERSHIP_REQUIRED")
                connection.execute(
                    """INSERT INTO attempts
                       (id, package_id, worker_id, lease_id, started_at,
                        provider_diagnostics_json)
                       VALUES (?, ?, ?, ?, ?, '{}')""",
                    (attempt_id, package_id, worker_id, lease["id"], started_at),
                )
                connection.execute(
                    """INSERT INTO attempt_runtime_ownership
                       (attempt_id, runner_pid, recorded_at, updated_at)
                       VALUES (?, ?, ?, ?)""",
                    (attempt_id, runner_pid, started_at, started_at),
                )
                self._insert_event(
                    connection,
                    "ATTEMPT_RUNTIME_RESERVED",
                    started_at,
                    package_id,
                    worker_id,
                    attempt_id,
                    {"runner_pid": runner_pid, "lease_id": lease["id"]},
                )
                self._bump_revision(connection)
                self._record_operation(
                    connection,
                    operation_id=operation_id,
                    operation_kind="BEGIN_ATTEMPT_RUNTIME",
                    request=request,
                    result={"attempt_id": attempt_id},
                    recorded_at=started_at,
                )
                connection.commit()
            except sqlite3.IntegrityError as error:
                connection.rollback()
                conflict = RegistryConflict("ATTEMPT_RUNTIME_CONFLICT", str(error))
                self._record_operation_rejection(
                    operation_id=operation_id,
                    operation_kind="BEGIN_ATTEMPT_RUNTIME",
                    request=request,
                    error=conflict,
                    recorded_at=started_at,
                )
                raise conflict from error
            except Exception as error:
                connection.rollback()
                self._record_operation_rejection(
                    operation_id=operation_id,
                    operation_kind="BEGIN_ATTEMPT_RUNTIME",
                    request=request,
                    error=error,
                    recorded_at=started_at,
                )
                raise

    def record_attempt_process(
        self,
        attempt_id: str,
        *,
        agent_pid: int,
        agent_pgid: int,
        recorded_at: str,
    ) -> None:
        """Bind the launched provider process only while dispatch remains live."""
        if agent_pid <= 0 or agent_pgid <= 0:
            raise RegistryConflict("INVALID_PROCESS_ID")
        recorded_at = _normalize_timestamp(recorded_at)
        with self._connection() as connection:
            self._require_control_schema(connection)
            connection.execute("BEGIN IMMEDIATE")
            try:
                control = connection.execute(
                    """SELECT dispatch_mode, kill_switch_engaged
                       FROM factory_control WHERE singleton=1"""
                ).fetchone()
                if (
                    control is None
                    or control["dispatch_mode"] != "LIVE"
                    or control["kill_switch_engaged"]
                ):
                    raise RegistryConflict("DISPATCH_PAUSED")
                active = connection.execute(
                    """SELECT 1
                       FROM attempt_runtime_ownership AS runtime
                       JOIN attempts AS attempt ON attempt.id=runtime.attempt_id
                       JOIN leases AS lease ON lease.id=attempt.lease_id
                       WHERE runtime.attempt_id=? AND runtime.released_at IS NULL
                         AND attempt.ended_at IS NULL AND lease.released_at IS NULL
                         AND lease.expires_at > ?""",
                    (attempt_id, recorded_at),
                ).fetchone()
                if active is None:
                    raise RegistryConflict("ATTEMPT_RUNTIME_NOT_ACTIVE")
                updated = connection.execute(
                    """UPDATE attempt_runtime_ownership
                       SET agent_pid=?, agent_pgid=?, updated_at=?
                       WHERE attempt_id=? AND released_at IS NULL""",
                    (agent_pid, agent_pgid, recorded_at, attempt_id),
                ).rowcount
                if updated != 1:
                    raise RegistryConflict("ATTEMPT_RUNTIME_NOT_ACTIVE")
                row = connection.execute(
                    "SELECT package_id, worker_id FROM attempts WHERE id=?", (attempt_id,)
                ).fetchone()
                self._insert_event(
                    connection,
                    "ATTEMPT_PROCESS_RECORDED",
                    recorded_at,
                    row["package_id"],
                    row["worker_id"],
                    attempt_id,
                    {"agent_pid": agent_pid, "agent_pgid": agent_pgid},
                )
                self._bump_revision(connection)
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def active_attempt_runtimes(self) -> Sequence[Mapping[str, Any]]:
        """Return every unreleased runtime in deterministic attempt order."""
        with self._connection() as connection:
            self._require_control_schema(connection)
            rows = connection.execute(
                """SELECT runtime.attempt_id, runtime.runner_pid,
                          runtime.agent_pid, runtime.agent_pgid,
                          runtime.recorded_at, runtime.updated_at,
                          attempt.package_id, attempt.worker_id, attempt.lease_id,
                          attempt.ended_at, lease.expires_at AS lease_expires_at,
                          lease.released_at AS lease_released_at
                   FROM attempt_runtime_ownership AS runtime
                   JOIN attempts AS attempt ON attempt.id=runtime.attempt_id
                   LEFT JOIN leases AS lease ON lease.id=attempt.lease_id
                   WHERE runtime.released_at IS NULL
                   ORDER BY runtime.attempt_id"""
            ).fetchall()
        return tuple(dict(row) for row in rows)

    def active_unbound_leases(self) -> Sequence[Mapping[str, Any]]:
        """Return active leases not owned by an unreleased runtime record."""
        with self._connection() as connection:
            self._require_control_schema(connection)
            rows = connection.execute(
                """SELECT lease.id AS lease_id, lease.package_id, lease.worker_id,
                          lease.acquired_at, lease.expires_at
                   FROM leases AS lease
                   WHERE lease.released_at IS NULL
                     AND NOT EXISTS (
                         SELECT 1 FROM attempts AS attempt
                         JOIN attempt_runtime_ownership AS runtime
                           ON runtime.attempt_id=attempt.id
                         WHERE attempt.lease_id=lease.id
                           AND runtime.released_at IS NULL
                     )
                   ORDER BY lease.id"""
            ).fetchall()
        return tuple(dict(row) for row in rows)

    def renew_attempt_runtime(
        self,
        attempt_id: str,
        lease_id: str,
        *,
        now: str,
        expires_at: str,
    ) -> Lease:
        """Renew active runtime ownership while dispatch remains authorized."""
        now = _normalize_timestamp(now)
        expires_at = _normalize_timestamp(expires_at)
        if expires_at <= now:
            raise RegistryConflict("INVALID_LEASE_EXPIRY")
        with self._connection() as connection:
            self._require_control_schema(connection)
            connection.execute("BEGIN IMMEDIATE")
            try:
                control = connection.execute(
                    """SELECT dispatch_mode, kill_switch_engaged
                       FROM factory_control WHERE singleton=1"""
                ).fetchone()
                if (
                    control is None
                    or control["dispatch_mode"] != "LIVE"
                    or control["kill_switch_engaged"]
                ):
                    raise RegistryConflict("DISPATCH_PAUSED")
                row = connection.execute(
                    """SELECT runtime.released_at AS runtime_released_at,
                              runtime.updated_at AS runtime_updated_at,
                              runtime.agent_pid, attempt.package_id,
                              attempt.worker_id, attempt.lease_id,
                              attempt.ended_at, lease.acquired_at,
                              lease.expires_at AS lease_expires_at,
                              lease.released_at AS lease_released_at,
                              package.status AS package_status,
                              package.last_heartbeat_at AS package_heartbeat_at,
                              worker.availability AS worker_availability
                       FROM attempt_runtime_ownership AS runtime
                       JOIN attempts AS attempt ON attempt.id=runtime.attempt_id
                       JOIN leases AS lease ON lease.id=attempt.lease_id
                       JOIN work_packages AS package ON package.id=attempt.package_id
                       JOIN workers AS worker ON worker.id=attempt.worker_id
                       WHERE runtime.attempt_id=?""",
                    (attempt_id,),
                ).fetchone()
                if row is None:
                    raise RegistryNotFound(f"attempt runtime {attempt_id}")
                if row["lease_id"] != lease_id:
                    raise RegistryConflict("LEASE_OWNERSHIP_MISMATCH")
                if row["runtime_released_at"] is not None or row["ended_at"] is not None:
                    raise RegistryConflict("ATTEMPT_RUNTIME_NOT_ACTIVE")
                if row["lease_released_at"] is not None:
                    raise RegistryConflict("LEASE_REVOKED")
                if row["lease_expires_at"] <= now:
                    raise RegistryConflict("LEASE_EXPIRED")
                if (
                    now < row["acquired_at"]
                    or now < row["runtime_updated_at"]
                    or (
                        row["package_heartbeat_at"] is not None
                        and now < row["package_heartbeat_at"]
                    )
                ):
                    raise RegistryConflict("INVALID_LEASE_CHRONOLOGY")
                if expires_at < row["lease_expires_at"]:
                    raise RegistryConflict("INVALID_LEASE_EXPIRY")
                if row["package_status"] != "ACTIVE" or row["worker_availability"] != "BUSY":
                    raise RegistryConflict("REGISTRY_OWNERSHIP_REQUIRED")
                connection.execute(
                    "UPDATE leases SET expires_at=? WHERE id=?",
                    (expires_at, lease_id),
                )
                connection.execute(
                    """UPDATE attempt_runtime_ownership
                       SET updated_at=? WHERE attempt_id=? AND released_at IS NULL""",
                    (now, attempt_id),
                )
                connection.execute(
                    """UPDATE work_packages SET last_heartbeat_at=?, updated_at=?
                       WHERE id=?""",
                    (now, now, row["package_id"]),
                )
                connection.execute(
                    """UPDATE workers SET last_heartbeat_at=?, updated_at=?
                       WHERE id=?""",
                    (now, now, row["worker_id"]),
                )
                self._insert_event(
                    connection,
                    "ATTEMPT_RUNTIME_RENEWED",
                    now,
                    row["package_id"],
                    row["worker_id"],
                    attempt_id,
                    {"lease_id": lease_id, "expires_at": expires_at},
                )
                self._bump_revision(connection)
                connection.commit()
                return Lease(
                    lease_id,
                    row["package_id"],
                    row["worker_id"],
                    row["acquired_at"],
                    expires_at,
                )
            except Exception:
                connection.rollback()
                raise

    def recover_attempt_runtime(
        self,
        attempt_id: str,
        *,
        ended_at: str,
        reason: str,
        failure_detail: str,
    ) -> bool:
        """Close orphaned runtime ownership even after lease expiry or revocation."""
        ended_at = _normalize_timestamp(ended_at)
        with self._connection() as connection:
            self._require_control_schema(connection)
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(
                    """SELECT runtime.released_at AS runtime_released_at,
                              attempt.package_id, attempt.worker_id,
                              attempt.lease_id, attempt.started_at,
                              attempt.ended_at, lease.released_at AS lease_released_at,
                              package.status AS package_status,
                              worker.availability AS worker_availability
                       FROM attempt_runtime_ownership AS runtime
                       JOIN attempts AS attempt ON attempt.id=runtime.attempt_id
                       LEFT JOIN leases AS lease ON lease.id=attempt.lease_id
                       JOIN work_packages AS package ON package.id=attempt.package_id
                       JOIN workers AS worker ON worker.id=attempt.worker_id
                       WHERE runtime.attempt_id=?""",
                    (attempt_id,),
                ).fetchone()
                if row is None:
                    raise RegistryNotFound(f"attempt runtime {attempt_id}")
                if row["runtime_released_at"] is not None:
                    connection.rollback()
                    return False
                if ended_at < row["started_at"]:
                    raise RegistryConflict("INVALID_ATTEMPT_CHRONOLOGY")
                connection.execute(
                    """UPDATE attempt_runtime_ownership
                       SET released_at=?, release_reason=?, updated_at=?
                       WHERE attempt_id=? AND released_at IS NULL""",
                    (ended_at, reason, ended_at, attempt_id),
                )
                if row["ended_at"] is None:
                    connection.execute(
                        """UPDATE attempts
                           SET ended_at=?, outcome='FAILED',
                               failure_code='RUNTIME_RECOVERY', failure_detail=?
                           WHERE id=?""",
                        (ended_at, failure_detail, attempt_id),
                    )
                if row["lease_id"] is not None and row["lease_released_at"] is None:
                    connection.execute(
                        """UPDATE leases SET released_at=?, release_reason=?
                           WHERE id=? AND released_at IS NULL""",
                        (ended_at, reason, row["lease_id"]),
                    )
                if row["package_status"] == "ACTIVE":
                    connection.execute(
                        """UPDATE work_packages
                           SET status='BLOCKED', failure_code='RUNTIME_RECOVERY',
                               failure_detail=?, updated_at=? WHERE id=?""",
                        (failure_detail, ended_at, row["package_id"]),
                    )
                if row["worker_availability"] == "BUSY":
                    connection.execute(
                        "UPDATE workers SET availability='IDLE', updated_at=? WHERE id=?",
                        (ended_at, row["worker_id"]),
                    )
                failure_id = str(uuid.uuid4())
                connection.execute(
                    """INSERT INTO failure_observations
                       (id, package_id, worker_id, attempt_id, code, detail,
                        observed_at, metadata_json)
                       VALUES (?, ?, ?, ?, 'RUNTIME_RECOVERY', ?, ?, ?)""",
                    (
                        failure_id,
                        row["package_id"],
                        row["worker_id"],
                        attempt_id,
                        failure_detail,
                        ended_at,
                        _json({"lease_id": row["lease_id"], "reason": reason}),
                    ),
                )
                self._insert_event(
                    connection,
                    "ATTEMPT_RUNTIME_RECOVERED",
                    ended_at,
                    row["package_id"],
                    row["worker_id"],
                    attempt_id,
                    {"failure_id": failure_id, "reason": reason},
                )
                self._bump_revision(connection)
                connection.commit()
                return True
            except Exception:
                connection.rollback()
                raise

    def recover_stopped_lease(
        self,
        lease_id: str,
        *,
        ended_at: str,
        reason: str,
        failure_detail: str,
    ) -> bool:
        """Release lease-only ownership left before attempt reservation."""
        ended_at = _normalize_timestamp(ended_at)
        with self._connection() as connection:
            self._require_control_schema(connection)
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(
                    """SELECT lease.*, package.status AS package_status,
                              worker.availability AS worker_availability
                       FROM leases AS lease
                       JOIN work_packages AS package ON package.id=lease.package_id
                       JOIN workers AS worker ON worker.id=lease.worker_id
                       WHERE lease.id=?""",
                    (lease_id,),
                ).fetchone()
                if row is None:
                    raise RegistryNotFound(f"lease {lease_id}")
                if row["released_at"] is not None:
                    connection.rollback()
                    return False
                if ended_at < row["acquired_at"]:
                    raise RegistryConflict("INVALID_LEASE_CHRONOLOGY")
                connection.execute(
                    """UPDATE leases SET released_at=?, release_reason=?
                       WHERE id=? AND released_at IS NULL""",
                    (ended_at, reason, lease_id),
                )
                if row["package_status"] == "ACTIVE":
                    connection.execute(
                        """UPDATE work_packages
                           SET status='BLOCKED', failure_code='LEASE_RECOVERY',
                               failure_detail=?, updated_at=? WHERE id=?""",
                        (failure_detail, ended_at, row["package_id"]),
                    )
                if row["worker_availability"] == "BUSY":
                    connection.execute(
                        "UPDATE workers SET availability='IDLE', updated_at=? WHERE id=?",
                        (ended_at, row["worker_id"]),
                    )
                failure_id = str(uuid.uuid4())
                connection.execute(
                    """INSERT INTO failure_observations
                       (id, package_id, worker_id, attempt_id, code, detail,
                        observed_at, metadata_json)
                       VALUES (?, ?, ?, NULL, 'LEASE_RECOVERY', ?, ?, ?)""",
                    (
                        failure_id,
                        row["package_id"],
                        row["worker_id"],
                        failure_detail,
                        ended_at,
                        _json({"lease_id": lease_id, "reason": reason}),
                    ),
                )
                self._insert_event(
                    connection,
                    "LEASE_OWNERSHIP_RECOVERED",
                    ended_at,
                    row["package_id"],
                    row["worker_id"],
                    None,
                    {"failure_id": failure_id, "lease_id": lease_id, "reason": reason},
                )
                self._bump_revision(connection)
                connection.commit()
                return True
            except Exception:
                connection.rollback()
                raise

    def record_runtime_recovery_failure(
        self, attempt_id: str, *, observed_at: str, detail: str
    ) -> str:
        """Persist deterministic evidence while dispatch remains STOPPING."""
        observed_at = _normalize_timestamp(observed_at)
        with self._connection() as connection:
            self._require_control_schema(connection)
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(
                    "SELECT package_id, worker_id FROM attempts WHERE id=?",
                    (attempt_id,),
                ).fetchone()
                if row is None:
                    raise RegistryNotFound(f"attempt {attempt_id}")
                failure_id = str(uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"runtime-recovery:{attempt_id}",
                ))
                connection.execute(
                    """INSERT OR IGNORE INTO failure_observations
                       (id, package_id, worker_id, attempt_id, code, detail,
                        observed_at, metadata_json)
                       VALUES (?, ?, ?, ?, 'RUNTIME_RECOVERY_FAILED', ?, ?, '{}')""",
                    (
                        failure_id,
                        row["package_id"],
                        row["worker_id"],
                        attempt_id,
                        detail,
                        observed_at,
                    ),
                )
                self._insert_event(
                    connection,
                    "ATTEMPT_RUNTIME_RECOVERY_FAILED",
                    observed_at,
                    row["package_id"],
                    row["worker_id"],
                    attempt_id,
                    {"failure_id": failure_id, "detail": detail},
                )
                self._bump_revision(connection)
                connection.commit()
                return failure_id
            except Exception:
                connection.rollback()
                raise

    def record_lease_recovery_failure(
        self, lease_id: str, *, observed_at: str, detail: str
    ) -> str:
        observed_at = _normalize_timestamp(observed_at)
        with self._connection() as connection:
            self._require_control_schema(connection)
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(
                    "SELECT package_id, worker_id FROM leases WHERE id=?",
                    (lease_id,),
                ).fetchone()
                if row is None:
                    raise RegistryNotFound(f"lease {lease_id}")
                failure_id = str(uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"lease-recovery:{lease_id}",
                ))
                connection.execute(
                    """INSERT OR IGNORE INTO failure_observations
                       (id, package_id, worker_id, attempt_id, code, detail,
                        observed_at, metadata_json)
                       VALUES (?, ?, ?, NULL, 'LEASE_RECOVERY_FAILED', ?, ?, ?)""",
                    (
                        failure_id,
                        row["package_id"],
                        row["worker_id"],
                        detail,
                        observed_at,
                        _json({"lease_id": lease_id}),
                    ),
                )
                self._insert_event(
                    connection,
                    "LEASE_OWNERSHIP_RECOVERY_FAILED",
                    observed_at,
                    row["package_id"],
                    row["worker_id"],
                    None,
                    {"failure_id": failure_id, "lease_id": lease_id, "detail": detail},
                )
                self._bump_revision(connection)
                connection.commit()
                return failure_id
            except Exception:
                connection.rollback()
                raise

    def release_attempt_runtime(
        self,
        attempt_id: str,
        *,
        released_at: str,
        reason: str,
    ) -> None:
        released_at = _normalize_timestamp(released_at)
        with self._connection() as connection:
            self._require_control_schema(connection)
            connection.execute("BEGIN IMMEDIATE")
            try:
                updated = connection.execute(
                    """UPDATE attempt_runtime_ownership
                       SET released_at=?, release_reason=?, updated_at=?
                       WHERE attempt_id=? AND released_at IS NULL""",
                    (released_at, reason, released_at, attempt_id),
                ).rowcount
                if updated != 1:
                    raise RegistryConflict("ATTEMPT_RUNTIME_NOT_ACTIVE")
                row = connection.execute(
                    "SELECT package_id, worker_id FROM attempts WHERE id=?", (attempt_id,)
                ).fetchone()
                self._insert_event(
                    connection,
                    "ATTEMPT_RUNTIME_RELEASED",
                    released_at,
                    row["package_id"],
                    row["worker_id"],
                    attempt_id,
                    {"reason": reason},
                )
                self._bump_revision(connection)
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def finish_attempt_runtime(
        self,
        attempt_id: str,
        *,
        ended_at: str,
        outcome: str,
        next_status: TaskStatus,
        reason: str,
        failure_detail: str | None = None,
        operation_id: str | None = None,
    ) -> None:
        """Atomically close runtime, attempt, lease, package, and worker ownership."""
        validate_attempt_completion(outcome, next_status)
        ended_at = _normalize_timestamp(ended_at)
        request = {
            "attempt_id": attempt_id,
            "outcome": outcome,
            "next_status": next_status.value,
            "reason": reason,
            "failure_detail": failure_detail,
        }
        with self._connection() as connection:
            self._require_control_schema(connection)
            connection.execute("BEGIN IMMEDIATE")
            try:
                replay = self._operation_replay(
                    connection,
                    operation_id=operation_id,
                    operation_kind="FINISH_ATTEMPT_RUNTIME",
                    request=request,
                )
                if replay is not None:
                    connection.rollback()
                    return
                row = connection.execute(
                    """SELECT attempt.package_id, attempt.worker_id, attempt.lease_id,
                              attempt.started_at, attempt.ended_at,
                              runtime.released_at AS runtime_released_at
                       FROM attempts AS attempt
                       JOIN attempt_runtime_ownership AS runtime
                         ON runtime.attempt_id=attempt.id
                       WHERE attempt.id=?""",
                    (attempt_id,),
                ).fetchone()
                if row is None:
                    raise RegistryNotFound(f"attempt runtime {attempt_id}")
                if row["ended_at"] is not None or row["runtime_released_at"] is not None:
                    raise RegistryConflict("ATTEMPT_RUNTIME_NOT_ACTIVE")
                if ended_at < row["started_at"]:
                    raise RegistryConflict("INVALID_ATTEMPT_CHRONOLOGY")
                lease = connection.execute(
                    "SELECT released_at FROM leases WHERE id=?", (row["lease_id"],)
                ).fetchone()
                if lease is None or lease["released_at"] is not None:
                    raise RegistryConflict("LEASE_NOT_ACTIVE")
                connection.execute(
                    """UPDATE attempt_runtime_ownership
                       SET released_at=?, release_reason=?, updated_at=?
                       WHERE attempt_id=?""",
                    (ended_at, reason, ended_at, attempt_id),
                )
                connection.execute(
                    """UPDATE attempts
                       SET ended_at=?, outcome=?, failure_detail=?
                       WHERE id=?""",
                    (ended_at, outcome, failure_detail, attempt_id),
                )
                connection.execute(
                    "UPDATE leases SET released_at=?, release_reason=? WHERE id=?",
                    (ended_at, reason, row["lease_id"]),
                )
                package_updated = connection.execute(
                    """UPDATE work_packages
                       SET status=?, updated_at=?, failure_detail=?
                       WHERE id=? AND status='ACTIVE'""",
                    (
                        next_status.value,
                        ended_at,
                        failure_detail,
                        row["package_id"],
                    ),
                ).rowcount
                if package_updated != 1:
                    raise RegistryConflict("PACKAGE_NOT_ACTIVE")
                connection.execute(
                    "UPDATE workers SET availability='IDLE', updated_at=? WHERE id=?",
                    (ended_at, row["worker_id"]),
                )
                self._insert_event(
                    connection,
                    "ATTEMPT_FINISHED",
                    ended_at,
                    row["package_id"],
                    row["worker_id"],
                    attempt_id,
                    {
                        "outcome": outcome,
                        "next_status": next_status.value,
                        "reason": reason,
                    },
                )
                self._bump_revision(connection)
                self._record_operation(
                    connection,
                    operation_id=operation_id,
                    operation_kind="FINISH_ATTEMPT_RUNTIME",
                    request=request,
                    result={"attempt_id": attempt_id, "status": next_status.value},
                    recorded_at=ended_at,
                )
                connection.commit()
            except Exception as error:
                connection.rollback()
                self._record_operation_rejection(
                    operation_id=operation_id,
                    operation_kind="FINISH_ATTEMPT_RUNTIME",
                    request=request,
                    error=error,
                    recorded_at=ended_at,
                )
                raise

    def runtime_orphans(
        self, *, observed_at: str | None = None
    ) -> Sequence[Mapping[str, Any]]:
        """Return unresolved runtime ownership without changing it."""
        observed_at = _normalize_timestamp(observed_at or _utc_now())
        with self._connection() as connection:
            self._require_control_schema(connection)
            rows = connection.execute(
                """SELECT runtime.*, attempt.package_id, attempt.worker_id,
                          attempt.ended_at, lease.released_at AS lease_released_at,
                          lease.expires_at AS lease_expires_at,
                          worker.availability AS worker_availability
                   FROM attempt_runtime_ownership AS runtime
                   JOIN attempts AS attempt ON attempt.id=runtime.attempt_id
                   LEFT JOIN leases AS lease ON lease.id=attempt.lease_id
                   LEFT JOIN workers AS worker ON worker.id=attempt.worker_id
                   WHERE runtime.released_at IS NULL
                     AND (attempt.ended_at IS NOT NULL OR lease.id IS NULL
                          OR lease.released_at IS NOT NULL OR lease.expires_at <= ?
                          OR worker.availability IN ('OFFLINE', 'CONSTRAINED'))
                   ORDER BY runtime.attempt_id""",
                (observed_at,),
            ).fetchall()
        return tuple(dict(row) for row in rows)

    @staticmethod
    def _require_control_schema(connection: sqlite3.Connection) -> None:
        """Reject unknown control-plane storage before reading or mutating it."""
        try:
            row = connection.execute(
                "SELECT value FROM registry_metadata WHERE key='control_schema_version'"
            ).fetchone()
        except sqlite3.DatabaseError as error:
            raise RegistryConflict("CONTROL_SCHEMA_METADATA_MISSING") from error
        if row is None:
            raise RegistryConflict("CONTROL_SCHEMA_METADATA_MISSING")
        try:
            version = int(row[0])
        except (TypeError, ValueError) as error:
            raise RegistryConflict("MALFORMED_CONTROL_SCHEMA_VERSION", str(row[0])) from error
        if str(version) != str(row[0]).strip():
            raise RegistryConflict("MALFORMED_CONTROL_SCHEMA_VERSION", str(row[0]))
        if version != CONTROL_SCHEMA_VERSION:
            raise RegistryConflict("UNSUPPORTED_CONTROL_SCHEMA_VERSION", str(version))

    @staticmethod
    def _bump_revision(connection: sqlite3.Connection) -> int:
        connection.execute(
            "UPDATE registry_metadata SET value=CAST(value AS INTEGER)+1 WHERE key='revision'"
        )
        return int(connection.execute(
            "SELECT value FROM registry_metadata WHERE key='revision'"
        ).fetchone()[0])

    @staticmethod
    def _require_revision(connection: sqlite3.Connection, expected_revision: int) -> None:
        revision = int(connection.execute(
            "SELECT value FROM registry_metadata WHERE key='revision'"
        ).fetchone()[0])
        if revision != expected_revision:
            raise RegistryConflict(
                "REGISTRY_REVISION_CHANGED",
                f"expected {expected_revision}, got {revision}",
            )

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
                (id, feature_id, title, category, lane, kind, capacity_size, capacity_risk,
                 required_capabilities_json, priority, acceptance_criteria_json,
                 status, provider_diagnostics_json, branch, pr_url, ready_at, started_at,
                 last_heartbeat_at, runtime_seconds, usage_consumption_json,
                 failure_code, failure_detail, source_system, source_ref,
                 created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                package.id, package.feature_id, package.title, package.category,
                package.lane.value if package.lane else None, package.kind.value,
                package.capacity_size.value, package.capacity_risk.value,
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

    def sync_worker_telemetry(
        self,
        worker: Worker,
        usage_observations: Sequence[Mapping[str, Any]],
        *,
        expected_revision: int,
        recorded_at: str,
    ) -> int:
        """Atomically upsert one active worker and its fresh capacity evidence."""
        recorded_at = _normalize_timestamp(recorded_at)
        heartbeat_at = (
            _normalize_timestamp(worker.last_heartbeat_at)
            if worker.last_heartbeat_at else None
        )
        if worker.id.startswith("legacy-worker:") or worker.availability == "PRESERVED":
            raise RegistryConflict("PRESERVED_WORKER_IMMUTABLE", worker.id)
        normalized = []
        for observation in usage_observations:
            value = dict(observation)
            if value.get("worker_id") != worker.id:
                raise RegistryConflict("USAGE_WORKER_MISMATCH", str(value.get("worker_id")))
            observation_id = value.get("id")
            if not isinstance(observation_id, str) or not observation_id:
                raise RegistryConflict("INVALID_USAGE_OBSERVATION", "id")
            observed_at = _normalize_timestamp(value.get("observed_at"))
            reset_at = value.get("reset_at")
            reset_at = _normalize_timestamp(reset_at) if reset_at else None
            consumed = value.get("consumed_percent")
            if consumed is not None and (
                isinstance(consumed, bool)
                or not isinstance(consumed, (int, float))
                or not 0 <= float(consumed) <= 100
            ):
                raise RegistryConflict("INVALID_USAGE_OBSERVATION", "consumed_percent")
            state = value.get("state")
            if not isinstance(state, str) or not state:
                raise RegistryConflict("INVALID_USAGE_OBSERVATION", "state")
            diagnostics = dict(value.get("provider_diagnostics") or {})
            for key in (
                "capacity_mode", "capacity_scope", "service_state",
                "authentication_state", "live_invocation_state", "limit_signal",
            ):
                if key in value:
                    diagnostics[key] = value[key]
            normalized.append((
                observation_id, observed_at, reset_at, consumed, state, diagnostics,
            ))
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                self._require_control_schema(connection)
                self._require_revision(connection, expected_revision)
                if connection.execute(
                    "SELECT 1 FROM leases WHERE worker_id=? AND released_at IS NULL",
                    (worker.id,),
                ).fetchone():
                    raise RegistryConflict("WORKER_HAS_ACTIVE_LEASE")
                prior = connection.execute(
                    "SELECT availability FROM workers WHERE id=?", (worker.id,)
                ).fetchone()
                if prior is not None and prior["availability"] == "PRESERVED":
                    raise RegistryConflict("PRESERVED_WORKER_IMMUTABLE", worker.id)
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
                        _json(worker.capabilities),
                        _json([lane.value for lane in worker.approved_lanes]),
                        _json(worker.provider_diagnostics), heartbeat_at,
                        worker.usage_state, recorded_at, recorded_at,
                    ),
                )
                for observation_id, observed_at, reset_at, consumed, state, diagnostics in normalized:
                    connection.execute(
                        """INSERT INTO usage_observations
                           (id, worker_id, observed_at, reset_at, consumed_percent,
                            state, provider_diagnostics_json)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (
                            observation_id, worker.id, observed_at, reset_at,
                            consumed, state, _json(diagnostics),
                        ),
                    )
                self._insert_event(
                    connection,
                    "WORKER_TELEMETRY_SYNCED",
                    recorded_at,
                    None,
                    worker.id,
                    None,
                    {"usage_observation_ids": [value[0] for value in normalized]},
                )
                revision = self._bump_revision(connection)
                connection.commit()
                return revision
            except sqlite3.IntegrityError as error:
                connection.rollback()
                raise RegistryConflict("WORKER_TELEMETRY_CONFLICT", str(error)) from error
            except Exception:
                connection.rollback()
                raise

    def register_canary_bundle(
        self,
        feature: Feature,
        implementation: WorkPackage,
        review: WorkPackage,
        *,
        expected_revision: int,
        recorded_at: str,
    ) -> int:
        """Register exactly one implementation/review canary while fail-closed."""
        recorded_at = _normalize_timestamp(recorded_at)
        if implementation.feature_id != feature.id or review.feature_id != feature.id:
            raise RegistryConflict("CANARY_FEATURE_MISMATCH")
        if implementation.id == review.id:
            raise RegistryConflict("CANARY_PACKAGE_ID_CONFLICT")
        if implementation.kind != PackageKind.PARENT or review.kind != PackageKind.REVIEW:
            raise RegistryConflict("INVALID_CANARY_KINDS")
        if implementation.status != TaskStatus.READY or review.status != TaskStatus.READY:
            raise RegistryConflict("CANARY_PACKAGES_MUST_BE_READY")
        if review.lane != Lane.ASSURANCE:
            raise RegistryConflict("CANARY_REVIEW_REQUIRES_ASSURANCE")
        if tuple(review.dependency_ids) != (implementation.id,):
            raise RegistryConflict("CANARY_REVIEW_DEPENDENCY_INVALID")
        if not {value.lower() for value in review.required_capabilities} & {
            "review", "independent-review"
        }:
            raise RegistryConflict("CANARY_REVIEW_CAPABILITY_MISSING")
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                self._require_control_schema(connection)
                self._require_revision(connection, expected_revision)
                control = connection.execute(
                    "SELECT dispatch_mode, kill_switch_engaged FROM factory_control WHERE singleton=1"
                ).fetchone()
                if control is None or control["dispatch_mode"] != "PAUSED" or not control["kill_switch_engaged"]:
                    raise RegistryConflict("CANARY_REGISTRATION_REQUIRES_PAUSED")
                if connection.execute(
                    "SELECT 1 FROM leases WHERE released_at IS NULL LIMIT 1"
                ).fetchone() or connection.execute(
                    "SELECT 1 FROM attempts WHERE ended_at IS NULL LIMIT 1"
                ).fetchone() or connection.execute(
                    "SELECT 1 FROM attempt_runtime_ownership WHERE released_at IS NULL LIMIT 1"
                ).fetchone():
                    raise RegistryConflict("ACTIVE_OWNERSHIP_PRESENT")
                existing_ready = connection.execute(
                    "SELECT id FROM work_packages WHERE status IN ('READY', 'ACTIVE') ORDER BY id"
                ).fetchall()
                if existing_ready:
                    raise RegistryConflict(
                        "CANARY_NOT_EXCLUSIVE",
                        ",".join(row["id"] for row in existing_ready),
                    )
                connection.execute(
                    """INSERT INTO features
                       (id, title, description, priority, status, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        feature.id, feature.title, feature.description, feature.priority,
                        feature.status.value, recorded_at, recorded_at,
                    ),
                )
                self._insert_package(connection, implementation, recorded_at)
                self._insert_package(connection, review, recorded_at)
                connection.execute(
                    "INSERT INTO task_dependencies(package_id, dependency_id) VALUES (?, ?)",
                    (review.id, implementation.id),
                )
                self._insert_event(
                    connection,
                    "CANARY_REGISTERED",
                    recorded_at,
                    implementation.id,
                    None,
                    None,
                    {"feature_id": feature.id, "review_package_id": review.id},
                )
                revision = self._bump_revision(connection)
                connection.commit()
                return revision
            except sqlite3.IntegrityError as error:
                connection.rollback()
                raise RegistryConflict("CANARY_REGISTRATION_CONFLICT", str(error)) from error
            except Exception:
                connection.rollback()
                raise

    def register_followup_review(
        self,
        review: WorkPackage,
        *,
        expected_revision: int,
        recorded_at: str,
    ) -> int:
        """Register one review retry after an evidence-bound changes request."""
        recorded_at = _normalize_timestamp(recorded_at)
        if (
            review.kind != PackageKind.REVIEW
            or review.status != TaskStatus.READY
            or review.lane != Lane.ASSURANCE
            or len(review.dependency_ids) != 1
            or not {value.lower() for value in review.required_capabilities}
            & {"review", "independent-review"}
        ):
            raise RegistryConflict("INVALID_FOLLOWUP_REVIEW")
        target_id = review.dependency_ids[0]
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                self._require_control_schema(connection)
                self._require_revision(connection, expected_revision)
                control = connection.execute(
                    "SELECT dispatch_mode, kill_switch_engaged FROM factory_control WHERE singleton=1"
                ).fetchone()
                if (
                    control is None
                    or control["dispatch_mode"] != "PAUSED"
                    or not control["kill_switch_engaged"]
                ):
                    raise RegistryConflict("FOLLOWUP_REVIEW_REQUIRES_PAUSED")
                if connection.execute(
                    "SELECT 1 FROM leases WHERE released_at IS NULL LIMIT 1"
                ).fetchone() or connection.execute(
                    "SELECT 1 FROM attempts WHERE ended_at IS NULL LIMIT 1"
                ).fetchone() or connection.execute(
                    "SELECT 1 FROM attempt_runtime_ownership WHERE released_at IS NULL LIMIT 1"
                ).fetchone():
                    raise RegistryConflict("ACTIVE_OWNERSHIP_PRESENT")
                if connection.execute(
                    "SELECT 1 FROM work_packages WHERE status IN ('READY', 'ACTIVE') LIMIT 1"
                ).fetchone():
                    raise RegistryConflict("CANARY_NOT_EXCLUSIVE")
                target = connection.execute(
                    "SELECT feature_id, kind, status FROM work_packages WHERE id=?",
                    (target_id,),
                ).fetchone()
                if target is None:
                    raise RegistryNotFound(f"work package {target_id}")
                if (
                    target["feature_id"] != review.feature_id
                    or target["kind"] != PackageKind.PARENT.value
                    or target["status"] != TaskStatus.VERIFY_REVIEW.value
                ):
                    raise RegistryConflict("FOLLOWUP_REVIEW_TARGET_INVALID")
                prior = connection.execute(
                    """SELECT 1 FROM review_outcomes
                       WHERE target_package_id=? AND state='CHANGES_REQUESTED'
                       LIMIT 1""",
                    (target_id,),
                ).fetchone()
                if prior is None:
                    raise RegistryConflict("CHANGES_REQUESTED_REVIEW_REQUIRED")
                self._insert_package(connection, review, recorded_at)
                connection.execute(
                    "INSERT INTO task_dependencies(package_id, dependency_id) VALUES (?, ?)",
                    (review.id, target_id),
                )
                self._insert_event(
                    connection,
                    "FOLLOWUP_REVIEW_REGISTERED",
                    recorded_at,
                    review.id,
                    None,
                    None,
                    {"feature_id": review.feature_id, "target_package_id": target_id},
                )
                revision = self._bump_revision(connection)
                connection.commit()
                return revision
            except sqlite3.IntegrityError as error:
                connection.rollback()
                raise RegistryConflict(
                    "FOLLOWUP_REVIEW_REGISTRATION_CONFLICT", str(error)
                ) from error
            except Exception:
                connection.rollback()
                raise

    def requeue_failed_package(
        self,
        package_id: str,
        *,
        expected_revision: int,
        changed_at: str,
        reason: str,
    ) -> int:
        """Requeue a terminal failed package without changing attempt history."""
        changed_at = _normalize_timestamp(changed_at)
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                self._require_control_schema(connection)
                self._require_revision(connection, expected_revision)
                control = connection.execute(
                    "SELECT dispatch_mode, kill_switch_engaged FROM factory_control WHERE singleton=1"
                ).fetchone()
                if control is None or control["dispatch_mode"] != "PAUSED" or not control["kill_switch_engaged"]:
                    raise RegistryConflict("REQUEUE_REQUIRES_PAUSED")
                package = connection.execute(
                    "SELECT status FROM work_packages WHERE id=?", (package_id,)
                ).fetchone()
                if package is None:
                    raise RegistryNotFound(f"work package {package_id}")
                if package["status"] != "BLOCKED":
                    raise RegistryConflict("PACKAGE_NOT_BLOCKED", package["status"])
                if connection.execute(
                    "SELECT 1 FROM leases WHERE package_id=? AND released_at IS NULL",
                    (package_id,),
                ).fetchone() or connection.execute(
                    "SELECT 1 FROM attempt_runtime_ownership AS runtime "
                    "JOIN attempts AS attempt ON attempt.id=runtime.attempt_id "
                    "WHERE attempt.package_id=? AND runtime.released_at IS NULL",
                    (package_id,),
                ).fetchone():
                    raise RegistryConflict("ACTIVE_OWNERSHIP_PRESENT")
                attempt = connection.execute(
                    """SELECT id, ended_at, outcome FROM attempts
                       WHERE package_id=? ORDER BY started_at DESC, id DESC LIMIT 1""",
                    (package_id,),
                ).fetchone()
                if (
                    attempt is None
                    or attempt["ended_at"] is None
                    or attempt["outcome"] not in {"FAILED", "BLOCKED"}
                ):
                    raise RegistryConflict("TERMINAL_FAILED_ATTEMPT_REQUIRED")
                connection.execute(
                    """UPDATE work_packages
                       SET status='READY', ready_at=?, failure_code=NULL,
                           failure_detail=NULL, updated_at=? WHERE id=?""",
                    (changed_at, changed_at, package_id),
                )
                self._insert_event(
                    connection,
                    "PACKAGE_REQUEUED",
                    changed_at,
                    package_id,
                    None,
                    attempt["id"],
                    {"reason": reason, "prior_outcome": attempt["outcome"]},
                )
                revision = self._bump_revision(connection)
                connection.commit()
                return revision
            except Exception:
                connection.rollback()
                raise

    def review_implementer_worker(self, review_package_id: str) -> str:
        """Return the actual successful implementer for a review package."""
        with self._connection() as connection:
            review = connection.execute(
                "SELECT kind FROM work_packages WHERE id=?", (review_package_id,)
            ).fetchone()
            if review is None:
                raise RegistryNotFound(f"work package {review_package_id}")
            if review["kind"] != "REVIEW":
                raise RegistryConflict("REVIEW_PACKAGE_REQUIRED")
            targets = connection.execute(
                "SELECT dependency_id FROM task_dependencies WHERE package_id=?",
                (review_package_id,),
            ).fetchall()
            if len(targets) != 1:
                raise RegistryConflict("REVIEW_TARGET_MISMATCH")
            target_id = str(targets[0]["dependency_id"])
        return self.successful_package_worker(target_id)

    def successful_package_worker(self, package_id: str) -> str:
        """Return the worker from the latest completed successful package attempt."""
        with self._connection() as connection:
            if connection.execute(
                "SELECT 1 FROM work_packages WHERE id=?", (package_id,)
            ).fetchone() is None:
                raise RegistryNotFound(f"work package {package_id}")
            attempt = connection.execute(
                """SELECT worker_id FROM attempts
                   WHERE package_id=? AND outcome='SUCCEEDED'
                     AND ended_at IS NOT NULL AND worker_id IS NOT NULL
                   ORDER BY ended_at DESC, started_at DESC, id DESC LIMIT 1""",
                (package_id,),
            ).fetchone()
        if attempt is None:
            raise RegistryConflict("SUCCESSFUL_PACKAGE_PROVENANCE_REQUIRED")
        return str(attempt["worker_id"])

    def record_review_input(self, review_input: ReviewInput, *, operation_id: str | None = None) -> None:
        """Record immutable review input separately from a reviewer verdict."""
        if (not all(isinstance(value, str) and value for value in (review_input.id, review_input.review_package_id, review_input.target_package_id, review_input.implementation_attempt_id, review_input.pr_url, review_input.contract_sha256)) or not re.fullmatch(r"[0-9a-f]{40,64}", review_input.implementation_commit) or not re.fullmatch(r"[0-9a-f]{40,64}", review_input.base_commit) or not re.fullmatch(r"[0-9a-f]{64}", review_input.contract_sha256) or not isinstance(review_input.contract, Mapping) or not isinstance(review_input.validation_evidence, Mapping) or not review_input.validation_evidence):
            raise RegistryConflict("INVALID_REVIEW_INPUT")
        if _request_sha256(dict(review_input.contract)) != review_input.contract_sha256:
            raise RegistryConflict("REVIEW_CONTRACT_MISMATCH")
        self.record_evidence(Evidence(id=review_input.id, package_id=review_input.review_package_id, kind="review-input", uri=review_input.pr_url, summary="Exact implementation input bound for independent review.", recorded_at=review_input.recorded_at, metadata={"target_package_id": review_input.target_package_id, "implementation_attempt_id": review_input.implementation_attempt_id, "implementation_commit": review_input.implementation_commit, "base_commit": review_input.base_commit, "contract_sha256": review_input.contract_sha256, "contract": dict(review_input.contract), "validation_evidence": dict(review_input.validation_evidence)}), operation_id=operation_id or f"review-input:{review_input.id}")

    def review_input(self, review_package_id: str) -> Mapping[str, Any]:
        """Return the single immutable input assigned to a review package."""
        with self._connection() as connection:
            rows = connection.execute("SELECT id, package_id, uri, recorded_at, metadata_json FROM evidence WHERE package_id=? AND kind='review-input' ORDER BY recorded_at, id", (review_package_id,)).fetchall()
        if len(rows) != 1:
            raise RegistryConflict("REVIEW_INPUT_REQUIRED", review_package_id)
        row = rows[0]
        value = {"id": row["id"], "review_package_id": row["package_id"], "pr_url": row["uri"], "recorded_at": row["recorded_at"], **json.loads(row["metadata_json"])}
        if not {"target_package_id", "implementation_attempt_id", "implementation_commit", "base_commit", "contract_sha256", "contract", "validation_evidence"}.issubset(value):
            raise RegistryConflict("REVIEW_INPUT_INVALID", str(row["id"]))
        return value

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
        expected_dispatch_revision: int | None = None,
        operation_id: str | None = None,
    ) -> Lease:
        acquired_at = _normalize_timestamp(acquired_at)
        expires_at = _normalize_timestamp(expires_at)
        if expires_at <= acquired_at:
            raise RegistryConflict("INVALID_LEASE_EXPIRY")
        request = {
            "package_id": package_id,
            "worker_id": worker_id,
            "lease_duration_seconds": (
                datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
                - datetime.fromisoformat(acquired_at.replace("Z", "+00:00"))
            ).total_seconds(),
            "expected_dispatch_revision": expected_dispatch_revision,
        }
        lease_id = (
            str(uuid.uuid5(uuid.NAMESPACE_URL, f"factory-operation:{operation_id}"))
            if operation_id is not None else str(uuid.uuid4())
        )
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                replay = self._operation_replay(
                    connection,
                    operation_id=operation_id,
                    operation_kind="ACQUIRE_LEASE",
                    request=request,
                )
                if replay is not None:
                    connection.rollback()
                    return Lease(**replay)
                expired = self._expire_leases(connection, acquired_at)
                if expired:
                    self._bump_revision(connection)
                    connection.commit()
                    connection.execute("BEGIN IMMEDIATE")
                    replay = self._operation_replay(
                        connection,
                        operation_id=operation_id,
                        operation_kind="ACQUIRE_LEASE",
                        request=request,
                    )
                    if replay is not None:
                        connection.rollback()
                        return Lease(**replay)
                if expected_dispatch_revision is not None:
                    control = connection.execute(
                        """SELECT control.dispatch_mode, control.kill_switch_engaged,
                                  metadata.value AS revision
                           FROM factory_control AS control
                           JOIN registry_metadata AS metadata ON metadata.key='revision'
                           WHERE control.singleton=1"""
                    ).fetchone()
                    if (
                        control is None
                        or control["dispatch_mode"] != "LIVE"
                        or control["kill_switch_engaged"]
                        or int(control["revision"]) != expected_dispatch_revision
                    ):
                        raise RegistryConflict("DISPATCH_NOT_AUTHORIZED")
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
                validate_package_transition(
                    TaskStatus.READY,
                    TaskStatus.ACTIVE,
                    authority=TransitionAuthority.LEASE_ACQUIRE,
                )
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
                allowed_dependency_states = (
                    ("VERIFY_REVIEW", "DONE")
                    if package["kind"] == "REVIEW" else ("DONE",)
                )
                placeholders = ",".join("?" for _ in allowed_dependency_states)
                incomplete = connection.execute(
                    "SELECT dependency_id FROM task_dependencies AS dependency "
                    "JOIN work_packages AS required "
                    "ON required.id=dependency.dependency_id "
                    f"WHERE dependency.package_id=? AND required.status NOT IN ({placeholders})",
                    (package_id, *allowed_dependency_states),
                ).fetchall()
                if incomplete:
                    raise RegistryConflict(
                        "DEPENDENCY_BLOCKED", ",".join(row["dependency_id"] for row in incomplete)
                    )
                if package["kind"] == "REVIEW":
                    targets = connection.execute(
                        "SELECT dependency_id FROM task_dependencies WHERE package_id=?",
                        (package_id,),
                    ).fetchall()
                    if len(targets) != 1:
                        raise RegistryConflict("REVIEW_TARGET_MISMATCH")
                    implementation = connection.execute(
                        """SELECT worker_id FROM attempts
                           WHERE package_id=? AND outcome='SUCCEEDED'
                             AND ended_at IS NOT NULL AND worker_id IS NOT NULL
                           ORDER BY ended_at DESC, started_at DESC, id DESC LIMIT 1""",
                        (targets[0]["dependency_id"],),
                    ).fetchone()
                    if implementation is None:
                        raise RegistryConflict("REVIEW_IMPLEMENTER_PROVENANCE_REQUIRED")
                    if implementation["worker_id"] == worker_id:
                        raise RegistryConflict("REVIEW_INDEPENDENCE_REQUIRED")
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
                result = {
                    "id": lease_id,
                    "package_id": package_id,
                    "worker_id": worker_id,
                    "acquired_at": acquired_at,
                    "expires_at": expires_at,
                    "released_at": None,
                    "release_reason": None,
                }
                self._record_operation(
                    connection,
                    operation_id=operation_id,
                    operation_kind="ACQUIRE_LEASE",
                    request=request,
                    result=result,
                    recorded_at=acquired_at,
                )
                connection.commit()
            except Exception as error:
                connection.rollback()
                self._record_operation_rejection(
                    operation_id=operation_id,
                    operation_kind="ACQUIRE_LEASE",
                    request=request,
                    error=error,
                    recorded_at=acquired_at,
                )
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
        operation_id: str | None = None,
    ) -> None:
        released_at = _normalize_timestamp(released_at)
        request = {
            "lease_id": lease_id,
            "reason": reason,
            "next_status": next_status.value,
        }
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                replay = self._operation_replay(
                    connection,
                    operation_id=operation_id,
                    operation_kind="RELEASE_LEASE",
                    request=request,
                )
                if replay is not None:
                    connection.rollback()
                    return
                expired = self._expire_leases(connection, released_at)
                if expired:
                    self._bump_revision(connection)
                    connection.commit()
                    connection.execute("BEGIN IMMEDIATE")
                    replay = self._operation_replay(
                        connection,
                        operation_id=operation_id,
                        operation_kind="RELEASE_LEASE",
                        request=request,
                    )
                    if replay is not None:
                        connection.rollback()
                        return
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
                validate_package_transition(
                    TaskStatus.ACTIVE,
                    next_status,
                    authority=TransitionAuthority.LEASE_RELEASE,
                )
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
                self._record_operation(
                    connection,
                    operation_id=operation_id,
                    operation_kind="RELEASE_LEASE",
                    request=request,
                    result={"lease_id": lease_id, "status": next_status.value},
                    recorded_at=released_at,
                )
                connection.commit()
            except Exception as error:
                connection.rollback()
                self._record_operation_rejection(
                    operation_id=operation_id,
                    operation_kind="RELEASE_LEASE",
                    request=request,
                    error=error,
                    recorded_at=released_at,
                )
                raise

    def transition_work_package(
        self,
        package_id: str,
        *,
        expected_status: TaskStatus,
        new_status: TaskStatus,
        changed_at: str,
        operation_id: str | None = None,
    ) -> None:
        changed_at = _normalize_timestamp(changed_at)
        if new_status == TaskStatus.ACTIVE:
            raise RegistryConflict("ACTIVE_REQUIRES_LEASE")
        request = {
            "package_id": package_id,
            "expected_status": expected_status.value,
            "new_status": new_status.value,
        }
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                replay = self._operation_replay(
                    connection,
                    operation_id=operation_id,
                    operation_kind="TRANSITION_WORK_PACKAGE",
                    request=request,
                )
                if replay is not None:
                    connection.rollback()
                    return
                if expected_status == TaskStatus.ACTIVE and connection.execute(
                    "SELECT 1 FROM leases WHERE package_id=? AND released_at IS NULL",
                    (package_id,),
                ).fetchone():
                    raise RegistryConflict("ACTIVE_TRANSITION_REQUIRES_LEASE_RELEASE")
                validate_package_transition(
                    expected_status,
                    new_status,
                    authority=TransitionAuthority.DIRECT,
                )
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
                self._record_operation(
                    connection,
                    operation_id=operation_id,
                    operation_kind="TRANSITION_WORK_PACKAGE",
                    request=request,
                    result={"package_id": package_id, "status": new_status.value},
                    recorded_at=changed_at,
                )
                connection.commit()
            except Exception as error:
                connection.rollback()
                self._record_operation_rejection(
                    operation_id=operation_id,
                    operation_kind="TRANSITION_WORK_PACKAGE",
                    request=request,
                    error=error,
                    recorded_at=changed_at,
                )
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

    def record_evidence(
        self, evidence: Evidence, *, operation_id: str | None = None
    ) -> None:
        recorded_at = _normalize_timestamp(evidence.recorded_at)
        request = {
            "id": evidence.id,
            "package_id": evidence.package_id,
            "kind": evidence.kind,
            "uri": evidence.uri,
            "summary": evidence.summary,
            "recorded_at": recorded_at,
            "metadata": dict(evidence.metadata),
        }
        operation_id = operation_id or f"evidence:{evidence.id}"
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                replay = self._operation_replay(
                    connection,
                    operation_id=operation_id,
                    operation_kind="RECORD_EVIDENCE",
                    request=request,
                )
                if replay is not None:
                    connection.rollback()
                    return
                existing = connection.execute(
                    """SELECT package_id, kind, uri, summary, recorded_at, metadata_json
                       FROM evidence WHERE id=?""",
                    (evidence.id,),
                ).fetchone()
                if existing is not None:
                    existing_request = {
                        "id": evidence.id,
                        "package_id": existing["package_id"],
                        "kind": existing["kind"],
                        "uri": existing["uri"],
                        "summary": existing["summary"],
                        "recorded_at": existing["recorded_at"],
                        "metadata": json.loads(existing["metadata_json"]),
                    }
                    if _request_sha256(existing_request) != _request_sha256(request):
                        raise RegistryConflict("EVIDENCE_ID_REUSED", evidence.id)
                    self._record_operation(
                        connection,
                        operation_id=operation_id,
                        operation_kind="RECORD_EVIDENCE",
                        request=request,
                        result={"evidence_id": evidence.id},
                        recorded_at=recorded_at,
                    )
                    self._bump_revision(connection)
                    connection.commit()
                    return
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
                self._record_operation(
                    connection,
                    operation_id=operation_id,
                    operation_kind="RECORD_EVIDENCE",
                    request=request,
                    result={"evidence_id": evidence.id},
                    recorded_at=recorded_at,
                )
                connection.commit()
            except Exception as error:
                connection.rollback()
                self._record_operation_rejection(
                    operation_id=operation_id,
                    operation_kind="RECORD_EVIDENCE",
                    request=request,
                    error=error,
                    recorded_at=recorded_at,
                )
                raise

    def record_review_outcome(
        self,
        outcome: ReviewOutcome,
        *,
        evidence: Evidence | None = None,
        expected_revision: int | None = None,
        operation_id: str | None = None,
    ) -> int:
        """Append one explicit, independently authored review decision."""
        requested_at = _normalize_timestamp(outcome.requested_at)
        decided_at = _normalize_timestamp(outcome.decided_at)
        evidence_recorded_at = (
            _normalize_timestamp(evidence.recorded_at) if evidence is not None else None
        )
        if not isinstance(outcome.state, ReviewOutcomeState):
            raise RegistryConflict("INVALID_REVIEW_OUTCOME", "state")
        if decided_at < requested_at:
            raise RegistryConflict("INVALID_REVIEW_OUTCOME", "decided before requested")
        if outcome.implementer_worker_id == outcome.reviewer_worker_id:
            raise RegistryConflict("REVIEW_INDEPENDENCE_REQUIRED")
        if outcome.state is ReviewOutcomeState.APPROVED and not outcome.approval_evidence_ids:
            raise RegistryConflict("REVIEW_APPROVAL_EVIDENCE_REQUIRED")
        if outcome.state is ReviewOutcomeState.CHANGES_REQUESTED and not outcome.changes_requested:
            raise RegistryConflict("REVIEW_CHANGES_REQUIRED")
        if evidence is not None and (
            evidence.package_id != outcome.review_package_id
            or evidence.kind.lower() != "review"
            or not isinstance(evidence.metadata.get("attempt_id"), str)
            or not evidence.metadata["attempt_id"]
        ):
            raise RegistryConflict("REVIEW_EVIDENCE_MISMATCH", evidence.id)
        request = {
            "outcome": {
                "id": outcome.id,
                "review_package_id": outcome.review_package_id,
                "target_package_id": outcome.target_package_id,
                "implementer_worker_id": outcome.implementer_worker_id,
                "reviewer_worker_id": outcome.reviewer_worker_id,
                "requested_at": requested_at,
                "decided_at": decided_at,
                "state": outcome.state.value,
                "findings": list(outcome.findings),
                "changes_requested": list(outcome.changes_requested),
                "approval_evidence_ids": list(outcome.approval_evidence_ids),
                "reviewed_commit": outcome.reviewed_commit,
                "reviewed_base_commit": outcome.reviewed_base_commit,
                "contract_sha256": outcome.contract_sha256,
                "review_input_evidence_id": outcome.review_input_evidence_id,
                "reviewer_attempt_id": outcome.reviewer_attempt_id,
            },
            "evidence": None if evidence is None else {
                "id": evidence.id,
                "package_id": evidence.package_id,
                "kind": evidence.kind,
                "uri": evidence.uri,
                "summary": evidence.summary,
                "recorded_at": evidence_recorded_at,
                "metadata": dict(evidence.metadata),
            },
            "expected_revision": expected_revision,
        }
        operation_id = operation_id or f"review-outcome:{outcome.id}"
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                replay = self._operation_replay(
                    connection,
                    operation_id=operation_id,
                    operation_kind="RECORD_REVIEW_OUTCOME",
                    request=request,
                )
                if replay is not None:
                    connection.rollback()
                    return int(replay["revision"])
                if expected_revision is not None:
                    self._require_revision(connection, expected_revision)
                if evidence is not None:
                    connection.execute(
                        """INSERT INTO evidence
                           (id, package_id, kind, uri, summary, recorded_at, metadata_json)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (
                            evidence.id, evidence.package_id, evidence.kind,
                            evidence.uri, evidence.summary, evidence_recorded_at,
                            _json(evidence.metadata),
                        ),
                    )
                review_package = connection.execute(
                    "SELECT feature_id, kind, status FROM work_packages WHERE id=?",
                    (outcome.review_package_id,),
                ).fetchone()
                target_package = connection.execute(
                    "SELECT feature_id, status FROM work_packages WHERE id=?",
                    (outcome.target_package_id,),
                ).fetchone()
                if review_package is None:
                    raise RegistryNotFound(f"work package {outcome.review_package_id}")
                if target_package is None:
                    raise RegistryNotFound(f"work package {outcome.target_package_id}")
                if review_package["kind"] != "REVIEW":
                    raise RegistryConflict("REVIEW_PACKAGE_REQUIRED")
                if (
                    review_package["status"] != TaskStatus.VERIFY_REVIEW.value
                    or target_package["status"] != TaskStatus.VERIFY_REVIEW.value
                    or review_package["feature_id"] != target_package["feature_id"]
                ):
                    raise RegistryConflict("REVIEW_OUTCOME_STATUS_INVALID")
                validate_package_transition(
                    TaskStatus.VERIFY_REVIEW,
                    TaskStatus.DONE,
                    authority=TransitionAuthority.REVIEW_OUTCOME,
                )
                dependency = connection.execute(
                    "SELECT 1 FROM task_dependencies WHERE package_id=? AND dependency_id=?",
                    (outcome.review_package_id, outcome.target_package_id),
                ).fetchone()
                if dependency is None:
                    raise RegistryConflict("REVIEW_TARGET_MISMATCH")
                target_attempts = connection.execute(
                    """SELECT id, worker_id, started_at, ended_at, outcome
                       FROM attempts WHERE package_id=?
                       ORDER BY started_at, id""",
                    (outcome.target_package_id,),
                ).fetchall()
                successful_implementation_attempts = [
                    attempt for attempt in target_attempts
                    if attempt["worker_id"] is not None
                    and attempt["outcome"] == "SUCCEEDED"
                    and attempt["ended_at"] is not None
                    and attempt["ended_at"] <= requested_at
                ]
                if not successful_implementation_attempts:
                    raise RegistryConflict("REVIEW_IMPLEMENTER_PROVENANCE_REQUIRED")
                actual_implementation = max(
                    successful_implementation_attempts,
                    key=lambda attempt: (
                        attempt["ended_at"], attempt["started_at"], attempt["id"],
                    ),
                )
                if actual_implementation["worker_id"] != outcome.implementer_worker_id:
                    raise RegistryConflict("REVIEW_IMPLEMENTER_MISMATCH")
                if any(
                    attempt["worker_id"] == outcome.reviewer_worker_id
                    for attempt in target_attempts
                ):
                    raise RegistryConflict("REVIEWER_IMPLEMENTED_TARGET")
                if any(
                    attempt["started_at"] <= decided_at
                    and (
                        attempt["ended_at"] is None
                        or attempt["ended_at"] > requested_at
                    )
                    for attempt in target_attempts
                ):
                    raise RegistryConflict("REVIEW_TARGET_CHANGED_DURING_REVIEW")
                reviewer = connection.execute(
                    "SELECT capabilities_json, approved_lanes_json FROM workers WHERE id=?",
                    (outcome.reviewer_worker_id,),
                ).fetchone()
                if reviewer is None:
                    raise RegistryNotFound(f"worker {outcome.reviewer_worker_id}")
                reviewer_capabilities = {item.lower() for item in json.loads(reviewer["capabilities_json"])}
                reviewer_lanes = set(json.loads(reviewer["approved_lanes_json"]))
                if "review" not in reviewer_capabilities and "ASSURANCE" not in reviewer_lanes:
                    raise RegistryConflict("REVIEWER_NOT_ELIGIBLE")
                reviewer_attempts = connection.execute(
                    """SELECT id, started_at, ended_at FROM attempts
                       WHERE package_id=? AND worker_id=? AND outcome='SUCCEEDED'
                         AND ended_at IS NOT NULL AND started_at>=? AND ended_at<=?
                       ORDER BY ended_at, started_at, id""",
                    (
                        outcome.review_package_id, outcome.reviewer_worker_id,
                        requested_at, decided_at,
                    ),
                ).fetchall()
                if not reviewer_attempts:
                    raise RegistryConflict("REVIEWER_ATTEMPT_REQUIRED")
                reviewer_attempt = reviewer_attempts[-1]
                if not all(isinstance(value, str) and value for value in (outcome.reviewed_commit, outcome.reviewed_base_commit, outcome.contract_sha256, outcome.review_input_evidence_id, outcome.reviewer_attempt_id)):
                    raise RegistryConflict("REVIEW_PROVENANCE_REQUIRED")
                if reviewer_attempt["id"] != outcome.reviewer_attempt_id:
                    raise RegistryConflict("REVIEWER_ATTEMPT_MISMATCH")
                input_evidence = connection.execute("SELECT package_id, metadata_json FROM evidence WHERE id=? AND kind='review-input'", (outcome.review_input_evidence_id,)).fetchone()
                if input_evidence is None or input_evidence["package_id"] != outcome.review_package_id:
                    raise RegistryConflict("REVIEW_INPUT_REQUIRED")
                review_input = json.loads(input_evidence["metadata_json"])
                if (review_input.get("target_package_id") != outcome.target_package_id or review_input.get("implementation_attempt_id") != actual_implementation["id"] or review_input.get("implementation_commit") != outcome.reviewed_commit or review_input.get("base_commit") != outcome.reviewed_base_commit or review_input.get("contract_sha256") != outcome.contract_sha256 or _request_sha256(review_input.get("contract", {})) != outcome.contract_sha256 or not review_input.get("validation_evidence")):
                    raise RegistryConflict("REVIEW_INPUT_MISMATCH")
                for evidence_id in outcome.approval_evidence_ids:
                    evidence = connection.execute(
                        """SELECT package_id, kind, recorded_at, metadata_json
                           FROM evidence WHERE id=?""",
                        (evidence_id,),
                    ).fetchone()
                    if evidence is None:
                        raise RegistryNotFound(f"evidence {evidence_id}")
                    evidence_metadata = json.loads(evidence["metadata_json"])
                    if (
                        evidence["kind"].lower() != "review"
                        or evidence["package_id"] != outcome.review_package_id
                        or evidence_metadata.get("attempt_id") != reviewer_attempt["id"]
                        or evidence_metadata.get("reviewed_commit") != outcome.reviewed_commit
                        or evidence_metadata.get("reviewed_base_commit") != outcome.reviewed_base_commit
                        or evidence_metadata.get("contract_sha256") != outcome.contract_sha256
                        or evidence_metadata.get("review_input_evidence_id") != outcome.review_input_evidence_id
                        or evidence["recorded_at"] < reviewer_attempt["started_at"]
                        or evidence["recorded_at"] > decided_at
                    ):
                        raise RegistryConflict("REVIEW_EVIDENCE_MISMATCH", evidence_id)
                connection.execute(
                    """INSERT INTO review_outcomes
                       (id, review_package_id, target_package_id,
                        implementer_worker_id, reviewer_worker_id,
                        requested_at, decided_at, state, findings_json,
                        changes_requested_json, approval_evidence_ids_json)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        outcome.id, outcome.review_package_id, outcome.target_package_id,
                        outcome.implementer_worker_id, outcome.reviewer_worker_id,
                        requested_at, decided_at, outcome.state.value,
                        _json(outcome.findings), _json(outcome.changes_requested),
                        _json(outcome.approval_evidence_ids),
                    ),
                )
                connection.execute(
                    "UPDATE work_packages SET status='DONE', updated_at=? WHERE id=?",
                    (decided_at, outcome.review_package_id),
                )
                if outcome.state is ReviewOutcomeState.APPROVED:
                    connection.execute(
                        "UPDATE work_packages SET status='DONE', updated_at=? WHERE id=?",
                        (decided_at, outcome.target_package_id),
                    )
                    connection.execute(
                        """UPDATE work_packages SET status='DONE', updated_at=?
                           WHERE kind='REVIEW' AND status='VERIFY_REVIEW'
                             AND id IN (
                               SELECT review_package_id FROM review_outcomes
                               WHERE target_package_id=?
                             )""",
                        (decided_at, outcome.target_package_id),
                    )
                    remaining = connection.execute(
                        "SELECT 1 FROM work_packages WHERE feature_id=? AND status!='DONE' LIMIT 1",
                        (review_package["feature_id"],),
                    ).fetchone()
                    if remaining is None:
                        connection.execute(
                            "UPDATE features SET status='DONE', updated_at=? WHERE id=?",
                            (decided_at, review_package["feature_id"]),
                        )
                self._insert_event(
                    connection, "REVIEW_OUTCOME_RECORDED", decided_at,
                    outcome.target_package_id, outcome.reviewer_worker_id, None,
                    {
                        "review_package_id": outcome.review_package_id,
                        "outcome_id": outcome.id,
                        "state": outcome.state.value,
                        "evidence_ids": list(outcome.approval_evidence_ids),
                        "reviewed_commit": outcome.reviewed_commit,
                        "review_input_evidence_id": outcome.review_input_evidence_id,
                        "summary": f"Independent review recorded {outcome.state.value.lower().replace('_', ' ')}.",
                    },
                )
                revision = self._bump_revision(connection)
                self._record_operation(
                    connection,
                    operation_id=operation_id,
                    operation_kind="RECORD_REVIEW_OUTCOME",
                    request=request,
                    result={"revision": revision, "outcome_id": outcome.id},
                    recorded_at=decided_at,
                )
                connection.commit()
                return revision
            except sqlite3.IntegrityError as error:
                connection.rollback()
                conflict = RegistryConflict("REVIEW_OUTCOME_CONFLICT", str(error))
                self._record_operation_rejection(
                    operation_id=operation_id,
                    operation_kind="RECORD_REVIEW_OUTCOME",
                    request=request,
                    error=conflict,
                    recorded_at=decided_at,
                )
                raise conflict from error
            except Exception as error:
                connection.rollback()
                self._record_operation_rejection(
                    operation_id=operation_id,
                    operation_kind="RECORD_REVIEW_OUTCOME",
                    request=request,
                    error=error,
                    recorded_at=decided_at,
                )
                raise

    def register_attempt(self, attempt: Attempt) -> None:
        """Append an attempt identity before autonomous invocation telemetry."""
        started_at = _normalize_timestamp(attempt.started_at)
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                package = connection.execute(
                    "SELECT 1 FROM work_packages WHERE id=?", (attempt.package_id,)
                ).fetchone()
                if package is None:
                    raise RegistryNotFound(f"work package {attempt.package_id}")
                if attempt.worker_id is not None and connection.execute(
                    "SELECT 1 FROM workers WHERE id=?", (attempt.worker_id,)
                ).fetchone() is None:
                    raise RegistryNotFound(f"worker {attempt.worker_id}")
                if attempt.lease_id is not None:
                    lease = connection.execute(
                        "SELECT package_id, worker_id FROM leases WHERE id=?",
                        (attempt.lease_id,),
                    ).fetchone()
                    if lease is None:
                        raise RegistryNotFound(f"lease {attempt.lease_id}")
                    if lease["package_id"] != attempt.package_id or (
                        attempt.worker_id is not None
                        and lease["worker_id"] != attempt.worker_id
                    ):
                        raise RegistryConflict("ATTEMPT_LEASE_MISMATCH")
                connection.execute(
                    """INSERT INTO attempts
                       (id, package_id, worker_id, lease_id, started_at,
                        provider_diagnostics_json)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        attempt.id,
                        attempt.package_id,
                        attempt.worker_id,
                        attempt.lease_id,
                        started_at,
                        _json(attempt.provider_diagnostics),
                    ),
                )
                self._insert_event(
                    connection,
                    "ATTEMPT_STARTED",
                    started_at,
                    attempt.package_id,
                    attempt.worker_id,
                    attempt.id,
                    {"lease_id": attempt.lease_id},
                )
                self._bump_revision(connection)
                connection.commit()
            except sqlite3.IntegrityError as error:
                connection.rollback()
                raise RegistryConflict("ATTEMPT_CONFLICT", str(error)) from error
            except Exception:
                connection.rollback()
                raise

    @staticmethod
    def _validate_usage_entry(entry: UsageLedgerEntry) -> None:
        required = {
            "id": entry.id,
            "provider": entry.provider,
            "worker_id": entry.worker_id,
            "account_id": entry.account_id,
            "invocation_id": entry.invocation_id,
            "session_id": entry.session_id,
            "outcome": entry.outcome,
            "source_identity": entry.source_identity,
        }
        missing = sorted(key for key, value in required.items() if not str(value).strip())
        if missing:
            raise RegistryConflict("INVALID_USAGE_ENTRY", ",".join(missing))
        if not isinstance(entry.source_type, UsageSource):
            raise RegistryConflict("INVALID_USAGE_ENTRY", "source_type")
        if entry.outcome not in {"SUCCEEDED", "FAILED", "LIMITED"}:
            raise RegistryConflict("INVALID_USAGE_ENTRY", "outcome")
        if entry.limit_signal not in {None, "RATE_LIMIT", "EXHAUSTION", "THROTTLING"}:
            raise RegistryConflict("INVALID_USAGE_ENTRY", "limit_signal")
        if not isinstance(entry.task_completed, bool) or not isinstance(
            entry.review_completed, bool
        ):
            raise RegistryConflict("INVALID_USAGE_ENTRY", "completion flags")
        if not isinstance(entry.observation_class, UsageObservationClass):
            raise RegistryConflict("INVALID_USAGE_ENTRY", "observation_class")
        if entry.observation_class is UsageObservationClass.LEGACY_UNCLASSIFIED:
            raise RegistryConflict("LEGACY_USAGE_CLASS_RESERVED")
        if entry.observation_class is UsageObservationClass.AUTONOMOUS:
            if not entry.package_id or not entry.attempt_id:
                raise RegistryConflict(
                    "USAGE_PROVENANCE_REQUIRED", "package_id,attempt_id"
                )
        elif entry.package_id is not None or entry.attempt_id is not None:
            raise RegistryConflict(
                "DIAGNOSTIC_PROVENANCE_FORBIDDEN", "package_id,attempt_id"
            )
        if entry.observation_class is UsageObservationClass.DIAGNOSTIC and (
            entry.task_completed or entry.review_completed
        ):
            raise RegistryConflict("DIAGNOSTIC_COMPLETION_FORBIDDEN")
        for key in (
            "input_tokens",
            "output_tokens",
            "cache_read_input_tokens",
            "cache_creation_input_tokens",
            "duration_ms",
        ):
            value = getattr(entry, key)
            if value is not None and (isinstance(value, bool) or value < 0):
                raise RegistryConflict("INVALID_USAGE_MEASUREMENT", key)
        if entry.limit_raw_error and not entry.limit_signal:
            raise RegistryConflict("LIMIT_ERROR_REQUIRES_SIGNAL")
        if (entry.outcome == "LIMITED") != bool(entry.limit_signal):
            raise RegistryConflict("LIMIT_OUTCOME_MISMATCH")

    @staticmethod
    def _usage_observation(
        entry: UsageLedgerEntry,
        *,
        observed_at: str,
        reset_at: str | None,
        calibration_metadata: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        return {
            "observation_class": entry.observation_class.value,
            "package_id": entry.package_id,
            "attempt_id": entry.attempt_id,
            "observed_at": observed_at,
            "model_diagnostic": entry.model_diagnostic,
            "input_tokens": entry.input_tokens,
            "output_tokens": entry.output_tokens,
            "cache_read_input_tokens": entry.cache_read_input_tokens,
            "cache_creation_input_tokens": entry.cache_creation_input_tokens,
            "duration_ms": entry.duration_ms,
            "duration_basis": entry.source_metadata.get(
                "duration_basis",
                "provider_result" if entry.source_type is not UsageSource.TRANSCRIPT
                else "first_to_last_timestamp",
            ),
            "outcome": entry.outcome,
            "task_completed": bool(entry.task_completed),
            "review_completed": bool(entry.review_completed),
            "limit_signal": entry.limit_signal,
            "limit_reset_at": reset_at,
            "limit_raw_error": entry.limit_raw_error,
            "calibration_metadata": dict(calibration_metadata),
        }

    @staticmethod
    def _validate_usage_merge(
        existing: sqlite3.Row,
        sources: Sequence[sqlite3.Row],
        entry: UsageLedgerEntry,
        observation: Mapping[str, Any],
    ) -> None:
        if existing["observation_class"] != entry.observation_class.value:
            raise RegistryConflict("USAGE_SOURCE_MISMATCH", "observation_class")
        for key in ("session_id", "package_id", "attempt_id"):
            if existing[key] != getattr(entry, key):
                raise RegistryConflict("USAGE_SOURCE_MISMATCH", key)
        observations = [
            json.loads(source["metadata_json"]).get("observation", {})
            for source in sources
        ]
        for prior in observations:
            for key in (
                "input_tokens",
                "output_tokens",
                "cache_read_input_tokens",
                "cache_creation_input_tokens",
            ):
                if (
                    prior.get(key) is not None
                    and observation.get(key) is not None
                    and prior[key] != observation[key]
                ):
                    raise RegistryConflict("USAGE_SOURCE_MISMATCH", key)
            prior_model = prior.get("model_diagnostic")
            model = observation.get("model_diagnostic")
            if prior_model and model and set(prior_model.split(",")) != set(model.split(",")):
                raise RegistryConflict("USAGE_SOURCE_MISMATCH", "model_diagnostic")
            if (
                prior.get("duration_basis") == observation.get("duration_basis")
                and prior.get("duration_ms") is not None
                and observation.get("duration_ms") is not None
                and prior["duration_ms"] != observation["duration_ms"]
            ):
                raise RegistryConflict("USAGE_SOURCE_MISMATCH", "duration_ms")
            prior_signal = prior.get("limit_signal")
            signal = observation.get("limit_signal")
            if prior_signal and signal and prior_signal != signal:
                raise RegistryConflict("USAGE_SOURCE_MISMATCH", "limit_signal")
            if (
                prior_signal
                and signal
                and prior.get("limit_reset_at") is not None
                and observation.get("limit_reset_at") is not None
                and prior["limit_reset_at"] != observation["limit_reset_at"]
            ):
                raise RegistryConflict("USAGE_SOURCE_MISMATCH", "limit_reset_at")
            if not prior_signal and not signal and prior.get("outcome") != observation.get("outcome"):
                raise RegistryConflict("USAGE_SOURCE_MISMATCH", "outcome")

    def record_usage(self, entry: UsageLedgerEntry) -> UsageLedgerWrite:
        """Append one invocation and retain secondary source provenance.

        The provider/worker/account/invocation tuple is the counting identity.
        A transcript observed after its CLI result adds a source row but never a
        second counted invocation.
        """
        self._validate_usage_entry(entry)
        observed_at = _normalize_timestamp(entry.observed_at)
        reset_at = _normalize_timestamp(entry.limit_reset_at) if entry.limit_reset_at else None
        created_at = _utc_now()
        calibration_metadata = dict(entry.calibration_metadata)
        if entry.limit_signal and "factory_measured_before_limit" not in calibration_metadata:
            end = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
            prior_rows = [
                row
                for row in self.usage_entries(
                    worker_id=entry.worker_id,
                    since=_normalize_timestamp((end - timedelta(days=7)).isoformat()),
                    through=observed_at,
                )
                if not (
                    row["provider"] == entry.provider
                    and row["account_id"] == entry.account_id
                    and row["invocation_id"] == entry.invocation_id
                )
            ]
            calibration_metadata["factory_measured_before_limit"] = {
                "rolling_24h": self._usage_totals(
                    [
                        row
                        for row in prior_rows
                        if datetime.fromisoformat(
                            row["observed_at"].replace("Z", "+00:00")
                        )
                        >= end - timedelta(hours=24)
                    ]
                ),
                "rolling_7d": self._usage_totals(prior_rows),
            }
        source_metadata = {
            **entry.source_metadata,
            "observed_measurements": {
                "input_tokens": entry.input_tokens,
                "output_tokens": entry.output_tokens,
                "cache_read_input_tokens": entry.cache_read_input_tokens,
                "cache_creation_input_tokens": entry.cache_creation_input_tokens,
                "duration_ms": entry.duration_ms,
                "outcome": entry.outcome,
                "model_diagnostic": entry.model_diagnostic,
            },
            "observation": self._usage_observation(
                entry,
                observed_at=observed_at,
                reset_at=reset_at,
                calibration_metadata=calibration_metadata,
            ),
        }
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                if entry.observation_class is UsageObservationClass.AUTONOMOUS:
                    attempt = connection.execute(
                        "SELECT package_id, worker_id FROM attempts WHERE id=?",
                        (entry.attempt_id,),
                    ).fetchone()
                    if attempt is None:
                        raise RegistryNotFound(f"attempt {entry.attempt_id}")
                    if attempt["package_id"] != entry.package_id:
                        raise RegistryConflict("USAGE_ATTEMPT_PACKAGE_MISMATCH")
                    if (
                        attempt["worker_id"] is not None
                        and attempt["worker_id"] != entry.worker_id
                    ):
                        raise RegistryConflict("USAGE_ATTEMPT_WORKER_MISMATCH")
                existing_source = connection.execute(
                    """SELECT source.ledger_id, source.metadata_json,
                              ledger.provider, ledger.worker_id,
                              ledger.account_id, ledger.invocation_id, ledger.session_id,
                              ledger.package_id, ledger.attempt_id, ledger.observation_class
                       FROM usage_ledger_sources AS source
                       JOIN usage_ledger AS ledger ON ledger.id=source.ledger_id
                       WHERE source.source_identity=?""",
                    (entry.source_identity,),
                ).fetchone()
                if existing_source:
                    for key in (
                        "provider", "worker_id", "account_id", "invocation_id",
                        "session_id", "package_id", "attempt_id",
                    ):
                        if existing_source[key] != getattr(entry, key):
                            raise RegistryConflict("USAGE_SOURCE_MISMATCH", key)
                    if existing_source["observation_class"] != entry.observation_class.value:
                        raise RegistryConflict("USAGE_SOURCE_MISMATCH", "observation_class")
                    stored_observation = json.loads(
                        existing_source["metadata_json"]
                    ).get("observation", {})
                    for key in (
                        "model_diagnostic", "input_tokens", "output_tokens",
                        "cache_read_input_tokens", "cache_creation_input_tokens",
                        "duration_ms", "duration_basis", "outcome", "task_completed",
                        "review_completed", "limit_signal", "limit_reset_at",
                        "limit_raw_error",
                    ):
                        if stored_observation.get(key) != source_metadata["observation"].get(key):
                            raise RegistryConflict("USAGE_SOURCE_MISMATCH", key)
                    connection.rollback()
                    return UsageLedgerWrite(existing_source["ledger_id"], False, False)
                existing = connection.execute(
                    """SELECT *
                       FROM usage_ledger
                       WHERE provider=? AND worker_id=? AND account_id=? AND invocation_id=?""",
                    (entry.provider, entry.worker_id, entry.account_id, entry.invocation_id),
                ).fetchone()
                if existing:
                    existing_sources = connection.execute(
                        "SELECT source_type, metadata_json FROM usage_ledger_sources "
                        "WHERE ledger_id=? ORDER BY observed_at, id",
                        (existing["id"],),
                    ).fetchall()
                    self._validate_usage_merge(
                        existing, existing_sources, entry, source_metadata["observation"]
                    )
                    source_id = str(uuid.uuid4())
                    connection.execute(
                        """INSERT INTO usage_ledger_sources
                           (id, ledger_id, source_type, source_identity, observed_at, metadata_json)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (
                            source_id,
                            existing["id"],
                            entry.source_type.value,
                            entry.source_identity,
                            observed_at,
                            _json(source_metadata),
                        ),
                    )
                    self._insert_event(
                        connection,
                        "USAGE_SOURCE_DEDUPLICATED",
                        observed_at,
                        entry.package_id,
                        entry.worker_id,
                        entry.attempt_id,
                        {
                            "ledger_id": existing["id"],
                            "source_type": entry.source_type.value,
                        },
                    )
                    self._bump_revision(connection)
                    connection.commit()
                    return UsageLedgerWrite(existing["id"], False, True)
                connection.execute(
                    """INSERT INTO usage_ledger
                       (id, provider, worker_id, account_id, invocation_id, session_id,
                        observation_class, package_id, attempt_id, observed_at, model_diagnostic,
                        input_tokens, output_tokens, cache_read_input_tokens,
                        cache_creation_input_tokens, duration_ms, outcome,
                        task_completed, review_completed, limit_signal, limit_reset_at,
                        limit_raw_error, calibration_metadata_json, primary_source_type,
                        primary_source_identity, primary_source_metadata_json, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                               ?, ?, ?, ?, ?, ?)""",
                    (
                        entry.id,
                        entry.provider,
                        entry.worker_id,
                        entry.account_id,
                        entry.invocation_id,
                        entry.session_id,
                        entry.observation_class.value,
                        entry.package_id,
                        entry.attempt_id,
                        observed_at,
                        entry.model_diagnostic,
                        entry.input_tokens,
                        entry.output_tokens,
                        entry.cache_read_input_tokens,
                        entry.cache_creation_input_tokens,
                        entry.duration_ms,
                        entry.outcome,
                        int(entry.task_completed),
                        int(entry.review_completed),
                        entry.limit_signal,
                        reset_at,
                        entry.limit_raw_error,
                        _json(calibration_metadata),
                        entry.source_type.value,
                        entry.source_identity,
                        _json(source_metadata),
                        created_at,
                    ),
                )
                connection.execute(
                    """INSERT INTO usage_ledger_sources
                       (id, ledger_id, source_type, source_identity, observed_at, metadata_json)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        str(uuid.uuid4()),
                        entry.id,
                        entry.source_type.value,
                        entry.source_identity,
                        observed_at,
                        _json(source_metadata),
                    ),
                )
                self._insert_event(
                    connection,
                    "USAGE_RECORDED",
                    observed_at,
                    entry.package_id,
                    entry.worker_id,
                    entry.attempt_id,
                    {
                        "ledger_id": entry.id,
                        "provider": entry.provider,
                        "outcome": entry.outcome,
                        "limit_signal": entry.limit_signal,
                    },
                )
                self._bump_revision(connection)
                connection.commit()
                return UsageLedgerWrite(entry.id, True, True)
            except sqlite3.IntegrityError as error:
                connection.rollback()
                raise RegistryConflict("USAGE_LEDGER_CONFLICT", str(error)) from error
            except Exception:
                connection.rollback()
                raise

    @staticmethod
    def _canonical_usage_entry(
        item: dict[str, Any], sources: Sequence[Mapping[str, Any]]
    ) -> dict[str, Any]:
        observations = [
            (source["source_type"], source["source_identity"], source["metadata"].get("observation"))
            for source in sources
            if isinstance(source["metadata"].get("observation"), Mapping)
        ]
        if not observations:
            return item
        priority = {
            UsageSource.CLI_JSON.value: 2,
            UsageSource.CLI_STREAM_JSON.value: 2,
            UsageSource.TRANSCRIPT.value: 1,
        }
        ordered = sorted(
            observations,
            key=lambda value: (-priority.get(value[0], 0), value[0], value[1]),
        )
        values = [value[2] for value in ordered]
        for key in (
            "input_tokens",
            "output_tokens",
            "cache_read_input_tokens",
            "cache_creation_input_tokens",
            "model_diagnostic",
        ):
            item[key] = next(
                (value[key] for value in values if value.get(key) is not None), None
            )
        duration = next(
            (value for value in values if value.get("duration_ms") is not None), None
        )
        item["duration_ms"] = duration.get("duration_ms") if duration else None
        item["duration_basis"] = duration.get("duration_basis") if duration else None
        item["observed_at"] = max(value["observed_at"] for value in values)
        item["task_completed"] = any(bool(value.get("task_completed")) for value in values)
        item["review_completed"] = any(bool(value.get("review_completed")) for value in values)
        limited = [value for value in values if value.get("limit_signal")]
        if limited:
            item["outcome"] = "LIMITED"
            for key in ("limit_signal", "limit_reset_at", "limit_raw_error"):
                item[key] = next(
                    (value[key] for value in limited if value.get(key) is not None),
                    None,
                )
            item["calibration_metadata"] = dict(
                next(
                    (
                        value["calibration_metadata"]
                        for value in limited
                        if value.get("calibration_metadata")
                    ),
                    {},
                )
            )
        else:
            item["outcome"] = values[0].get("outcome", item["outcome"])
            item["limit_signal"] = None
            item["limit_reset_at"] = None
            item["limit_raw_error"] = None
        return item

    def usage_entries(
        self,
        *,
        worker_id: str | None = None,
        since: str | None = None,
        through: str | None = None,
    ) -> Sequence[Mapping[str, Any]]:
        clauses: list[str] = []
        parameters: list[Any] = []
        if worker_id is not None:
            clauses.append("worker_id=?")
            parameters.append(worker_id)
        normalized_since = _normalize_timestamp(since) if since is not None else None
        normalized_through = _normalize_timestamp(through) if through is not None else None
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connection() as connection:
            rows = connection.execute(
                f"SELECT * FROM usage_ledger {where} ORDER BY observed_at, id", parameters
            ).fetchall()
            sources = connection.execute(
                """SELECT ledger_id, source_type, source_identity, observed_at, metadata_json
                   FROM usage_ledger_sources ORDER BY observed_at, id"""
            ).fetchall()
        by_ledger: dict[str, list[Mapping[str, Any]]] = {}
        for source in sources:
            by_ledger.setdefault(source["ledger_id"], []).append(
                {
                    "source_type": source["source_type"],
                    "source_identity": source["source_identity"],
                    "observed_at": source["observed_at"],
                    "metadata": json.loads(source["metadata_json"]),
                }
            )
        entries = []
        for row in rows:
            item = dict(row)
            item["task_completed"] = bool(item["task_completed"])
            item["review_completed"] = bool(item["review_completed"])
            item["calibration_metadata"] = json.loads(
                item.pop("calibration_metadata_json")
            )
            item["primary_source_metadata"] = json.loads(
                item.pop("primary_source_metadata_json")
            )
            item["sources"] = by_ledger.get(item["id"], [])
            item = self._canonical_usage_entry(item, item["sources"])
            if normalized_since is not None and item["observed_at"] < normalized_since:
                continue
            if normalized_through is not None and item["observed_at"] > normalized_through:
                continue
            entries.append(item)
        return sorted(entries, key=lambda value: (value["observed_at"], value["id"]))

    @staticmethod
    def _usage_totals(rows: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
        token_fields = (
            "input_tokens",
            "output_tokens",
            "cache_read_input_tokens",
            "cache_creation_input_tokens",
        )
        totals: dict[str, Any] = {"invocations": len(rows)}
        for field in token_fields:
            values = [row[field] for row in rows if row[field] is not None]
            totals[field] = sum(values) if values else None
        measured = [
            sum(row[field] or 0 for field in token_fields)
            for row in rows
            if any(row[field] is not None for field in token_fields)
        ]
        totals["measured_tokens"] = sum(measured) if measured else None
        durations = [row["duration_ms"] for row in rows if row["duration_ms"] is not None]
        totals["productive_runtime_seconds"] = (
            sum(durations) / 1000 if durations else None
        )
        totals["tasks_completed"] = sum(bool(row["task_completed"]) for row in rows)
        totals["review_throughput"] = sum(bool(row["review_completed"]) for row in rows)
        return totals

    def usage_analytics(
        self,
        worker_id: str,
        *,
        observed_at: str,
    ) -> Mapping[str, Any]:
        observed_at = _normalize_timestamp(observed_at)
        end = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
        start_7d = end - timedelta(days=7)
        start_24h = end - timedelta(hours=24)
        rows = list(
            self.usage_entries(
                worker_id=worker_id,
                since=_normalize_timestamp(start_7d.isoformat()),
                through=observed_at,
            )
        )
        rows_24h = [
            row
            for row in rows
            if datetime.fromisoformat(row["observed_at"].replace("Z", "+00:00")) >= start_24h
        ]
        totals_24h = dict(self._usage_totals(rows_24h))
        totals_7d = dict(self._usage_totals(rows))
        runtime_hours = (totals_7d["productive_runtime_seconds"] or 0) / 3600
        output_tokens = totals_7d["output_tokens"]
        output_per_hour = (
            output_tokens / runtime_hours
            if output_tokens is not None and runtime_hours > 0
            else None
        )
        completed_tasks = totals_7d["tasks_completed"]
        average_tokens = (
            totals_7d["measured_tokens"] / completed_tasks
            if totals_7d["measured_tokens"] is not None and completed_tasks > 0
            else None
        )
        by_day = []
        for offset in range(6, -1, -1):
            day = (end - timedelta(days=offset)).date()
            day_rows = [
                row
                for row in rows
                if datetime.fromisoformat(row["observed_at"].replace("Z", "+00:00")).date()
                == day
            ]
            by_day.append(
                {
                    "date": day.isoformat(),
                    "tasks_completed": sum(bool(row["task_completed"]) for row in day_rows),
                    "reviews_completed": sum(bool(row["review_completed"]) for row in day_rows),
                }
            )
        limits = [
            {
                "observed_at": row["observed_at"],
                "signal": row["limit_signal"],
                "reset_at": row["limit_reset_at"],
                "raw_error": row["limit_raw_error"],
                "rolling_consumption": row["calibration_metadata"],
            }
            for row in rows
            if row["limit_signal"]
        ]
        return {
            "worker_id": worker_id,
            "observed_at": observed_at,
            "measurement_kind": "FACTORY_MEASURED_CONSUMPTION",
            "provider_reported_percent": None,
            "inferred_capacity_percent": None,
            "rolling_24h": totals_24h,
            "rolling_7d": totals_7d,
            "tasks_completed_by_day": by_day,
            "average_measured_tokens_per_completed_task_7d": average_tokens,
            "output_tokens_per_productive_hour_7d": output_per_hour,
            "limit_events_7d": limits,
        }

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
                diagnostics = item["provider_diagnostics"]
                item["capacity_mode"] = diagnostics.get("capacity_mode", "percentage")
                item["capacity_scopes"] = diagnostics.get("capacity_scopes", ("default",))
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
                diagnostics = item["provider_diagnostics"]
                for key in (
                    "capacity_mode", "capacity_scope", "service_state",
                    "authentication_state", "live_invocation_state", "limit_signal",
                ):
                    if key in diagnostics:
                        item[key] = diagnostics[key]
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

    def control_center_snapshot(self, *, observed_at: str) -> ControlCenterReadSnapshot:
        """Read every Control Center source at one revision without mutation."""
        observed_at = _normalize_timestamp(observed_at)
        with self._connection() as connection:
            connection.execute("PRAGMA query_only = ON")
            connection.execute("BEGIN")
            metadata = {
                row["key"]: row["value"]
                for row in connection.execute("SELECT key, value FROM registry_metadata")
            }

            def decoded_rows(query: str, json_fields: Sequence[str] = ()) -> tuple[Mapping[str, Any], ...]:
                records = []
                for row in connection.execute(query).fetchall():
                    item = dict(row)
                    for field in json_fields:
                        item[field.removesuffix("_json")] = json.loads(item.pop(field))
                    records.append(item)
                return tuple(records)

            tables = {
                row["name"]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            usage_invocations = (
                decoded_rows(
                    "SELECT * FROM usage_ledger ORDER BY observed_at, id",
                    (
                        "calibration_metadata_json",
                        "primary_source_metadata_json",
                    ),
                )
                if "usage_ledger" in tables else ()
            )
            usage_sources = (
                decoded_rows(
                    "SELECT * FROM usage_ledger_sources ORDER BY observed_at, id",
                    ("metadata_json",),
                )
                if "usage_ledger_sources" in tables else ()
            )
            snapshot = ControlCenterReadSnapshot(
                revision=int(metadata["revision"]),
                observed_at=observed_at,
                active_parent_limit=int(metadata["active_parent_limit"]),
                orchestra_reserve_percent=float(metadata["orchestra_reserve_percent"]),
                features=decoded_rows(
                    "SELECT * FROM features ORDER BY priority DESC, created_at, id"
                ),
                work_packages=decoded_rows(
                    "SELECT * FROM work_packages "
                    "ORDER BY priority DESC, COALESCE(ready_at, created_at), id",
                    (
                        "required_capabilities_json",
                        "acceptance_criteria_json",
                        "provider_diagnostics_json",
                        "usage_consumption_json",
                    ),
                ),
                dependencies=decoded_rows(
                    "SELECT package_id, dependency_id FROM task_dependencies "
                    "ORDER BY package_id, dependency_id"
                ),
                workers=decoded_rows(
                    "SELECT * FROM workers ORDER BY id",
                    (
                        "capabilities_json",
                        "approved_lanes_json",
                        "provider_diagnostics_json",
                    ),
                ),
                leases=decoded_rows(
                    "SELECT * FROM leases ORDER BY acquired_at, id"
                ),
                attempts=decoded_rows(
                    "SELECT * FROM attempts ORDER BY started_at, id",
                    ("provider_diagnostics_json",),
                ),
                evidence=decoded_rows(
                    "SELECT * FROM evidence ORDER BY recorded_at, id",
                    ("metadata_json",),
                ),
                review_outcomes=(
                    decoded_rows(
                        "SELECT * FROM review_outcomes ORDER BY decided_at, id",
                        (
                            "findings_json", "changes_requested_json",
                            "approval_evidence_ids_json",
                        ),
                    )
                    if "review_outcomes" in tables else ()
                ),
                usage_observations=decoded_rows(
                    "SELECT * FROM usage_observations ORDER BY observed_at, id",
                    ("provider_diagnostics_json",),
                ),
                usage_invocations=usage_invocations,
                usage_sources=usage_sources,
                failures=decoded_rows(
                    "SELECT * FROM failure_observations ORDER BY observed_at, id",
                    ("metadata_json",),
                ),
                events=decoded_rows(
                    "SELECT * FROM task_events ORDER BY recorded_at, id",
                    ("detail_json",),
                ),
                preservation_imports=decoded_rows(
                    "SELECT id, source_sha256, imported_at, reconciliation_json "
                    "FROM preservation_imports ORDER BY imported_at, id",
                    ("reconciliation_json",),
                ),
                preserved_artifacts=decoded_rows(
                    "SELECT * FROM preserved_artifacts ORDER BY kind, external_identity, id",
                    ("metadata_json",),
                ),
            )
            connection.commit()
        return snapshot
