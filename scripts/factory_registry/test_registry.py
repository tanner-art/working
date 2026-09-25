from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from scripts.factory_registry import (
    Attempt,
    Feature,
    Lane,
    PackageCapacityRisk,
    PackageCapacitySize,
    RegistryConflict,
    SQLiteRegistry,
    TaskStatus,
    Worker,
    WorkPackage,
)
from scripts.factory_registry.preservation_import import import_snapshot


class SQLiteRegistryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.database = self.root / "registry.sqlite3"
        self.registry = SQLiteRegistry(self.database)
        self.registry.initialize()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def feature(self, feature_id: str = "FEATURE-1") -> None:
        self.registry.register_feature(Feature(feature_id, "Feature", 100, TaskStatus.READY))

    def worker(self, worker_id: str, *capabilities: str) -> None:
        self.registry.register_worker(
            Worker(worker_id, worker_id, capabilities, (Lane.PLATFORM,), usage_state="GREEN")
        )

    def package(
        self,
        package_id: str,
        *,
        dependencies: tuple[str, ...] = (),
        capabilities: tuple[str, ...] = ("registry",),
    ) -> None:
        self.registry.register_work_package(
            WorkPackage(
                package_id,
                "FEATURE-1",
                package_id,
                "ORCHESTRATION",
                Lane.PLATFORM,
                capabilities,
                100,
                ("test evidence exists",),
                status=TaskStatus.READY,
                dependency_ids=dependencies,
            )
        )

    def test_uses_wal_and_expected_schema_version(self) -> None:
        self.assertEqual(self.registry.journal_mode(), "wal")
        with sqlite3.connect(self.database) as connection:
            versions = dict(connection.execute(
                """SELECT key, value FROM registry_metadata
                   WHERE key IN ('schema_version', 'control_schema_version')"""
            ).fetchall())
        self.assertEqual(
            versions,
            {"schema_version": "3", "control_schema_version": "1"},
        )

    def test_initialize_additively_upgrades_version_one_registry(self) -> None:
        legacy_database = self.root / "legacy.sqlite3"
        with sqlite3.connect(legacy_database) as connection:
            connection.execute(
                "CREATE TABLE registry_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            connection.execute(
                "INSERT INTO registry_metadata(key, value) VALUES ('schema_version', '1')"
            )
            connection.execute(
                "INSERT INTO registry_metadata(key, value) VALUES ('legacy_marker', 'preserved')"
            )
        legacy = SQLiteRegistry(legacy_database)
        legacy.initialize()
        with sqlite3.connect(legacy_database) as connection:
            metadata = dict(connection.execute("SELECT key, value FROM registry_metadata"))
            usage_tables = connection.execute(
                """SELECT count(*) FROM sqlite_master
                   WHERE type='table' AND name IN ('usage_ledger', 'usage_ledger_sources')"""
            ).fetchone()[0]
            package_columns = {
                row[1] for row in connection.execute("PRAGMA table_info(work_packages)")
            }
        self.assertEqual(metadata["schema_version"], "3")
        self.assertEqual(metadata["legacy_marker"], "preserved")
        self.assertEqual(usage_tables, 2)
        self.assertTrue({"capacity_size", "capacity_risk"}.issubset(package_columns))

    def test_initialize_additively_upgrades_pre_control_schema_version_three(self) -> None:
        database = self.root / "pre-a4b-v3.sqlite3"
        legacy = SQLiteRegistry(database)
        legacy.initialize()
        legacy.register_feature(Feature("PRESERVED", "Preserved feature", 100, TaskStatus.READY))
        with sqlite3.connect(database) as connection:
            connection.execute("DROP TABLE attempt_runtime_ownership")
            connection.execute("DROP TABLE factory_control")
            connection.execute(
                "DELETE FROM registry_metadata WHERE key='control_schema_version'"
            )

        legacy.initialize()

        with sqlite3.connect(database) as connection:
            metadata = dict(connection.execute(
                "SELECT key, value FROM registry_metadata "
                "WHERE key IN ('schema_version', 'control_schema_version')"
            ))
            control = connection.execute(
                "SELECT dispatch_mode, kill_switch_engaged FROM factory_control "
                "WHERE singleton=1"
            ).fetchone()
            preserved = connection.execute(
                "SELECT title FROM features WHERE id='PRESERVED'"
            ).fetchone()[0]
            runtime_table = connection.execute(
                "SELECT count(*) FROM sqlite_schema "
                "WHERE type='table' AND name='attempt_runtime_ownership'"
            ).fetchone()[0]
        self.assertEqual(
            metadata,
            {"schema_version": "3", "control_schema_version": "1"},
        )
        self.assertEqual(control, ("PAUSED", 1))
        self.assertEqual(preserved, "Preserved feature")
        self.assertEqual(runtime_table, 1)

    def test_initialize_adds_capacity_fields_to_existing_version_one_packages(self) -> None:
        legacy_database = self.root / "legacy-capacity.sqlite3"
        with sqlite3.connect(legacy_database) as connection:
            connection.executescript(
                """
                CREATE TABLE registry_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                INSERT INTO registry_metadata(key, value) VALUES
                    ('schema_version', '1'), ('revision', '0'),
                    ('active_parent_limit', '3'), ('orchestra_reserve_percent', '20');
                CREATE TABLE work_packages (
                    id TEXT PRIMARY KEY, feature_id TEXT NOT NULL, status TEXT NOT NULL,
                    priority INTEGER NOT NULL, ready_at TEXT, created_at TEXT NOT NULL,
                    kind TEXT NOT NULL, source_system TEXT, source_ref TEXT
                );
                INSERT INTO work_packages
                    (id, feature_id, status, priority, created_at, kind)
                    VALUES ('legacy', 'feature', 'READY', 1, '2026-09-24T00:00:00Z', 'PARENT');
                """
            )
        legacy = SQLiteRegistry(legacy_database)
        legacy.initialize()
        with sqlite3.connect(legacy_database) as connection:
            row = connection.execute(
                "SELECT capacity_size, capacity_risk FROM work_packages WHERE id='legacy'"
            ).fetchone()
            version = connection.execute(
                "SELECT value FROM registry_metadata WHERE key='schema_version'"
            ).fetchone()[0]
        self.assertEqual(row, ("SUBSTANTIAL", "UNCERTAIN"))
        self.assertEqual(version, "3")

    def test_initialize_classifies_version_two_usage_provenance(self) -> None:
        legacy_database = self.root / "legacy-v2.sqlite3"
        legacy = SQLiteRegistry(legacy_database)
        legacy.initialize()
        legacy.register_feature(Feature("FEATURE", "Feature", 100, TaskStatus.READY))
        legacy.register_worker(
            Worker("claude", "Claude", ("registry",), (Lane.PLATFORM,))
        )
        for package_id in ("TASK", "OTHER"):
            legacy.register_work_package(
                WorkPackage(
                    package_id,
                    "FEATURE",
                    package_id,
                    "ORCHESTRATION",
                    Lane.PLATFORM,
                    ("registry",),
                    100,
                    ("evidence",),
                    status=TaskStatus.READY,
                )
            )
        legacy.register_attempt(
            Attempt("ATTEMPT", "TASK", "claude", "2026-09-24T20:00:00Z")
        )
        with sqlite3.connect(legacy_database) as connection:
            connection.execute("DROP TABLE usage_ledger_sources")
            connection.execute("DROP TABLE usage_ledger")
            connection.execute(
                """CREATE TABLE usage_ledger (
                    id TEXT PRIMARY KEY, provider TEXT NOT NULL, worker_id TEXT NOT NULL,
                    account_id TEXT NOT NULL, invocation_id TEXT NOT NULL,
                    session_id TEXT NOT NULL, package_id TEXT, attempt_id TEXT,
                    observed_at TEXT NOT NULL, model_diagnostic TEXT,
                    input_tokens INTEGER, output_tokens INTEGER,
                    cache_read_input_tokens INTEGER, cache_creation_input_tokens INTEGER,
                    duration_ms REAL, outcome TEXT NOT NULL, task_completed INTEGER NOT NULL,
                    review_completed INTEGER NOT NULL, limit_signal TEXT,
                    limit_reset_at TEXT, limit_raw_error TEXT,
                    calibration_metadata_json TEXT NOT NULL,
                    primary_source_type TEXT NOT NULL,
                    primary_source_identity TEXT NOT NULL UNIQUE,
                    primary_source_metadata_json TEXT NOT NULL, created_at TEXT NOT NULL,
                    UNIQUE(provider, worker_id, account_id, invocation_id)
                )"""
            )
            values = (
                "anthropic", "claude", "account", "2026-09-24T20:00:00Z",
                "SUCCEEDED", "{}", "CLI_JSON", "{}", "2026-09-24T20:00:00Z",
            )
            connection.execute(
                """INSERT INTO usage_ledger
                   (id, provider, worker_id, account_id, invocation_id, session_id,
                    package_id, attempt_id, observed_at, outcome, task_completed,
                    review_completed, calibration_metadata_json, primary_source_type,
                    primary_source_identity, primary_source_metadata_json, created_at)
                   VALUES ('linked', ?, ?, ?, 'linked', 'session-linked', 'TASK',
                           'ATTEMPT', ?, ?, 0, 0, ?, ?, 'source-linked', ?, ?)""",
                values,
            )
            connection.execute(
                """INSERT INTO usage_ledger
                   (id, provider, worker_id, account_id, invocation_id, session_id,
                    observed_at, outcome, task_completed, review_completed,
                    calibration_metadata_json, primary_source_type,
                    primary_source_identity, primary_source_metadata_json, created_at)
                   VALUES ('probe', ?, ?, ?, 'probe', 'session-probe', ?, ?, 0, 0,
                           ?, ?, 'source-probe', ?, ?)""",
                values,
            )
            connection.execute(
                """INSERT INTO usage_ledger
                   (id, provider, worker_id, account_id, invocation_id, session_id,
                    package_id, attempt_id, observed_at, outcome, task_completed,
                    review_completed, calibration_metadata_json, primary_source_type,
                    primary_source_identity, primary_source_metadata_json, created_at)
                   VALUES ('mismatched', ?, ?, ?, 'mismatched', 'session-mismatched',
                           'OTHER', 'ATTEMPT', ?, ?, 0, 0, ?, ?, 'source-mismatched', ?, ?)""",
                values,
            )
            connection.execute(
                "UPDATE registry_metadata SET value='2' WHERE key='schema_version'"
            )
        legacy.initialize()
        with sqlite3.connect(legacy_database) as connection:
            classes = dict(
                connection.execute("SELECT id, observation_class FROM usage_ledger")
            )
            version = connection.execute(
                "SELECT value FROM registry_metadata WHERE key='schema_version'"
            ).fetchone()[0]
        self.assertEqual(
            classes,
            {
                "linked": "AUTONOMOUS",
                "probe": "LEGACY_UNCLASSIFIED",
                "mismatched": "LEGACY_UNCLASSIFIED",
            },
        )
        self.assertEqual(version, "3")

    def test_initialize_rejects_invalid_versions_without_mutating_database(self) -> None:
        cases = (
            ("newer", "4", "SCHEMA_VERSION_UNSUPPORTED: 4"),
            ("malformed", "future", "SCHEMA_VERSION_INVALID: future"),
        )
        for label, version, error in cases:
            with self.subTest(label=label):
                database = self.root / f"{label}.sqlite3"
                connection = sqlite3.connect(database)
                try:
                    self.assertEqual(
                        connection.execute("PRAGMA journal_mode = WAL").fetchone()[0],
                        "wal",
                    )
                    connection.execute(
                        "CREATE TABLE registry_metadata "
                        "(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
                    )
                    connection.execute(
                        "INSERT INTO registry_metadata(key, value) "
                        "VALUES ('schema_version', ?)",
                        (version,),
                    )
                    connection.execute(
                        "CREATE TABLE future_schema_marker "
                        "(id INTEGER PRIMARY KEY, value TEXT NOT NULL)"
                    )
                    connection.execute(
                        "INSERT INTO future_schema_marker(value) VALUES ('preserve')"
                    )
                    connection.commit()
                    connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                finally:
                    connection.close()
                for suffix in ("-wal", "-shm"):
                    Path(f"{database}{suffix}").unlink(missing_ok=True)

                def immutable_state() -> tuple[str, tuple[tuple[object, ...], ...]]:
                    uri = f"{database.resolve().as_uri()}?mode=ro&immutable=1"
                    readonly = sqlite3.connect(uri, uri=True)
                    try:
                        stored_version = readonly.execute(
                            "SELECT value FROM registry_metadata WHERE key='schema_version'"
                        ).fetchone()[0]
                        schema = tuple(readonly.execute(
                            "SELECT type, name, tbl_name, sql FROM sqlite_schema "
                            "ORDER BY type, name"
                        ))
                        return stored_version, schema
                    finally:
                        readonly.close()

                before_bytes = database.read_bytes()
                before_files = sorted(path.name for path in self.root.glob(f"{database.name}*"))
                before_version, before_schema = immutable_state()
                before_journal_header = before_bytes[18:20]
                self.assertEqual(before_journal_header, b"\x02\x02")
                self.assertEqual(before_files, [database.name])

                with self.assertRaisesRegex(RegistryConflict, error):
                    SQLiteRegistry(database).initialize()

                stored_version, after_schema = immutable_state()
                after_files = sorted(path.name for path in self.root.glob(f"{database.name}*"))
                after_bytes = database.read_bytes()

                self.assertEqual(stored_version, version)
                self.assertEqual(before_version, version)
                self.assertEqual(after_bytes[18:20], before_journal_header)
                self.assertEqual(after_schema, before_schema)
                self.assertEqual(after_bytes, before_bytes)
                self.assertEqual(after_files, before_files)

    def test_initialize_reads_active_wal_before_opening_source(self) -> None:
        cases = (
            ("newer-active", "4", "SCHEMA_VERSION_UNSUPPORTED: 4"),
            ("malformed-active", "future", "SCHEMA_VERSION_INVALID: future"),
        )
        for label, wal_version, error in cases:
            with self.subTest(label=label):
                database = self.root / f"{label}.sqlite3"
                connection = sqlite3.connect(database)
                try:
                    connection.execute(
                        "CREATE TABLE registry_metadata "
                        "(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
                    )
                    connection.execute(
                        "INSERT INTO registry_metadata(key, value) "
                        "VALUES ('schema_version', '1')"
                    )
                    connection.execute(
                        "CREATE TABLE active_wal_marker "
                        "(id INTEGER PRIMARY KEY, value TEXT NOT NULL)"
                    )
                    connection.execute(
                        "INSERT INTO active_wal_marker(value) VALUES ('main')"
                    )
                    connection.commit()
                    self.assertEqual(
                        connection.execute("PRAGMA journal_mode = WAL").fetchone()[0],
                        "wal",
                    )
                    connection.execute("PRAGMA wal_autocheckpoint = 0")
                    connection.execute(
                        "UPDATE registry_metadata SET value=? WHERE key='schema_version'",
                        (wal_version,),
                    )
                    connection.execute(
                        "UPDATE active_wal_marker SET value='active-wal' WHERE id=1"
                    )
                    connection.commit()
                    self.assertEqual(
                        connection.execute(
                            "SELECT value FROM registry_metadata WHERE key='schema_version'"
                        ).fetchone()[0],
                        wal_version,
                    )

                    immutable_uri = (
                        f"{database.resolve().as_uri()}?mode=ro&immutable=1"
                    )
                    immutable = sqlite3.connect(immutable_uri, uri=True)
                    try:
                        self.assertEqual(
                            immutable.execute(
                                "SELECT value FROM registry_metadata "
                                "WHERE key='schema_version'"
                            ).fetchone()[0],
                            "1",
                        )
                    finally:
                        immutable.close()

                    source_paths = tuple(
                        Path(f"{database}{suffix}") for suffix in ("", "-wal", "-shm")
                    )
                    self.assertTrue(all(path.exists() for path in source_paths))
                    before = {path.name: path.read_bytes() for path in source_paths}

                    with self.assertRaisesRegex(RegistryConflict, error):
                        SQLiteRegistry(database).initialize()

                    after = {path.name: path.read_bytes() for path in source_paths}
                    self.assertEqual(after, before)
                    self.assertEqual(
                        connection.execute(
                            "SELECT value FROM registry_metadata WHERE key='schema_version'"
                        ).fetchone()[0],
                        wal_version,
                    )
                    self.assertEqual(
                        connection.execute(
                            "SELECT value FROM active_wal_marker WHERE id=1"
                        ).fetchone()[0],
                        "active-wal",
                    )
                finally:
                    connection.close()

    def test_control_apis_fail_closed_for_newer_or_malformed_schema(self) -> None:
        for value, code in (
            ("2", "UNSUPPORTED_CONTROL_SCHEMA_VERSION"),
            ("future", "MALFORMED_CONTROL_SCHEMA_VERSION"),
        ):
            with self.subTest(value=value):
                with sqlite3.connect(self.database) as connection:
                    connection.execute(
                        "UPDATE registry_metadata SET value=? WHERE key='control_schema_version'",
                        (value,),
                    )
                with self.assertRaisesRegex(RegistryConflict, code):
                    self.registry.dispatch_control()
                with self.assertRaisesRegex(RegistryConflict, code):
                    self.registry.initialize()
                with sqlite3.connect(self.database) as connection:
                    stored = connection.execute(
                        "SELECT value FROM registry_metadata WHERE key='control_schema_version'"
                    ).fetchone()[0]
                    mode = connection.execute(
                        "SELECT dispatch_mode FROM factory_control WHERE singleton=1"
                    ).fetchone()[0]
                    connection.execute(
                        "UPDATE registry_metadata SET value='1' WHERE key='control_schema_version'"
                    )
                self.assertEqual(stored, value)
                self.assertEqual(mode, "PAUSED")

        with sqlite3.connect(self.database) as connection:
            connection.execute(
                "DELETE FROM registry_metadata WHERE key='control_schema_version'"
            )
        with self.assertRaisesRegex(RegistryConflict, "CONTROL_SCHEMA_METADATA_MISSING"):
            self.registry.dispatch_control()
        with self.assertRaisesRegex(RegistryConflict, "CONTROL_SCHEMA_METADATA_MISSING"):
            self.registry.initialize()
        with sqlite3.connect(self.database) as connection:
            stored = connection.execute(
                "SELECT value FROM registry_metadata WHERE key='control_schema_version'"
            ).fetchone()
            mode = connection.execute(
                "SELECT dispatch_mode FROM factory_control WHERE singleton=1"
            ).fetchone()[0]
            connection.execute(
                "INSERT INTO registry_metadata(key, value) VALUES ('control_schema_version', '1')"
            )
        self.assertIsNone(stored)
        self.assertEqual(mode, "PAUSED")

    def test_enforces_three_active_parent_packages_transactionally(self) -> None:
        self.feature()
        for number in range(1, 5):
            self.worker(f"worker-{number}", "registry")
            self.package(f"TASK-{number}")
        leases = []
        for number in range(1, 4):
            leases.append(
                self.registry.acquire_lease(
                    f"TASK-{number}", f"worker-{number}",
                    acquired_at="2026-09-24T10:00:00+00:00",
                    expires_at="2026-09-24T10:05:00+00:00",
                )
            )
        with self.assertRaisesRegex(RegistryConflict, "ACTIVE_PARENT_LIMIT"):
            self.registry.acquire_lease(
                "TASK-4", "worker-4",
                acquired_at="2026-09-24T10:01:00+00:00",
                expires_at="2026-09-24T10:06:00+00:00",
            )
        self.registry.release_lease(
            leases[0].id,
            released_at="2026-09-24T10:02:00+00:00",
            reason="READY_FOR_REVIEW",
            next_status=TaskStatus.VERIFY_REVIEW,
        )
        replacement = self.registry.acquire_lease(
            "TASK-4", "worker-4",
            acquired_at="2026-09-24T10:03:00+00:00",
            expires_at="2026-09-24T10:08:00+00:00",
        )
        self.assertEqual(replacement.package_id, "TASK-4")

    def test_concurrent_claim_allows_only_one_worker_to_own_package(self) -> None:
        self.feature()
        self.worker("worker-1", "registry")
        self.worker("worker-2", "registry")
        self.package("TASK")

        def claim(worker_id: str) -> str:
            try:
                lease = self.registry.acquire_lease(
                    "TASK", worker_id,
                    acquired_at="2026-09-24T10:00:00+00:00",
                    expires_at="2026-09-24T10:05:00+00:00",
                )
                return lease.worker_id
            except RegistryConflict as error:
                return error.code

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = sorted(pool.map(claim, ("worker-1", "worker-2")))
        self.assertEqual(sum(result.startswith("worker-") for result in results), 1)
        self.assertEqual(sum(result in {"PACKAGE_NOT_READY", "LEASE_CONFLICT"} for result in results), 1)

    def test_active_package_transition_requires_atomic_lease_release(self) -> None:
        self.feature()
        self.worker("worker", "registry")
        self.package("TASK")
        self.registry.acquire_lease(
            "TASK", "worker",
            acquired_at="2026-09-24T10:00:00+00:00",
            expires_at="2026-09-24T10:05:00+00:00",
        )
        with self.assertRaisesRegex(RegistryConflict, "ACTIVE_TRANSITION_REQUIRES_LEASE_RELEASE"):
            self.registry.transition_work_package(
                "TASK", expected_status=TaskStatus.ACTIVE,
                new_status=TaskStatus.VERIFY_REVIEW,
                changed_at="2026-09-24T10:01:00+00:00",
            )

    def test_active_status_can_only_be_entered_by_acquiring_a_lease(self) -> None:
        self.feature()
        self.package("TASK")
        with self.assertRaisesRegex(RegistryConflict, "ACTIVE_REQUIRES_LEASE"):
            self.registry.transition_work_package(
                "TASK", expected_status=TaskStatus.READY,
                new_status=TaskStatus.ACTIVE,
                changed_at="2026-09-24T10:01:00Z",
            )
        with sqlite3.connect(self.database) as connection:
            self.assertEqual(
                connection.execute("SELECT status FROM work_packages WHERE id='TASK'").fetchone()[0],
                "READY",
            )
            self.assertEqual(connection.execute("SELECT count(*) FROM leases").fetchone()[0], 0)

    def test_work_package_cannot_be_registered_as_active(self) -> None:
        self.feature()
        with self.assertRaisesRegex(RegistryConflict, "ACTIVE_REQUIRES_LEASE"):
            self.registry.register_work_package(
                WorkPackage(
                    "ACTIVE-TASK", "FEATURE-1", "Active", "ORCHESTRATION",
                    Lane.PLATFORM, ("registry",), 1, ("complete",),
                    status=TaskStatus.ACTIVE,
                )
            )

    def test_explicit_expiry_reconciles_lease_package_worker_failure_and_event(self) -> None:
        self.feature()
        self.worker("worker", "registry")
        self.package("TASK")
        lease = self.registry.acquire_lease(
            "TASK", "worker",
            acquired_at="2026-09-24T10:00:00Z",
            expires_at="2026-09-24T10:05:00Z",
        )
        self.assertEqual(
            self.registry.expire_leases(observed_at="2026-09-24T10:06:00Z"), 1
        )
        with sqlite3.connect(self.database) as connection:
            released = connection.execute(
                "SELECT released_at, release_reason FROM leases WHERE id=?", (lease.id,)
            ).fetchone()
            package = connection.execute(
                "SELECT status, failure_code FROM work_packages WHERE id='TASK'"
            ).fetchone()
            worker = connection.execute(
                "SELECT availability FROM workers WHERE id='worker'"
            ).fetchone()[0]
            event_count = connection.execute(
                "SELECT count(*) FROM task_events WHERE event_type='LEASE_EXPIRED'"
            ).fetchone()[0]
            failure_count = connection.execute(
                "SELECT count(*) FROM failure_observations WHERE code='HEARTBEAT_MISSED'"
            ).fetchone()[0]
        self.assertEqual(released[1], "LEASE_EXPIRED")
        self.assertEqual(package, ("BLOCKED", "HEARTBEAT_MISSED"))
        self.assertEqual(worker, "IDLE")
        self.assertEqual(event_count, 1)
        self.assertEqual(failure_count, 1)

    def test_release_after_expiry_reconciles_expiry_instead_of_completing(self) -> None:
        self.feature()
        self.worker("worker", "registry")
        self.package("TASK")
        lease = self.registry.acquire_lease(
            "TASK", "worker",
            acquired_at="2026-09-24T10:00:00Z",
            expires_at="2026-09-24T10:05:00Z",
        )
        with self.assertRaisesRegex(RegistryConflict, "LEASE_NOT_ACTIVE"):
            self.registry.release_lease(
                lease.id,
                released_at="2026-09-24T10:06:00Z",
                reason="COMPLETED",
                next_status=TaskStatus.DONE,
            )
        with sqlite3.connect(self.database) as connection:
            self.assertEqual(
                connection.execute("SELECT status FROM work_packages WHERE id='TASK'").fetchone()[0],
                "BLOCKED",
            )

    def test_lease_lifecycle_cannot_move_backward_in_time(self) -> None:
        self.feature()
        self.worker("worker", "registry")
        self.package("TASK")
        lease = self.registry.acquire_lease(
            "TASK", "worker",
            acquired_at="2026-09-24T10:00:00Z",
            expires_at="2026-09-24T10:10:00Z",
        )
        with self.assertRaisesRegex(RegistryConflict, "INVALID_LEASE_CHRONOLOGY"):
            self.registry.renew_lease(
                lease.id,
                now="2026-09-24T09:59:00Z",
                expires_at="2026-09-24T10:11:00Z",
            )
        with self.assertRaisesRegex(RegistryConflict, "INVALID_LEASE_CHRONOLOGY"):
            self.registry.release_lease(
                lease.id,
                released_at="2026-09-24T09:59:00Z",
                reason="COMPLETED",
                next_status=TaskStatus.DONE,
            )
        self.registry.renew_lease(
            lease.id,
            now="2026-09-24T10:02:00Z",
            expires_at="2026-09-24T10:12:00Z",
        )
        with self.assertRaisesRegex(RegistryConflict, "INVALID_LEASE_CHRONOLOGY"):
            self.registry.renew_lease(
                lease.id,
                now="2026-09-24T10:01:00Z",
                expires_at="2026-09-24T10:13:00Z",
            )

    def test_actively_leased_worker_cannot_be_reconfigured(self) -> None:
        self.feature()
        self.worker("worker", "registry")
        self.package("TASK")
        self.registry.acquire_lease(
            "TASK", "worker",
            acquired_at="2026-09-24T10:00:00Z",
            expires_at="2026-09-24T10:05:00Z",
        )
        with self.assertRaisesRegex(RegistryConflict, "WORKER_HAS_ACTIVE_LEASE"):
            self.registry.register_worker(
                Worker(
                    "worker", "Changed", (), (), role="ORCHESTRA",
                    availability="IDLE", usage_state="GREEN",
                )
            )
        with sqlite3.connect(self.database) as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT role, availability FROM workers WHERE id='worker'"
                ).fetchone(),
                ("WORKER", "BUSY"),
            )

    def test_lease_timestamps_are_normalized_before_duration_check(self) -> None:
        self.feature()
        self.worker("worker", "registry")
        self.package("TASK")
        with self.assertRaisesRegex(RegistryConflict, "INVALID_LEASE_EXPIRY"):
            self.registry.acquire_lease(
                "TASK", "worker",
                acquired_at="2026-09-24T10:00:00.900000+00:00",
                expires_at="2026-09-24T10:00:00Z",
            )

    def test_orchestra_role_cannot_claim_implementation_work(self) -> None:
        self.feature()
        self.registry.register_worker(
            Worker(
                "orchestra", "Orchestra", ("registry",), (Lane.PLATFORM,),
                role="ORCHESTRA", usage_state="GREEN",
            )
        )
        self.package("TASK")
        with self.assertRaisesRegex(RegistryConflict, "ORCHESTRA_CANNOT_CLAIM"):
            self.registry.acquire_lease(
                "TASK", "orchestra",
                acquired_at="2026-09-24T10:00:00Z",
                expires_at="2026-09-24T10:05:00Z",
            )

    def test_rejects_capability_mismatch_and_incomplete_dependency(self) -> None:
        self.feature()
        self.worker("worker", "registry")
        self.package("DEPENDENCY")
        self.package("BLOCKED", dependencies=("DEPENDENCY",))
        self.package("MISMATCH", capabilities=("database-migration",))
        with self.assertRaisesRegex(RegistryConflict, "DEPENDENCY_BLOCKED"):
            self.registry.acquire_lease(
                "BLOCKED", "worker",
                acquired_at="2026-09-24T10:00:00+00:00",
                expires_at="2026-09-24T10:05:00+00:00",
            )
        with self.assertRaisesRegex(RegistryConflict, "CAPABILITY_MISMATCH"):
            self.registry.acquire_lease(
                "MISMATCH", "worker",
                acquired_at="2026-09-24T10:00:00+00:00",
                expires_at="2026-09-24T10:05:00+00:00",
            )

    def test_events_are_append_only(self) -> None:
        event_id = self.registry.append_event(
            "OBSERVED", recorded_at="2026-09-24T10:00:00+00:00", detail={"safe": True}
        )
        with sqlite3.connect(self.database) as connection:
            with self.assertRaisesRegex(sqlite3.IntegrityError, "TASK_EVENTS_APPEND_ONLY"):
                connection.execute(
                    "UPDATE task_events SET event_type='CHANGED' WHERE id=?", (event_id,)
                )
            with self.assertRaisesRegex(sqlite3.IntegrityError, "TASK_EVENTS_APPEND_ONLY"):
                connection.execute("DELETE FROM task_events WHERE id=?", (event_id,))

    def test_preservation_import_is_read_only_and_idempotent(self) -> None:
        snapshot = {
            "snapshot_version": 1,
            "canonical_repository": {
                "origin_main": "abc", "path": str(self.root / "canonical")
            },
            "services": {"heartbeats": {"codex-a": {"time": 1000, "status": "idle"}}},
            "open_task_mapping": [
                {
                    "issue": 146,
                    "task": "TASK-140",
                    "title": "Usage feed",
                    "status": "VERIFY / REVIEW",
                    "worker": "Agent B",
                    "branch": "runner/task-140",
                    "pr": 148,
                }
            ],
            "worktrees": [
                {"worktree": "/preserved/worktree", "branch": "refs/heads/preserved", "dirty": True}
            ],
            "unmerged_local_branches": ["runner/task-140 abc123"],
        }
        source = self.root / "snapshot.json"
        source.write_text(json.dumps(snapshot, sort_keys=True))
        before = source.read_bytes()
        digest = hashlib.sha256(before).hexdigest()
        self.assertTrue(import_snapshot(source, self.database))
        self.assertFalse(import_snapshot(source, self.database))
        self.assertEqual(source.read_bytes(), before)
        with sqlite3.connect(self.database) as connection:
            imported_digest = connection.execute(
                "SELECT source_sha256 FROM preservation_imports"
            ).fetchone()[0]
            package = connection.execute(
                "SELECT status, lane, source_system, source_ref FROM work_packages WHERE id='TASK-140'"
            ).fetchone()
            dirty = connection.execute(
                "SELECT dirty FROM preserved_artifacts WHERE kind='WORKTREE'"
            ).fetchone()[0]
        self.assertEqual(imported_digest, digest)
        self.assertEqual(package, ("VERIFY_REVIEW", None, "github_issue", "146"))
        self.assertEqual(dirty, 1)

    def test_preservation_import_rejects_database_inside_preserved_worktree(self) -> None:
        preserved = self.root / "preserved-worktree"
        preserved.mkdir()
        snapshot = {
            "snapshot_version": 1,
            "canonical_repository": {
                "origin_main": "abc", "path": str(self.root / "canonical")
            },
            "services": {"heartbeats": {}},
            "open_task_mapping": [],
            "worktrees": [{"worktree": str(preserved), "dirty": True}],
            "unmerged_local_branches": [],
        }
        source = self.root / "snapshot-safe.json"
        source.write_text(json.dumps(snapshot))
        unsafe_database = preserved / "registry.sqlite3"
        with self.assertRaisesRegex(RegistryConflict, "UNSAFE_IMPORT_TARGET"):
            import_snapshot(source, unsafe_database)
        self.assertFalse(unsafe_database.exists())

    def test_preservation_import_rejects_database_inside_canonical_repository(self) -> None:
        canonical = self.root / "canonical-repository"
        canonical.mkdir()
        snapshot = {
            "snapshot_version": 1,
            "canonical_repository": {"origin_main": "abc", "path": str(canonical)},
            "services": {"heartbeats": {}},
            "open_task_mapping": [],
            "worktrees": [],
            "unmerged_local_branches": [],
        }
        source = self.root / "snapshot-canonical.json"
        source.write_text(json.dumps(snapshot))
        unsafe_database = canonical / "registry.sqlite3"
        with self.assertRaisesRegex(RegistryConflict, "UNSAFE_IMPORT_TARGET"):
            import_snapshot(source, unsafe_database)
        self.assertFalse(unsafe_database.exists())

    def test_preservation_import_rejects_duplicate_normalized_tasks(self) -> None:
        duplicate = {
            "snapshot_version": 1,
            "canonical_repository": {
                "origin_main": "abc", "path": str(self.root / "canonical")
            },
            "services": {"heartbeats": {}},
            "open_task_mapping": [
                {"issue": 1, "task": "TASK-1", "title": "First", "status": "ON DECK"},
                {"issue": 2, "task": "TASK-1", "title": "Second", "status": "ON DECK"},
            ],
            "worktrees": [],
            "unmerged_local_branches": [],
        }
        with self.assertRaisesRegex(RegistryConflict, "DUPLICATE_PRESERVATION_TASK"):
            self.registry.import_preservation_snapshot(
                duplicate,
                source_uri="snapshot.json",
                source_sha256="a" * 64,
                imported_at="2026-09-24T10:00:00Z",
            )
        with sqlite3.connect(self.database) as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM preservation_imports").fetchone()[0], 0)

    def test_preservation_import_rejects_existing_legacy_worker_collision(self) -> None:
        self.registry.register_worker(
            Worker(
                "legacy-worker:codex-a", "Existing", ("registry",),
                (Lane.PLATFORM,), usage_state="GREEN",
            )
        )
        snapshot = {
            "snapshot_version": 1,
            "canonical_repository": {
                "origin_main": "abc", "path": str(self.root / "canonical")
            },
            "services": {"heartbeats": {"codex-a": {"time": 1000}}},
            "open_task_mapping": [],
            "worktrees": [],
            "unmerged_local_branches": [],
        }
        with self.assertRaisesRegex(RegistryConflict, "PRESERVATION_COLLISION"):
            self.registry.import_preservation_snapshot(
                snapshot,
                source_uri="snapshot.json",
                source_sha256="b" * 64,
                imported_at="2026-09-24T10:00:00Z",
            )
        with sqlite3.connect(self.database) as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM preservation_imports").fetchone()[0], 0)

    def test_preservation_import_rejects_malformed_artifacts_and_heartbeats(self) -> None:
        base = {
            "snapshot_version": 1,
            "canonical_repository": {
                "origin_main": "abc", "path": str(self.root / "canonical")
            },
            "services": {"heartbeats": {}},
            "open_task_mapping": [],
            "worktrees": [],
            "unmerged_local_branches": [],
        }
        malformed = [
            ({**base, "unmerged_local_branches": [None]}, "INVALID_PRESERVATION_BRANCH"),
            ({**base, "worktrees": [{"worktree": "relative/path"}]}, "INVALID_PRESERVATION_WORKTREE"),
            ({**base, "services": {"heartbeats": {"worker": "bad"}}}, "INVALID_PRESERVATION_HEARTBEAT"),
        ]
        for index, (snapshot, code) in enumerate(malformed):
            with self.subTest(code=code):
                with self.assertRaisesRegex(RegistryConflict, code):
                    self.registry.import_preservation_snapshot(
                        snapshot,
                        source_uri=f"snapshot-{index}.json",
                        source_sha256=str(index) * 64,
                        imported_at="2026-09-24T10:00:00Z",
                    )

    def test_registered_timestamps_are_normalized_to_utc(self) -> None:
        self.feature()
        self.registry.register_worker(
            Worker(
                "worker", "Worker", ("registry",), (Lane.PLATFORM,),
                last_heartbeat_at="2026-09-24T11:00:00+01:00", usage_state="GREEN",
            )
        )
        self.registry.register_work_package(
            WorkPackage(
                "TASK", "FEATURE-1", "Task", "ORCHESTRATION", Lane.PLATFORM,
                ("registry",), 1, ("complete",), status=TaskStatus.READY,
                started_at="2026-09-24T11:00:00+01:00",
                last_heartbeat_at="2026-09-24T11:01:00+01:00",
            )
        )
        snapshot = self.registry.dispatch_snapshot(observed_at="2026-09-24T10:02:00Z")
        self.assertEqual(snapshot.workers[0]["last_heartbeat_at"], "2026-09-24T10:00:00.000000Z")
        self.assertEqual(snapshot.work_packages[0]["started_at"], "2026-09-24T10:00:00.000000Z")
        self.assertEqual(
            snapshot.work_packages[0]["last_heartbeat_at"], "2026-09-24T10:01:00.000000Z"
        )

    def test_dispatch_snapshot_exposes_backend_neutral_scheduler_inputs(self) -> None:
        self.feature()
        self.worker("worker", "registry")
        self.package("TASK")
        snapshot = self.registry.dispatch_snapshot(observed_at="2026-09-24T10:00:00Z")
        self.assertGreaterEqual(snapshot.revision, 3)
        self.assertEqual(snapshot.active_parent_limit, 3)
        self.assertEqual(snapshot.orchestra_reserve_percent, 20)
        self.assertEqual(snapshot.work_packages[0]["ready_at"] is not None, True)
        self.assertEqual(snapshot.work_packages[0]["capacity_size"], "SUBSTANTIAL")
        self.assertEqual(snapshot.work_packages[0]["capacity_risk"], "UNCERTAIN")
        self.assertEqual(snapshot.workers[0]["availability"], "IDLE")
        self.assertEqual(snapshot.workers[0]["capabilities"], ["registry"])
        self.assertEqual(snapshot.dependencies, ())
        self.assertEqual(snapshot.active_leases, ())

    def test_package_capacity_classification_is_registry_data(self) -> None:
        self.feature()
        self.registry.register_work_package(
            WorkPackage(
                "TASK", "FEATURE-1", "Task", "ASSURANCE", Lane.ASSURANCE,
                ("review",), 1, ("complete",), status=TaskStatus.READY,
                capacity_size=PackageCapacitySize.VERY_SMALL,
                capacity_risk=PackageCapacityRisk.BOUNDED,
            )
        )
        package = self.registry.dispatch_snapshot(
            observed_at="2026-09-24T10:00:00Z"
        ).work_packages[0]
        self.assertEqual(package["capacity_size"], "VERY_SMALL")
        self.assertEqual(package["capacity_risk"], "BOUNDED")

    def test_provider_metadata_does_not_grant_lane_or_capability(self) -> None:
        self.feature()
        self.registry.register_worker(
            Worker(
                "diagnostic-worker", "Diagnostic worker", (), (),
                provider_diagnostics={"provider": "preferred", "model": "expensive"},
                usage_state="GREEN",
            )
        )
        self.package("TASK")
        with self.assertRaisesRegex(RegistryConflict, "LANE_NOT_APPROVED"):
            self.registry.acquire_lease(
                "TASK", "diagnostic-worker",
                acquired_at="2026-09-24T10:00:00+00:00",
                expires_at="2026-09-24T10:05:00+00:00",
            )

    def test_dispatch_control_defaults_paused_and_requires_revision_cas(self) -> None:
        control = self.registry.dispatch_control()
        self.assertEqual(control["dispatch_mode"], "PAUSED")
        self.assertTrue(control["kill_switch_engaged"])
        with self.assertRaisesRegex(RegistryConflict, "DISPATCH_PAUSED"):
            self.registry.require_live_dispatch()
        with self.assertRaisesRegex(
            RegistryConflict, "DISPATCH_CONTROL_COMPARE_AND_SWAP_FAILED"
        ):
            self.registry.set_dispatch_control(
                expected_revision=control["revision"] + 1,
                expected_mode="PAUSED",
                new_mode="LIVE",
                kill_switch_engaged=False,
                changed_at="2026-09-25T10:00:00Z",
                reason="stale caller",
            )
        revision = self.registry.set_dispatch_control(
            expected_revision=control["revision"],
            expected_mode="PAUSED",
            new_mode="LIVE",
            kill_switch_engaged=False,
            changed_at="2026-09-25T10:00:00Z",
            reason="bounded canary",
        )
        self.assertEqual(self.registry.require_live_dispatch(), revision)

    def test_revision_pinned_lease_claim_rechecks_live_gate_atomically(self) -> None:
        self.feature()
        self.worker("worker", "registry")
        self.package("TASK")
        control = self.registry.dispatch_control()
        live_revision = self.registry.set_dispatch_control(
            expected_revision=control["revision"],
            expected_mode="PAUSED",
            new_mode="LIVE",
            kill_switch_engaged=False,
            changed_at="2026-09-25T10:00:00Z",
            reason="bounded canary",
        )
        self.registry.engage_dispatch_kill_switch(
            changed_at="2026-09-25T10:00:01Z", reason="operator stop"
        )
        with self.assertRaisesRegex(RegistryConflict, "DISPATCH_NOT_AUTHORIZED"):
            self.registry.acquire_lease(
                "TASK", "worker",
                acquired_at="2026-09-25T10:00:02Z",
                expires_at="2026-09-25T10:10:02Z",
                expected_dispatch_revision=live_revision,
            )
        snapshot = self.registry.dispatch_snapshot(observed_at="2026-09-25T10:00:02Z")
        self.assertEqual(snapshot.active_leases, ())
        self.assertEqual(snapshot.work_packages[0]["status"], "READY")

    def test_dispatch_snapshot_projects_worker_capacity_mode_for_live_gate(self) -> None:
        self.registry.register_worker(
            Worker(
                "claude", "Claude", ("registry",), (Lane.ASSURANCE,),
                provider_diagnostics={
                    "capacity_mode": "provider_signal",
                    "capacity_scopes": ["provider_signal"],
                },
                usage_state="NORMAL",
            )
        )
        snapshot = self.registry.dispatch_snapshot(observed_at="2026-09-25T10:00:00Z")
        worker = snapshot.workers[0]
        self.assertEqual(worker["capacity_mode"], "provider_signal")
        self.assertEqual(worker["capacity_scopes"], ["provider_signal"])

    def test_dispatch_control_enforces_complete_phase_transition_table(self) -> None:
        legal = {
            ("PAUSED", "LIVE"),
            ("PAUSED", "STOPPING"),
            ("LIVE", "STOPPING"),
            ("STOPPING", "PAUSED"),
            ("STOPPING", "RECOVERY_REQUIRED"),
            ("RECOVERY_REQUIRED", "PAUSED"),
            ("RECOVERY_REQUIRED", "STOPPING"),
        }
        modes = ("PAUSED", "LIVE", "STOPPING", "RECOVERY_REQUIRED")
        for source in modes:
            for target in modes:
                with self.subTest(source=source, target=target):
                    database = self.root / f"transition-{source}-{target}.sqlite3"
                    registry = SQLiteRegistry(database)
                    registry.initialize()
                    with sqlite3.connect(database) as connection:
                        connection.execute(
                            "UPDATE factory_control SET dispatch_mode=?, "
                            "kill_switch_engaged=? WHERE singleton=1",
                            (source, int(source != "LIVE")),
                        )
                    before = registry.dispatch_control()
                    arguments = {
                        "expected_revision": before["revision"],
                        "expected_mode": source,
                        "new_mode": target,
                        "kill_switch_engaged": target != "LIVE",
                        "changed_at": "2026-09-25T10:00:00Z",
                        "reason": "transition-table test",
                    }
                    if (source, target) in legal:
                        registry.set_dispatch_control(**arguments)
                        self.assertEqual(
                            registry.dispatch_control()["dispatch_mode"], target
                        )
                    else:
                        with self.assertRaisesRegex(
                            RegistryConflict, "INVALID_DISPATCH_TRANSITION"
                        ):
                            registry.set_dispatch_control(**arguments)
                        after = registry.dispatch_control()
                        self.assertEqual(after["dispatch_mode"], source)
                        self.assertEqual(after["revision"], before["revision"])

    def test_runtime_provenance_is_atomic_and_finishes_all_ownership(self) -> None:
        self.feature()
        self.worker("worker", "registry")
        self.package("TASK")
        control = self.registry.dispatch_control()
        self.registry.set_dispatch_control(
            expected_revision=control["revision"],
            expected_mode="PAUSED",
            new_mode="LIVE",
            kill_switch_engaged=False,
            changed_at="2026-09-25T10:00:00Z",
            reason="bounded canary",
        )
        lease = self.registry.acquire_lease(
            "TASK",
            "worker",
            acquired_at="2026-09-25T10:01:00Z",
            expires_at="2026-09-25T10:10:00Z",
        )
        revision = self.registry.dispatch_control()["revision"]
        self.registry.begin_attempt_runtime(
            "attempt-1",
            package_id="TASK",
            worker_id="worker",
            runner_pid=100,
            started_at="2026-09-25T10:02:00Z",
            expected_revision=revision,
        )
        self.registry.record_attempt_process(
            "attempt-1",
            agent_pid=101,
            agent_pgid=101,
            recorded_at="2026-09-25T10:02:01Z",
        )
        self.registry.engage_dispatch_kill_switch(
            changed_at="2026-09-25T10:02:02Z", reason="operator stop"
        )
        stopped = self.registry.dispatch_control()
        with self.assertRaisesRegex(RegistryConflict, "ACTIVE_OWNERSHIP_PRESENT"):
            self.registry.set_dispatch_control(
                expected_revision=stopped["revision"],
                expected_mode="STOPPING",
                new_mode="PAUSED",
                kill_switch_engaged=True,
                changed_at="2026-09-25T10:02:03Z",
                reason="unsafe early pause",
            )
        self.registry.finish_attempt_runtime(
            "attempt-1",
            ended_at="2026-09-25T10:03:00Z",
            outcome="SUCCEEDED",
            next_status=TaskStatus.VERIFY_REVIEW,
            reason="ready for review",
        )
        with sqlite3.connect(self.database) as connection:
            runtime = connection.execute(
                """SELECT runner_pid, agent_pid, agent_pgid, released_at
                   FROM attempt_runtime_ownership WHERE attempt_id='attempt-1'"""
            ).fetchone()
            attempt = connection.execute(
                "SELECT outcome, ended_at FROM attempts WHERE id='attempt-1'"
            ).fetchone()
            package = connection.execute(
                "SELECT status FROM work_packages WHERE id='TASK'"
            ).fetchone()[0]
            released = connection.execute(
                "SELECT release_reason FROM leases WHERE id=?", (lease.id,)
            ).fetchone()[0]
        self.assertEqual(runtime[:3], (100, 101, 101))
        self.assertIsNotNone(runtime[3])
        self.assertEqual(attempt[0], "SUCCEEDED")
        self.assertIsNotNone(attempt[1])
        self.assertEqual(package, "VERIFY_REVIEW")
        self.assertEqual(released, "ready for review")
        self.assertEqual(self.registry.runtime_orphans(), ())
        stopped = self.registry.dispatch_control()
        self.registry.set_dispatch_control(
            expected_revision=stopped["revision"],
            expected_mode="STOPPING",
            new_mode="PAUSED",
            kill_switch_engaged=True,
            changed_at="2026-09-25T10:04:00Z",
            reason="ownership drained",
        )

    def test_process_binding_rechecks_kill_switch_and_orphans_stay_visible(self) -> None:
        self.feature()
        self.worker("worker", "registry")
        self.package("TASK")
        control = self.registry.dispatch_control()
        self.registry.set_dispatch_control(
            expected_revision=control["revision"],
            expected_mode="PAUSED",
            new_mode="LIVE",
            kill_switch_engaged=False,
            changed_at="2026-09-25T10:00:00Z",
            reason="bounded canary",
        )
        self.registry.acquire_lease(
            "TASK",
            "worker",
            acquired_at="2026-09-25T10:01:00Z",
            expires_at="2026-09-25T10:10:00Z",
        )
        self.registry.begin_attempt_runtime(
            "attempt-1",
            package_id="TASK",
            worker_id="worker",
            runner_pid=100,
            started_at="2026-09-25T10:02:00Z",
            expected_revision=self.registry.dispatch_control()["revision"],
        )
        self.registry.engage_dispatch_kill_switch(
            changed_at="2026-09-25T10:02:01Z", reason="operator stop"
        )
        with self.assertRaisesRegex(RegistryConflict, "DISPATCH_PAUSED"):
            self.registry.record_attempt_process(
                "attempt-1",
                agent_pid=101,
                agent_pgid=101,
                recorded_at="2026-09-25T10:02:02Z",
            )
        with sqlite3.connect(self.database) as connection:
            connection.execute(
                "UPDATE attempts SET ended_at=?, outcome='FAILED' WHERE id='attempt-1'",
                ("2026-09-25T10:03:00.000000Z",),
            )
        orphans = self.registry.runtime_orphans()
        self.assertEqual([item["attempt_id"] for item in orphans], ["attempt-1"])
        self.assertIsNone(orphans[0]["released_at"])

    def test_stopping_cannot_return_live_with_unreleased_runtime_orphan(self) -> None:
        self.feature()
        self.worker("worker", "registry")
        self.package("TASK")
        control = self.registry.dispatch_control()
        self.registry.set_dispatch_control(
            expected_revision=control["revision"],
            expected_mode="PAUSED",
            new_mode="LIVE",
            kill_switch_engaged=False,
            changed_at="2026-09-25T10:00:00Z",
            reason="bounded canary",
        )
        lease = self.registry.acquire_lease(
            "TASK",
            "worker",
            acquired_at="2026-09-25T10:01:00Z",
            expires_at="2026-09-25T10:10:00Z",
        )
        self.registry.begin_attempt_runtime(
            "attempt-1",
            package_id="TASK",
            worker_id="worker",
            runner_pid=100,
            started_at="2026-09-25T10:02:00Z",
            expected_revision=self.registry.dispatch_control()["revision"],
        )
        self.registry.engage_dispatch_kill_switch(
            changed_at="2026-09-25T10:02:01Z", reason="operator stop"
        )
        with sqlite3.connect(self.database) as connection:
            connection.execute(
                "UPDATE attempts SET ended_at=?, outcome='FAILED' WHERE id='attempt-1'",
                ("2026-09-25T10:03:00.000000Z",),
            )
            connection.execute(
                "UPDATE leases SET released_at=?, release_reason='incomplete recovery' WHERE id=?",
                ("2026-09-25T10:03:00.000000Z", lease.id),
            )
            connection.execute(
                "UPDATE work_packages SET status='BLOCKED' WHERE id='TASK'"
            )
            connection.execute(
                "UPDATE workers SET availability='IDLE' WHERE id='worker'"
            )
        stopped = self.registry.dispatch_control()
        with self.assertRaisesRegex(RegistryConflict, "ACTIVE_OWNERSHIP_PRESENT"):
            self.registry.set_dispatch_control(
                expected_revision=stopped["revision"],
                expected_mode="STOPPING",
                new_mode="LIVE",
                kill_switch_engaged=False,
                changed_at="2026-09-25T10:04:00Z",
                reason="unsafe restart",
            )
        unchanged = self.registry.dispatch_control()
        self.assertEqual(unchanged["dispatch_mode"], "STOPPING")
        self.assertTrue(unchanged["kill_switch_engaged"])
        self.assertEqual(unchanged["revision"], stopped["revision"])

    def test_expired_lease_and_disappeared_worker_surface_runtime_orphans(self) -> None:
        self.feature()
        self.worker("worker", "registry")
        self.package("TASK")
        control = self.registry.dispatch_control()
        self.registry.set_dispatch_control(
            expected_revision=control["revision"],
            expected_mode="PAUSED",
            new_mode="LIVE",
            kill_switch_engaged=False,
            changed_at="2026-09-25T10:00:00Z",
            reason="bounded canary",
        )
        self.registry.acquire_lease(
            "TASK",
            "worker",
            acquired_at="2026-09-25T10:01:00Z",
            expires_at="2026-09-25T10:10:00Z",
        )
        self.registry.begin_attempt_runtime(
            "attempt-1",
            package_id="TASK",
            worker_id="worker",
            runner_pid=100,
            started_at="2026-09-25T10:02:00Z",
            expected_revision=self.registry.dispatch_control()["revision"],
        )
        self.registry.record_attempt_process(
            "attempt-1",
            agent_pid=101,
            agent_pgid=101,
            recorded_at="2026-09-25T10:02:01Z",
        )
        self.assertEqual(
            self.registry.runtime_orphans(observed_at="2026-09-25T10:05:00Z"), ()
        )
        expired = self.registry.runtime_orphans(observed_at="2026-09-25T10:11:00Z")
        self.assertEqual([item["attempt_id"] for item in expired], ["attempt-1"])
        with sqlite3.connect(self.database) as connection:
            connection.execute(
                "UPDATE workers SET availability='OFFLINE' WHERE id='worker'"
            )
        disappeared = self.registry.runtime_orphans(
            observed_at="2026-09-25T10:05:00Z"
        )
        self.assertEqual(disappeared[0]["worker_availability"], "OFFLINE")


if __name__ == "__main__":
    unittest.main()
