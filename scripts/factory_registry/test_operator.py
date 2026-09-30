import hashlib
import json
import os
import plistlib
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path

import scripts.factory_registry.operator as operator_module
from scripts.factory_registry.models import (
    Evidence,
    Feature,
    Lane,
    PackageKind,
    ReviewOutcome,
    ReviewOutcomeState,
    ReviewInput,
    TaskStatus,
    Worker,
    WorkPackage,
)
from scripts.factory_registry.operator import (
    APPROVED_PRESERVATION_SHA256,
    OperatorError,
    REQUIRED_RELEASE_FILES,
    canary_worker_gate,
    enable_live,
    followup_review_worker_gate,
    harden_paths,
    migrate_registry_v3_to_v4,
    migrate_registry_v4_to_v5,
    migrate_registry_v5_to_v6,
    parse_canary_spec,
    parse_historical_reconciliation_spec,
    parse_followup_review_spec,
    preflight,
    prepare_dry_run,
    record_review_decision,
    reconcile_historical_package,
    restore_registry_v3_backup,
    restore_registry_v4_backup,
    status,
    store_preservation_evidence,
    utc_now,
    validate_telemetry_payload,
    verify_preservation,
)
from scripts.factory_registry.operator_cli import main as operator_main
from scripts.factory_registry.repository import RegistryConflict
from scripts.factory_registry.sqlite_registry import SQLiteRegistry
from scripts.runner.registry_control import RunnerRegistryControl


COMMIT = "a" * 40


class OperatorFixture(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.database = self.root / "registry" / "factory.sqlite3"
        self.database.parent.mkdir()
        self.registry = SQLiteRegistry(self.database)
        self.registry.initialize()
        self.preservation = (
            self.database.parent / "evidence" / "preservation_snapshot_2026-09-24.json"
        )
        self.preservation.parent.mkdir(mode=0o700)
        snapshot = {
            "snapshot_version": 1,
            "canonical_repository": {
                "origin_main": "abc",
                "path": "/preserved/canonical",
            },
            "services": {"heartbeats": {"codex-a": {"time": 1000, "status": "idle"}}},
            "open_task_mapping": [
                {
                    "issue": 101,
                    "task": "TASK-PRESERVED",
                    "title": "Preserved completed task",
                    "status": "DONE",
                }
            ],
            "worktrees": [
                {
                    "worktree": "/preserved/worktree",
                    "branch": "refs/heads/preserved",
                    "dirty": True,
                }
            ],
            "dirty_worktree_count": 1,
            "unmerged_local_branches": ["preserved abc123"],
        }
        self.preservation.write_text(json.dumps(snapshot, sort_keys=True))
        self.preservation.chmod(0o600)
        digest = hashlib.sha256(self.preservation.read_bytes()).hexdigest()
        self.approved_hash = mock.patch.object(
            operator_module, "APPROVED_PRESERVATION_SHA256", digest
        )
        self.approved_counts = mock.patch.object(
            operator_module,
            "APPROVED_PRESERVATION_COUNTS",
            {
                "worktrees": 1,
                "dirty_worktrees": 1,
                "unmerged_branches": 1,
                "unexplained_records": 0,
                "unreleased_live_leases": 0,
            },
        )
        self.approved_hash.start()
        self.approved_counts.start()
        self.registry.import_preservation_snapshot(
            snapshot,
            source_uri=str(self.preservation),
            source_sha256=digest,
            imported_at="2026-09-25T08:00:00Z",
        )
        self.release = self.root / "release"
        self._release()
        self.state = self.root / "state"
        self.worktrees = self.root / "worktrees"
        self.state.mkdir()
        self.worktrees.mkdir()
        self.config_path = self.root / "config.json"
        self.config_path.write_text(json.dumps(self.config(strict=True)))

    def tearDown(self):
        if self.release.exists():
            for path in sorted(
                (self.release, *self.release.rglob("*")),
                key=lambda value: len(value.parts),
            ):
                try:
                    path.chmod(0o700 if path.is_dir() else 0o600)
                except FileNotFoundError:
                    pass
        self.approved_counts.stop()
        self.approved_hash.stop()
        self.temporary.cleanup()

    def record_review_input(self, review_package_id, attempt_id, recorded_at):
        contract = {"task": review_package_id, "paths": ["scripts/factory_registry/operator.py"]}
        digest = hashlib.sha256(
            json.dumps(contract, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        input_id = f"review-input:{review_package_id}:{attempt_id}"
        self.registry.record_review_input(ReviewInput(
            id=input_id, review_package_id=review_package_id, target_package_id="TASK-201",
            implementation_attempt_id="implementation-attempt", implementation_commit=COMMIT,
            base_commit="b" * 40, pr_url="https://example.invalid/pr/1",
            contract_sha256=digest, contract=contract, validation_evidence={"focused_tests": "passed"},
            recorded_at=recorded_at,
        ))
        return digest, input_id

    def _review_packet_spec(self, *, review_id="TASK-202", target_id="TASK-201",
                            attempt_id="implementation-attempt", recorded_at):
        """Create the immutable packet consumed by the operator CLI, not a mock."""
        packet = self.root / f"packet-{review_id}"
        packet.mkdir()
        contract = {"task": target_id, "paths": ["scripts/factory_registry/operator.py"]}
        contents = {
            "base-to-implementation.diff": b"diff --git a/operator.py b/operator.py\n",
            "changed-files.txt": b"scripts/factory_registry/operator.py\n",
            "contract.json": json.dumps(contract, sort_keys=True).encode(),
            "validation-evidence.json": json.dumps({"focused_tests": "passed"}).encode(),
        }
        for name, content in contents.items():
            (packet / name).write_bytes(content)
        hashes = {name: hashlib.sha256(content).hexdigest() for name, content in contents.items()}
        manifest = {
            "schema_version": 1, "implementation_attempt_id": attempt_id,
            "base_commit": "b" * 40, "implementation_commit": COMMIT, "files": hashes,
        }
        manifest_bytes = json.dumps(manifest, sort_keys=True).encode()
        (packet / "manifest.json").write_bytes(manifest_bytes)
        return {
            "id": f"review-input:{review_id}:{attempt_id}", "review_package_id": review_id,
            "target_package_id": target_id, "implementation_attempt_id": attempt_id,
            "implementation_commit": COMMIT, "base_commit": "b" * 40,
            "pr_url": "https://example.invalid/pr/1", "contract": contract,
            "validation_evidence": {
                "ci": {"state": "SUCCESS", "implementation_commit": COMMIT,
                       "pr_url": "https://example.invalid/pr/1"},
                "review_packet": {"path": str(packet),
                                  "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
                                  "files": hashes},
            },
            "recorded_at": recorded_at,
        }

    def _bounded_review_fixture(self, *, publish_input=True):
        """Set up legacy history plus one completed target and its review evidence."""
        now = datetime.now(timezone.utc) - timedelta(minutes=5)
        observed_at = now.isoformat()
        self.sync_workers(observed_at)
        self.registry.register_feature(Feature("LEGACY-HISTORY", "Preserved history", 1, TaskStatus.READY))
        self.registry.register_work_package(WorkPackage(
            "LEGACY-PARENT-1", "LEGACY-HISTORY", "Preserved completed parent", "OPERATIONS",
            Lane.PLATFORM, ("documentation",), 1, ("preserved",), status=TaskStatus.VERIFY_REVIEW,
        ))
        self.registry.register_work_package(WorkPackage(
            "LEGACY-PARENT-2", "LEGACY-HISTORY", "Preserved failed-review target", "OPERATIONS",
            Lane.PLATFORM, ("documentation",), 1, ("preserved",), status=TaskStatus.DONE,
        ))
        self.registry.register_work_package(WorkPackage(
            "LEGACY-FAILED-REVIEW", "LEGACY-HISTORY", "Preserved failed review", "ASSURANCE",
            Lane.ASSURANCE, ("independent-review",), 1, ("preserved",), status=TaskStatus.BLOCKED,
            kind=PackageKind.REVIEW, dependency_ids=("LEGACY-PARENT-2",),
        ))
        feature, implementation, review = parse_canary_spec(self.canary())
        self.registry.register_canary_bundle(
            feature, implementation, review,
            expected_revision=self.registry.dispatch_control()["revision"], recorded_at=observed_at,
        )
        control = self.registry.dispatch_control()
        self.registry.set_dispatch_control(
            expected_revision=control["revision"], expected_mode="PAUSED", new_mode="LIVE",
            kill_switch_engaged=False, changed_at=(now + timedelta(seconds=1)).isoformat(),
            reason="bounded review fixture",
        )
        self.registry.acquire_lease(
            "TASK-201", "codex-a", acquired_at=(now + timedelta(seconds=2)).isoformat(),
            expires_at=(now + timedelta(minutes=10)).isoformat(),
        )
        self.registry.begin_attempt_runtime(
            "implementation-attempt", package_id="TASK-201", worker_id="codex-a",
            runner_pid=os.getpid(), started_at=(now + timedelta(seconds=3)).isoformat(),
            expected_revision=self.registry.dispatch_control()["revision"],
        )
        self.registry.finish_attempt_runtime(
            "implementation-attempt", ended_at=(now + timedelta(seconds=4)).isoformat(),
            outcome="SUCCEEDED", next_status=TaskStatus.VERIFY_REVIEW, reason="completed target",
        )
        self.registry.engage_dispatch_kill_switch(
            changed_at=(now + timedelta(seconds=5)).isoformat(), reason="fixture drained",
        )
        RunnerRegistryControl(self.database).finalize_paused(reason="fixture ownership drained")
        spec = self._review_packet_spec(recorded_at=(now + timedelta(seconds=6)).isoformat())
        if publish_input:
            self.registry.record_operator_review_input(
                operator_module.parse_review_input_spec(spec),
                expected_revision=self.registry.dispatch_control()["revision"],
            )
        return now, spec

    def _release(self):
        source_root = Path(__file__).resolve().parents[2]
        manifest = []
        for relative in sorted(REQUIRED_RELEASE_FILES):
            source = source_root / relative
            destination = self.release / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            manifest.append(f"{hashlib.sha1(destination.read_bytes()).hexdigest()}  {relative}")
        (self.release / "COMMIT").write_text(COMMIT + "\n")
        manifest.append(
            f"{hashlib.sha1((self.release / 'COMMIT').read_bytes()).hexdigest()}  COMMIT"
        )
        (self.release / "MANIFEST.sha1").write_text("\n".join(manifest) + "\n")

    def config(self, *, strict):
        value = {
            "repo": str(self.root / "repo"),
            "github": "owner/repo",
            "state": str(self.state),
            "worktrees": str(self.worktrees),
            "path": "/usr/bin:/bin",
            "gh": str(self.release.resolve() / "scripts" / "runner" / "github.py") if strict
            else "/old/release/scripts/runner/github.py",
            "git": "/usr/bin/git",
            "pnpm": "/usr/bin/true",
            "allowed_authors": ["owner"],
            "agent_timeout": 1800,
            "agents": {
                "codex-a": {
                    "provider": "openai", "account": "a", "slots": 1,
                    "model": "model",
                    "command": ["/opt/homebrew/bin/codex", "exec", "--disable", "multi_agent"],
                    "env": {},
                },
                "codex-b": {
                    "provider": "openai", "account": "b", "slots": 1,
                    "model": "model",
                    "command": ["/opt/homebrew/bin/codex", "exec", "--disable", "multi_agent"],
                    "env": {},
                },
                "claude": {
                    "provider": "anthropic", "account": "c", "slots": 1,
                    "model": "model",
                    "command": (
                        [
                            sys.executable,
                            str(self.release.resolve() / "scripts" / "runner" / "claude_keychain.py"),
                            "exec",
                            "/opt/homebrew/bin/claude",
                            "-p",
                            "--tools",
                            "Read,Edit,Write,Glob,Grep",
                        ]
                        if strict else
                        ["/opt/homebrew/bin/claude", "-p", "--tools", "Read,Edit,Write,Glob,Grep"]
                    ),
                    "env": {},
                },
            },
        }
        if strict:
            value.update({
                "registry_database": str(self.database),
                "registry_lease_seconds": 2100,
                "registry_renew_interval_seconds": 30,
                "usage_policy": {
                    "caution_percent": 90,
                    "checkpoint_percent": 95,
                    "hard_stop_percent": 98,
                    "stale_after_seconds": 3600,
                    "unknown_behavior": "defer",
                },
            })
            value["agents"]["codex-a"].update(
                capacity_mode="percentage", capacity_scopes=["short_window", "weekly_window"]
            )
            value["agents"]["codex-b"].update(
                capacity_mode="percentage", capacity_scopes=["short_window", "weekly_window"]
            )
            value["agents"]["claude"].update(
                capacity_mode="provider_signal", capacity_scopes=["provider_signal"]
            )
        return value

    def migration(self):
        return {
            "agents": {
                "codex-a": {"capacity_mode": "percentage", "capacity_scopes": ["short_window", "weekly_window"]},
                "codex-b": {"capacity_mode": "percentage", "capacity_scopes": ["short_window", "weekly_window"]},
                "claude": {"capacity_mode": "provider_signal", "capacity_scopes": ["provider_signal"]},
            }
        }

    def telemetry(self, worker_id, *, role="WORKER", reviewer=False, provider_signal=False, now=None):
        now = now or utc_now()
        mode = "provider_signal" if provider_signal else "percentage"
        scopes = ["provider_signal"] if provider_signal else ["short_window", "weekly_window"]
        capabilities = ["documentation"]
        lanes = ["PLATFORM"]
        if reviewer:
            capabilities = ["review", "independent-review"]
            lanes = ["ASSURANCE"]
        if role == "ORCHESTRA":
            capabilities = ["coordination"]
            lanes = []
        worker = {
            "id": worker_id,
            "display_name": worker_id,
            "role": role,
            "availability": "IDLE",
            "capabilities": capabilities,
            "approved_lanes": lanes,
            "last_heartbeat_at": now,
            "usage_state": "NORMAL",
            "provider_diagnostics": {
                "provider": "anthropic" if provider_signal else "openai",
                "capacity_mode": mode,
                "capacity_scopes": scopes,
                "service_state": "healthy",
                "authentication_state": "valid",
                "live_invocation_state": "succeeded",
            },
        }
        usages = []
        for scope in scopes:
            value = {
                "id": f"usage:{worker_id}:{scope}:{now}",
                "worker_id": worker_id,
                "capacity_scope": scope,
                "capacity_mode": mode,
                "state": "NORMAL",
                "observed_at": now,
            }
            if provider_signal:
                value.update(
                    service_state="healthy",
                    authentication_state="valid",
                    live_invocation_state="succeeded",
                    limit_signal="NONE",
                )
            else:
                value["consumed_percent"] = 10
            usages.append(value)
        return {"worker": worker, "usage_observations": usages}

    def sync_workers(self, now=None):
        now = now or utc_now()
        for payload in (
            self.telemetry("orchestra", role="ORCHESTRA", now=now),
            self.telemetry("codex-a", now=now),
            self.telemetry("claude", reviewer=True, provider_signal=True, now=now),
        ):
            worker, usage = validate_telemetry_payload(payload, now)
            revision = self.registry.dispatch_control()["revision"]
            self.registry.sync_worker_telemetry(
                worker, usage, expected_revision=revision, recorded_at=now
            )

    def canary(self):
        implementation_contract = {
            "task": "TASK-201",
            "paths": ["docs/factory/A5_CANARY_RESULT.md"],
            "instructions": "Write the deterministic canary evidence document.",
            "depends_on": [],
            "lane": "PLATFORM",
            "kind": "PARENT",
            "capacity_size": "VERY_SMALL",
            "capacity_risk": "BOUNDED",
        }
        review_contract = {
            "task": "TASK-202",
            "paths": ["docs/factory/A5_CANARY_REVIEW.md"],
            "instructions": "Independently review the canary evidence.",
            "depends_on": [201],
            "lane": "ASSURANCE",
            "kind": "REVIEW",
            "capacity_size": "VERY_SMALL",
            "capacity_risk": "BOUNDED",
        }
        return {
            "feature": {"id": "A5-CANARY", "title": "A5 canary", "priority": 100},
            "implementation": {
                "id": "TASK-201", "feature_id": "A5-CANARY", "title": "Canary implementation",
                "category": "OPERATIONS", "lane": "PLATFORM", "kind": "PARENT",
                "required_capabilities": ["documentation"], "priority": 100,
                "acceptance_criteria": ["Create only the allowed evidence file"],
                "capacity_size": "VERY_SMALL", "capacity_risk": "BOUNDED",
                "dependency_ids": [], "queue_contract": implementation_contract,
            },
            "review": {
                "id": "TASK-202", "feature_id": "A5-CANARY", "title": "Canary review",
                "category": "ASSURANCE", "lane": "ASSURANCE", "kind": "REVIEW",
                "required_capabilities": ["independent-review"], "priority": 99,
                "acceptance_criteria": ["Reviewer differs from implementer"],
                "capacity_size": "VERY_SMALL", "capacity_risk": "BOUNDED",
                "dependency_ids": ["TASK-201"], "queue_contract": review_contract,
            },
        }

    def test_v2_canary_registration_rejects_incomplete_readiness_shape(self):
        spec = self.canary()
        contract = spec["implementation"]["queue_contract"]
        contract["schema_version"] = 2
        contract["readiness"] = {
            "base_commit": "a" * 40, "planning_paths": ["docs/NORTH_STAR.md"],
            "existing_paths": [], "new_paths": ["docs/factory/A5_CANARY_RESULT.md"],
            "integration_paths": [], "test_paths": ["scripts/runner/test_registry_control.py"],
            "dependency_kinds": {},
        }
        with self.assertRaisesRegex(OperatorError, "INTEGRATION_PATHS_INVALID"):
            parse_canary_spec(spec)

    def test_v2_canary_registration_pins_exclusive_paths(self):
        spec = self.canary()
        contract = spec["implementation"]["queue_contract"]
        contract["schema_version"] = 2
        contract["readiness"] = {
            "base_commit": "a" * 40, "planning_paths": ["docs/NORTH_STAR.md"],
            "existing_paths": [], "new_paths": ["docs/factory/A5_CANARY_RESULT.md"],
            "integration_paths": ["docs/factory/A5_CANARY_RESULT.md"],
            "test_paths": ["docs/factory/A5_CANARY_RESULT.md"],
            "dependency_kinds": {},
        }
        _, implementation, _ = parse_canary_spec(spec)
        self.assertEqual(implementation.provider_diagnostics["exclusive_paths"], contract["paths"])
        spec["implementation"]["provider_diagnostics"] = {"exclusive_paths": ["other.py"]}
        with self.assertRaisesRegex(OperatorError, "exclusive paths mismatch"):
            parse_canary_spec(spec)

    def followup_review(self):
        contract = {
            "task": "TASK-203",
            "paths": ["docs/factory/A5_CANARY_REVIEW_RETRY.md"],
            "instructions": "Independently re-review the preserved canary implementation.",
            "depends_on": [201],
            "lane": "ASSURANCE",
            "kind": "REVIEW",
            "capacity_size": "VERY_SMALL",
            "capacity_risk": "BOUNDED",
        }
        return {
            "review": {
                "id": "TASK-203",
                "feature_id": "A5-CANARY",
                "title": "Canary follow-up review",
                "category": "ASSURANCE",
                "lane": "ASSURANCE",
                "kind": "REVIEW",
                "required_capabilities": ["independent-review"],
                "priority": 98,
                "acceptance_criteria": ["Reviewer differs from implementer"],
                "capacity_size": "VERY_SMALL",
                "capacity_risk": "BOUNDED",
                "source_ref": 312,
                "dependency_ids": ["TASK-201"],
                "queue_contract": contract,
            }
        }

    def test_telemetry_canary_and_worker_gate_are_revision_checked(self):
        now = utc_now()
        self.sync_workers(now)
        feature, implementation, review = parse_canary_spec(self.canary())
        revision = self.registry.dispatch_control()["revision"]
        new_revision = self.registry.register_canary_bundle(
            feature, implementation, review,
            expected_revision=revision, recorded_at=now,
        )
        extra = self.telemetry("extra", now=now)
        extra_worker, extra_usage = validate_telemetry_payload(extra, now)
        with self.assertRaisesRegex(RegistryConflict, "REGISTRY_REVISION_CHANGED"):
            self.registry.sync_worker_telemetry(
                extra_worker,
                extra_usage,
                expected_revision=revision,
                recorded_at=now,
            )
        evidence = preflight(
            self.database, self.config_path, self.release, self.preservation,
            COMMIT, new_revision, observed_at=now, require_permissions_gate=False,
            require_workers=True, canary_feature_id="A5-CANARY",
        )
        self.assertEqual(evidence["worker_gate"]["independent_pairs"], [["codex-a", "claude"]])

    def test_preservation_gate_recomputes_actual_imported_rows(self):
        deletions = (
            "DELETE FROM preserved_artifacts WHERE kind='WORKTREE'",
            "DELETE FROM work_packages WHERE id='TASK-PRESERVED'",
            "DELETE FROM workers WHERE id='legacy-worker:codex-a'",
            "UPDATE preserved_artifacts SET dirty=0 WHERE kind='WORKTREE'",
            "UPDATE work_packages SET status='READY' WHERE id='TASK-PRESERVED'",
            "UPDATE workers SET availability='IDLE' WHERE id='legacy-worker:codex-a'",
        )
        for statement in deletions:
            with self.subTest(statement=statement):
                copy = self.database.parent / f"copy-{hashlib.sha256(statement.encode()).hexdigest()}.sqlite3"
                with sqlite3.connect(self.database) as source, sqlite3.connect(copy) as target:
                    source.backup(target)
                with sqlite3.connect(copy) as connection:
                    connection.execute("PRAGMA foreign_keys=ON")
                    connection.execute(statement)
                with self.assertRaisesRegex(OperatorError, "actual_preserved"):
                    preflight(
                        copy,
                        self.config_path,
                        self.release,
                        self.preservation,
                        COMMIT,
                        self.registry.dispatch_control()["revision"],
                        require_config=False,
                        require_permissions_gate=False,
                    )

    def test_release_gate_rejects_unmanifested_or_omitted_runtime_files(self):
        runtime = self.release / "scripts" / "runner" / "registry_control.py"
        original = runtime.read_bytes()
        runtime.write_bytes(original + b"\n# unreviewed change\n")
        with self.assertRaisesRegex(OperatorError, "manifest mismatch"):
            preflight(self.database, self.config_path, self.release, self.preservation, COMMIT, self.registry.dispatch_control()["revision"], require_permissions_gate=False)
        runtime.write_bytes(original)
        extra = self.release / "scripts" / "runner" / "unreviewed.py"
        extra.write_text("raise RuntimeError('must not execute')\n")
        with self.assertRaisesRegex(OperatorError, "manifest is incomplete"):
            preflight(self.database, self.config_path, self.release, self.preservation, COMMIT, self.registry.dispatch_control()["revision"], require_permissions_gate=False)
        extra.unlink()
        manifest = self.release / "MANIFEST.sha1"
        manifest.write_text("\n".join(line for line in manifest.read_text().splitlines() if not line.endswith("  scripts/runner/registry_control.py")) + "\n")
        with self.assertRaisesRegex(OperatorError, "manifest is incomplete"):
            preflight(self.database, self.config_path, self.release, self.preservation, COMMIT, self.registry.dispatch_control()["revision"], require_permissions_gate=False)

    def test_release_gate_rejects_missing_review_protocol_runtime_dependency(self):
        manifest = self.release / "MANIFEST.sha1"
        manifest.write_text("\n".join(line for line in manifest.read_text().splitlines() if not line.endswith("  scripts/runner/review_protocol.py")) + "\n")
        with self.assertRaisesRegex(OperatorError, "manifest is incomplete"):
            preflight(self.database, self.config_path, self.release, self.preservation, COMMIT, self.registry.dispatch_control()["revision"], require_permissions_gate=False)

    def test_release_manifest_includes_commit_and_rejects_duplicate(self):
        manifest = self.release / "MANIFEST.sha1"
        lines = manifest.read_text().splitlines()
        self.assertTrue(any(line.endswith("  COMMIT") for line in lines))
        manifest.write_text("\n".join([*lines, lines[0]]) + "\n")
        with self.assertRaisesRegex(OperatorError, "duplicate paths"):
            preflight(
                self.database, self.config_path, self.release, self.preservation,
                COMMIT, self.registry.dispatch_control()["revision"],
                require_permissions_gate=False,
            )

    def test_release_gate_rejects_symlink_and_special_file(self):
        link = self.release / "unreviewed-link"
        link.symlink_to(self.release / "COMMIT")
        with self.assertRaisesRegex(OperatorError, "symlink"):
            preflight(
                self.database, self.config_path, self.release, self.preservation,
                COMMIT, self.registry.dispatch_control()["revision"],
                require_permissions_gate=False,
            )
        link.unlink()
        fifo = self.release / "unreviewed-fifo"
        os.mkfifo(fifo)
        with self.assertRaisesRegex(OperatorError, "special file"):
            preflight(
                self.database, self.config_path, self.release, self.preservation,
                COMMIT, self.registry.dispatch_control()["revision"],
                require_permissions_gate=False,
            )

    def test_preservation_is_pinned_and_installed_owner_only(self):
        self.assertEqual(
            APPROVED_PRESERVATION_SHA256,
            "7d47f980d66bf84676cb6d0c24a7eeab0efe40bbe2451d7b27dfd1d6ed94fce6",
        )
        source = self.root / "approved-preservation.json"
        source.write_bytes(self.preservation.read_bytes())
        harden_paths(self.database, self.config_path, self.release)
        revision = self.registry.dispatch_control()["revision"]
        with self.assertRaisesRegex(OperatorError, "0600"):
            store_preservation_evidence(
                self.database, source, self.release, COMMIT, revision
            )
        source.chmod(0o600)
        evidence = store_preservation_evidence(
            self.database, source, self.release, COMMIT, revision
        )
        self.assertEqual(evidence["sha256"], operator_module.APPROVED_PRESERVATION_SHA256)
        self.assertEqual(stat.S_IMODE(Path(evidence["path"]).stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(Path(evidence["path"]).parent.stat().st_mode), 0o700)
        source.write_bytes(source.read_bytes() + b"\n")
        source.chmod(0o600)
        with self.assertRaisesRegex(OperatorError, "not the approved"):
            store_preservation_evidence(
                self.database, source, self.release, COMMIT, revision
            )

    def test_config_gate_rejects_slots_and_unreviewed_commands(self):
        cases = []
        slots = self.config(strict=True)
        slots["agents"]["codex-a"]["slots"] = 2
        cases.append((slots, "exactly one slot"))
        github = self.config(strict=True)
        github["gh"] = "/old/release/scripts/runner/github.py"
        cases.append((github, "selected immutable release"))
        codex = self.config(strict=True)
        codex["agents"]["codex-a"]["command"][0] = "/usr/bin/true"
        cases.append((codex, "must invoke codex"))
        claude = self.config(strict=True)
        claude["agents"]["claude"]["command"][1] = "/tmp/claude_keychain.py"
        cases.append((claude, "selected release"))
        arbitrary_claude = self.config(strict=True)
        arbitrary_claude["agents"]["claude"]["command"][3] = "/usr/bin/true"
        cases.append((arbitrary_claude, "selected release"))
        for value, message in cases:
            with self.subTest(message=message):
                self.config_path.write_text(json.dumps(value))
                with self.assertRaisesRegex(OperatorError, message):
                    preflight(
                        self.database, self.config_path, self.release, self.preservation,
                        COMMIT, self.registry.dispatch_control()["revision"],
                        require_permissions_gate=False,
                    )

    def _downgrade_fixture_to_v3(self) -> int:
        with sqlite3.connect(self.database) as connection:
            connection.execute("DROP TRIGGER historical_package_reconciliations_are_append_only_update")
            connection.execute("DROP TRIGGER historical_package_reconciliations_are_append_only_delete")
            connection.execute("DROP TABLE historical_package_reconciliations")
            connection.execute(
                "DROP TRIGGER control_operation_receipts_are_append_only_update"
            )
            connection.execute(
                "DROP TRIGGER control_operation_receipts_are_append_only_delete"
            )
            connection.execute("DROP TABLE control_operation_receipts")
            connection.execute("DROP TRIGGER review_outcomes_are_append_only_update")
            connection.execute("DROP TRIGGER review_outcomes_are_append_only_delete")
            connection.execute("DROP TABLE review_outcomes")
            connection.execute(
                "UPDATE registry_metadata SET value='3' WHERE key='schema_version'"
            )
        harden_paths(self.database, self.config_path, self.release)
        return self.registry.dispatch_control()["revision"]

    def _downgrade_fixture_to_v4(self) -> int:
        with sqlite3.connect(self.database) as connection:
            connection.execute("DROP TRIGGER historical_package_reconciliations_are_append_only_update")
            connection.execute("DROP TRIGGER historical_package_reconciliations_are_append_only_delete")
            connection.execute("DROP TABLE historical_package_reconciliations")
            connection.execute(
                "DROP TRIGGER control_operation_receipts_are_append_only_update"
            )
            connection.execute(
                "DROP TRIGGER control_operation_receipts_are_append_only_delete"
            )
            connection.execute("DROP TABLE control_operation_receipts")
            connection.execute(
                "UPDATE registry_metadata SET value='4' WHERE key='schema_version'"
            )
        harden_paths(self.database, self.config_path, self.release)
        return self.registry.dispatch_control()["revision"]

    def _historical_repository(self) -> tuple[Path, str, str]:
        """Build the two-commit ancestry required by reconciliation tests."""
        repository = self.root / "historical-repository"
        repository.mkdir()
        def git(*arguments: str) -> str:
            return subprocess.run(
                ["git", "-C", str(repository), *arguments], check=True,
                capture_output=True, text=True,
            ).stdout.strip()
        git("init", "--quiet")
        git("config", "user.name", "Registry Test")
        git("config", "user.email", "registry-test@example.test")
        marker = repository / "history.txt"
        marker.write_text("historical\n")
        git("add", "history.txt")
        git("commit", "--quiet", "-m", "historical")
        historical = git("rev-parse", "HEAD")
        marker.write_text("historical\nintegrated\n")
        git("add", "history.txt")
        git("commit", "--quiet", "-m", "integration")
        return repository, historical, git("rev-parse", "HEAD")

    def test_reviewed_registry_v6_migration_creates_empty_reconciliation_store(self):
        revision = self._downgrade_fixture_to_v4()
        migrate_registry_v4_to_v5(self.database, self.release, self.preservation, COMMIT, revision)
        result = migrate_registry_v5_to_v6(self.database, self.release, self.preservation, COMMIT, revision)
        self.assertTrue(result["passed"])
        self.assertEqual(result["source_schema"], 5)
        self.assertEqual(result["schema_version"], 6)
        with sqlite3.connect(self.database) as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM historical_package_reconciliations").fetchone()[0], 0)

    def test_historical_reconciliation_operator_validates_exact_git_ancestry_and_repository_paths(self):
        repository, historical, head = self._historical_repository()
        def spec(**changes):
            value = {"id": "historical-reconcile", "package_id": "STALE",
                     "disposition": "INTEGRATED_ELSEWHERE", "repository": str(repository),
                     "historical_commit": historical, "integration_commit": head,
                     "evidence_uri": "https://example.test/evidence", "recorded_at": "2026-09-28T11:00:00Z"}
            value.update(changes)
            return value
        self.assertEqual(parse_historical_reconciliation_spec(spec())["historical_commit"], historical)
        with mock.patch.object(operator_module, "preflight") as preflight_gate, mock.patch.object(
            SQLiteRegistry, "reconcile_historical_package", return_value=9
        ) as reconcile_write:
            result = reconcile_historical_package(
                self.database, self.config_path, self.release, self.preservation, COMMIT, 8, spec()
            )
        self.assertTrue(result["passed"])
        self.assertEqual(result["revision"], 9)
        preflight_gate.assert_called_once()
        self.assertEqual(reconcile_write.call_args.kwargs["repository_head"], head)
        with self.assertRaisesRegex(OperatorError, "ancestry evidence failed"):
            reconcile_historical_package(self.database, self.config_path, self.release, self.preservation, COMMIT, 8,
                                         spec(historical_commit=head, integration_commit=historical))
        with self.assertRaisesRegex(OperatorError, "provenance is invalid"):
            parse_historical_reconciliation_spec(spec(historical_commit=historical[:12]))
        missing = self.root / "missing-repository"
        file_path = self.root / "not-a-repository"
        file_path.write_text("not a directory")
        link = self.root / "repository-link"
        link.symlink_to(repository, target_is_directory=True)
        for path in (missing, file_path, link):
            with self.subTest(path=path), self.assertRaisesRegex(OperatorError, "real directory"):
                reconcile_historical_package(self.database, self.config_path, self.release, self.preservation, COMMIT, 8,
                                             spec(repository=str(path)))
        not_a_git_repository = self.root / "not-a-git-repository"
        not_a_git_repository.mkdir()
        with self.assertRaisesRegex(OperatorError, "cannot resolve reconciliation commit"):
            reconcile_historical_package(self.database, self.config_path, self.release, self.preservation, COMMIT, 8,
                                         spec(repository=str(not_a_git_repository)))

    def test_reconcile_historical_package_cli_records_append_only_reconciliation(self):
        repository, historical, head = self._historical_repository()
        self.registry.register_feature(Feature("HISTORY", "History", 1, TaskStatus.READY))
        self.registry.register_work_package(WorkPackage(
            "STALE", "HISTORY", "stale historical package", "OPERATIONS", Lane.PLATFORM,
            ("registry",), 1, ("preserved",), status=TaskStatus.BLOCKED,
        ))
        self.state.chmod(0o700)
        self.worktrees.chmod(0o700)
        harden_paths(self.database, self.config_path, self.release)
        spec_path = self.root / "historical-reconciliation.json"
        spec_path.write_text(json.dumps({
            "id": "historical-cli", "package_id": "STALE", "disposition": "INTEGRATED_ELSEWHERE",
            "repository": str(repository), "historical_commit": historical, "integration_commit": head,
            "evidence_uri": "https://example.test/evidence", "recorded_at": "2026-09-28T11:00:00Z",
        }))
        output, errors = StringIO(), StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            self.assertEqual(operator_main([
                "reconcile-historical-package", "--database", str(self.database), "--config", str(self.config_path),
                "--release", str(self.release), "--release-commit", COMMIT, "--preservation", str(self.preservation),
                "--expect-revision", str(self.registry.dispatch_control()["revision"]), "--spec", str(spec_path),
            ]), 0, errors.getvalue())
        result = json.loads(output.getvalue())
        self.assertTrue(result["passed"])
        self.assertFalse(result["review_passed"])
        with sqlite3.connect(self.database) as connection:
            self.assertEqual(connection.execute(
                "SELECT disposition FROM historical_package_reconciliations WHERE id='historical-cli'"
            ).fetchone()[0], "INTEGRATED_ELSEWHERE")
            with self.assertRaisesRegex(sqlite3.IntegrityError, "APPEND_ONLY"):
                connection.execute("DELETE FROM historical_package_reconciliations WHERE id='historical-cli'")

    def test_reviewed_registry_v5_migration_preserves_v4_history(self):
        self.registry.register_feature(
            Feature("HISTORY", "History", 1, TaskStatus.READY)
        )
        revision = self._downgrade_fixture_to_v4()
        observed = status(self.database)
        result = migrate_registry_v4_to_v5(
            self.database, self.release, self.preservation, COMMIT, revision
        )
        self.assertTrue(result["passed"])
        self.assertEqual(result["source_schema"], 4)
        self.assertEqual(result["schema_version"], 5)
        self.assertEqual(result["control"], observed["control"])
        self.assertEqual(
            status(self.database)["database_checks"]["schema_version"], "5"
        )
        with sqlite3.connect(self.database) as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT count(*) FROM control_operation_receipts"
                ).fetchone()[0],
                0,
            )
            self.assertEqual(
                connection.execute(
                    "SELECT title FROM features WHERE id='HISTORY'"
                ).fetchone()[0],
                "History",
            )

    def test_reviewed_registry_v5_migration_can_restore_exact_v4_backup(self):
        self.registry.register_feature(
            Feature("HISTORY", "History", 1, TaskStatus.READY)
        )
        revision = self._downgrade_fixture_to_v4()
        result = migrate_registry_v4_to_v5(
            self.database, self.release, self.preservation, COMMIT, revision
        )
        backup = Path(result["backup"]["path"])
        restored = restore_registry_v4_backup(
            self.database,
            backup,
            self.release,
            self.preservation,
            COMMIT,
            result["backup"]["sha256"],
            revision,
        )
        self.assertTrue(restored["passed"])
        self.assertEqual(restored["schema_version"], 4)
        self.assertEqual(
            status(self.database)["database_checks"]["schema_version"], "4"
        )
        with sqlite3.connect(self.database) as connection:
            self.assertEqual(connection.execute(
                "SELECT title FROM features WHERE id='HISTORY'"
            ).fetchone()[0], "History")
            self.assertEqual(connection.execute(
                "SELECT count(*) FROM sqlite_schema "
                "WHERE type='table' AND name='control_operation_receipts'"
            ).fetchone()[0], 0)

    def test_restore_v4_rejects_any_v5_operation_receipt(self):
        revision = self._downgrade_fixture_to_v4()
        result = migrate_registry_v4_to_v5(
            self.database, self.release, self.preservation, COMMIT, revision
        )
        backup = Path(result["backup"]["path"])
        with sqlite3.connect(self.database) as connection:
            connection.execute(
                "INSERT INTO control_operation_receipts "
                "(operation_id, operation_kind, request_sha256, result_json, recorded_at) "
                "VALUES ('used', 'TEST', ?, '{}', '2026-09-25T10:00:00Z')",
                ("0" * 64,),
            )
        with self.assertRaisesRegex(OperatorError, "operation receipts exist"):
            restore_registry_v4_backup(
                self.database,
                backup,
                self.release,
                self.preservation,
                COMMIT,
                result["backup"]["sha256"],
                revision,
            )
        self.assertEqual(
            status(self.database)["database_checks"]["schema_version"], "5"
        )

    def test_restore_v4_rejects_changed_backup(self):
        revision = self._downgrade_fixture_to_v4()
        result = migrate_registry_v4_to_v5(
            self.database, self.release, self.preservation, COMMIT, revision
        )
        backup = Path(result["backup"]["path"])
        with sqlite3.connect(backup) as connection:
            connection.execute(
                "UPDATE registry_metadata SET value='changed' WHERE key='revision'"
            )
        backup.chmod(0o600)
        with self.assertRaisesRegex(OperatorError, "backup SHA-256 mismatch"):
            restore_registry_v4_backup(
                self.database,
                backup,
                self.release,
                self.preservation,
                COMMIT,
                result["backup"]["sha256"],
                revision,
            )
        self.assertEqual(
            status(self.database)["database_checks"]["schema_version"], "5"
        )

    def test_restore_v4_rejects_same_count_ownership_provenance_change(self):
        self.registry.register_feature(
            Feature("OWNERSHIP", "Ownership", 1, TaskStatus.READY)
        )
        self.registry.register_worker(
            Worker("worker", "Worker", ("registry",), (Lane.PLATFORM,), usage_state="GREEN")
        )
        self.registry.register_work_package(WorkPackage(
            "OWNERSHIP-TASK", "OWNERSHIP", "Ownership task", "ORCHESTRATION",
            Lane.PLATFORM, ("registry",), 1, ("lease history preserved",),
            status=TaskStatus.READY,
        ))
        control = self.registry.dispatch_control()
        live_revision = self.registry.set_dispatch_control(
            expected_revision=control["revision"], expected_mode="PAUSED",
            new_mode="LIVE", kill_switch_engaged=False,
            changed_at="2026-09-25T10:00:00Z", reason="migration fixture",
        )
        lease = self.registry.acquire_lease(
            "OWNERSHIP-TASK", "worker",
            acquired_at="2026-09-25T10:01:00Z",
            expires_at="2026-09-25T10:30:00Z",
            expected_dispatch_revision=live_revision,
        )
        self.registry.release_lease(
            lease.id,
            released_at="2026-09-25T10:02:00Z",
            reason="fixture complete",
            next_status=TaskStatus.READY,
        )
        control = self.registry.dispatch_control()
        self.registry.set_dispatch_control(
            expected_revision=control["revision"], expected_mode="LIVE",
            new_mode="STOPPING", kill_switch_engaged=True,
            changed_at="2026-09-25T10:03:00Z", reason="migration fixture stopping",
        )
        control = self.registry.dispatch_control()
        self.registry.set_dispatch_control(
            expected_revision=control["revision"], expected_mode="STOPPING",
            new_mode="PAUSED", kill_switch_engaged=True,
            changed_at="2026-09-25T10:04:00Z", reason="migration fixture stopped",
        )
        revision = self._downgrade_fixture_to_v4()
        result = migrate_registry_v4_to_v5(
            self.database, self.release, self.preservation, COMMIT, revision
        )
        backup = Path(result["backup"]["path"])
        with sqlite3.connect(self.database) as connection:
            connection.execute(
                "UPDATE leases SET release_reason='rewritten' WHERE id=?",
                (lease.id,),
            )
        with self.assertRaisesRegex(OperatorError, "ownership provenance changed"):
            restore_registry_v4_backup(
                self.database,
                backup,
                self.release,
                self.preservation,
                COMMIT,
                result["backup"]["sha256"],
                revision,
            )

    def test_restore_v4_preserves_mutation_racing_after_initial_validation(self):
        revision = self._downgrade_fixture_to_v4()
        result = migrate_registry_v4_to_v5(
            self.database, self.release, self.preservation, COMMIT, revision
        )
        backup = Path(result["backup"]["path"])
        original_verify = operator_module.verify_preservation
        calls = 0

        def inject_mutation(snapshot, preservation_path):
            nonlocal calls
            calls += 1
            if calls == 2:
                control = self.registry.dispatch_control()
                self.registry.set_dispatch_control(
                    expected_revision=control["revision"],
                    expected_mode="PAUSED",
                    new_mode="STOPPING",
                    kill_switch_engaged=True,
                    changed_at="2026-09-25T10:05:00Z",
                    reason="concurrent authoritative stop",
                    operation_id="racing-stop",
                )
            return original_verify(snapshot, preservation_path)

        with mock.patch.object(
            operator_module, "verify_preservation", side_effect=inject_mutation
        ):
            with self.assertRaisesRegex(
                OperatorError, "revision changed before v4 restore"
            ):
                restore_registry_v4_backup(
                    self.database,
                    backup,
                    self.release,
                    self.preservation,
                    COMMIT,
                    result["backup"]["sha256"],
                    revision,
                )

        current = status(self.database)
        self.assertEqual(current["database_checks"]["schema_version"], "5")
        self.assertEqual(current["control"]["dispatch_mode"], "STOPPING")
        self.assertEqual(current["control"]["revision"], revision + 1)
        with sqlite3.connect(self.database) as connection:
            self.assertEqual(connection.execute(
                "SELECT count(*) FROM control_operation_receipts "
                "WHERE operation_id='racing-stop'"
            ).fetchone()[0], 1)
            self.assertEqual(connection.execute(
                "SELECT count(*) FROM task_events "
                "WHERE event_type='DISPATCH_CONTROL_CHANGED'"
            ).fetchone()[0], 1)

    def test_reviewed_registry_migration_and_restore(self):
        revision = self._downgrade_fixture_to_v3()
        observed = status(self.database)
        self.assertEqual(observed["database_checks"]["schema_version"], "3")
        self.assertEqual(observed["counts"]["review_outcomes"], 0)
        with self.assertRaisesRegex(OperatorError, "schema version"):
            preflight(
                self.database, self.config_path, self.release, self.preservation,
                COMMIT, revision, require_permissions_gate=False,
            )
        result = migrate_registry_v3_to_v4(
            self.database, self.release, self.preservation, COMMIT, revision
        )
        self.assertTrue(result["passed"])
        self.assertEqual(result["schema_version"], 4)
        backup = Path(result["backup"]["path"])
        self.assertEqual(stat.S_IMODE(backup.stat().st_mode), 0o600)
        self.assertEqual(status(self.database)["control"], observed["control"])
        restored = restore_registry_v3_backup(
            self.database,
            backup,
            self.release,
            self.preservation,
            COMMIT,
            result["backup"]["sha256"],
            revision,
        )
        self.assertTrue(restored["passed"])
        self.assertEqual(status(self.database)["database_checks"]["schema_version"], "3")

    def test_restore_rejects_backup_changed_after_migration(self):
        self.registry.register_feature(
            Feature("UNRELATED", "Original title", 1, TaskStatus.ON_DECK)
        )
        revision = self._downgrade_fixture_to_v3()
        result = migrate_registry_v3_to_v4(
            self.database, self.release, self.preservation, COMMIT, revision
        )
        backup = Path(result["backup"]["path"])
        with sqlite3.connect(backup) as connection:
            connection.execute(
                "UPDATE features SET title='Modified title' WHERE id='UNRELATED'"
            )
        backup.chmod(0o600)
        with self.assertRaisesRegex(OperatorError, "backup SHA-256 mismatch"):
            restore_registry_v3_backup(
                self.database,
                backup,
                self.release,
                self.preservation,
                COMMIT,
                result["backup"]["sha256"],
                revision,
            )
        self.assertEqual(status(self.database)["database_checks"]["schema_version"], "4")

    def test_status_safely_observes_v3_without_control_metadata(self):
        revision = self._downgrade_fixture_to_v3()
        with sqlite3.connect(self.database) as connection:
            connection.execute(
                "DELETE FROM registry_metadata WHERE key='control_schema_version'"
            )
        observed = status(self.database)
        self.assertFalse(observed["control"]["available"])
        self.assertEqual(observed["control"]["revision"], revision)
        self.assertEqual(
            observed["control"]["reason"], "CONTROL_SCHEMA_METADATA_MISSING"
        )
        with self.assertRaisesRegex(OperatorError, "schema version"):
            preflight(
                self.database, self.config_path, self.release, self.preservation,
                COMMIT, revision, require_permissions_gate=False,
            )
        with self.assertRaisesRegex(OperatorError, "control schema"):
            migrate_registry_v3_to_v4(
                self.database, self.release, self.preservation, COMMIT, revision
            )

    def test_registry_migration_failure_rolls_back_atomic_transaction(self):
        revision = self._downgrade_fixture_to_v3()
        with mock.patch.object(
            operator_module,
            "V3_TO_V4_STATEMENTS",
            (*operator_module.V3_TO_V4_STATEMENTS, "INVALID SQL"),
        ):
            with self.assertRaises(sqlite3.Error):
                migrate_registry_v3_to_v4(
                    self.database, self.release, self.preservation, COMMIT, revision
                )
        self.assertEqual(status(self.database)["database_checks"]["schema_version"], "3")
        with sqlite3.connect(self.database) as connection:
            self.assertIsNone(connection.execute(
                "SELECT 1 FROM sqlite_schema WHERE type='table' AND name='review_outcomes'"
            ).fetchone())

    def test_registry_post_verify_failure_restores_v3_backup(self):
        revision = self._downgrade_fixture_to_v3()
        original = operator_module.verify_preservation
        calls = 0

        def fail_after_commit(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 3:
                raise OperatorError("injected post-verify failure")
            return original(*args, **kwargs)

        with mock.patch.object(operator_module, "verify_preservation", fail_after_commit):
            with self.assertRaisesRegex(OperatorError, "post-verify"):
                migrate_registry_v3_to_v4(
                    self.database, self.release, self.preservation, COMMIT, revision
                )
        self.assertEqual(status(self.database)["database_checks"]["schema_version"], "3")

    def test_registry_fk_post_verify_failure_restores_clean_v3(self):
        revision = self._downgrade_fixture_to_v3()
        original_verify = operator_module._verify_migrated_v4

        def inject_foreign_key_violation(*args, **kwargs):
            with sqlite3.connect(self.database) as connection:
                connection.execute("PRAGMA foreign_keys=OFF")
                connection.execute(
                    """INSERT INTO review_outcomes
                       (id, review_package_id, target_package_id,
                        implementer_worker_id, reviewer_worker_id,
                        requested_at, decided_at, state, findings_json,
                        changes_requested_json, approval_evidence_ids_json)
                       VALUES ('invalid-review', 'missing-review', 'missing-target',
                               'missing-implementer', 'missing-reviewer',
                               '2026-09-25T08:00:00Z', '2026-09-25T08:00:01Z',
                               'APPROVED', '[]', '[]', '[\"missing-evidence\"]')"""
                )
            return original_verify(*args, **kwargs)

        with mock.patch.object(
            operator_module, "_verify_migrated_v4", inject_foreign_key_violation
        ):
            with self.assertRaisesRegex(
                OperatorError, 'foreign-key.*"succeeded":true'
            ):
                migrate_registry_v3_to_v4(
                    self.database, self.release, self.preservation, COMMIT, revision
                )
        observed = status(self.database)
        self.assertEqual(observed["database_checks"]["schema_version"], "3")
        self.assertEqual(observed["counts"]["review_outcomes"], 0)
        with sqlite3.connect(self.database) as connection:
            self.assertEqual(tuple(connection.execute("PRAGMA foreign_key_check")), ())
            self.assertIsNone(connection.execute(
                "SELECT 1 FROM sqlite_schema "
                "WHERE type='table' AND name='review_outcomes'"
            ).fetchone())

    def test_canary_registration_gate_rejects_missing_capability(self):
        now = utc_now()
        self.sync_workers(now)
        spec = self.canary()
        spec["implementation"]["required_capabilities"] = ["missing-capability"]
        feature, implementation, review = parse_canary_spec(spec)
        self.assertEqual(feature.id, "A5-CANARY")
        with self.assertRaisesRegex(OperatorError, "no eligible implementation worker"):
            canary_worker_gate(
                self.registry.dispatch_snapshot(observed_at=now),
                implementation,
                review,
                observed_at=now,
            )

    def _pause_canary_after_successful_implementation(
        self, *, implementer="codex-a", observed_at=None
    ):
        observed_at = observed_at or (
            datetime.now(timezone.utc) - timedelta(minutes=1)
        ).isoformat()
        feature, implementation, review = parse_canary_spec(self.canary())
        revision = self.registry.dispatch_control()["revision"]
        self.registry.register_canary_bundle(
            feature, implementation, review,
            expected_revision=revision, recorded_at=observed_at,
        )
        control = self.registry.dispatch_control()
        self.registry.set_dispatch_control(
            expected_revision=control["revision"], expected_mode="PAUSED",
            new_mode="LIVE", kill_switch_engaged=False,
            changed_at=observed_at, reason="fixture implementation",
        )
        self.registry.acquire_lease(
            "TASK-201", implementer,
            acquired_at=observed_at,
            expires_at=(
                datetime.fromisoformat(observed_at) + timedelta(minutes=5)
            ).isoformat(),
        )
        self.registry.begin_attempt_runtime(
            "implementation-attempt",
            package_id="TASK-201", worker_id=implementer,
            runner_pid=os.getpid(), started_at=observed_at,
            expected_revision=self.registry.dispatch_control()["revision"],
        )
        self.registry.finish_attempt_runtime(
            "implementation-attempt", ended_at=utc_now(), outcome="SUCCEEDED",
            next_status=TaskStatus.VERIFY_REVIEW,
            reason="implementation ready for review",
        )
        self.registry.engage_dispatch_kill_switch(
            changed_at=utc_now(), reason="fixture pause after implementation",
        )
        RunnerRegistryControl(self.database).finalize_paused(
            reason="fixture implementation ownership drained"
        )

    def test_enable_live_resumes_ready_review_from_verify_review(self):
        self.config_path.write_text(json.dumps(self.config(strict=False)))
        loaded = set()

        def launchctl(arguments, **kwargs):
            operation = arguments[1]
            if operation == "print":
                label = arguments[-1].rsplit("/", 1)[-1]
                return subprocess.CompletedProcess(
                    arguments, 0 if label in loaded else 1
                )
            if operation == "bootout":
                loaded.discard(arguments[-1].rsplit("/", 1)[-1])
                return subprocess.CompletedProcess(arguments, 0)
            if operation == "bootstrap":
                loaded.add(Path(arguments[-1]).stem)
                return subprocess.CompletedProcess(arguments, 0)
            raise AssertionError(arguments)

        prepare_dry_run(
            self.database, self.config_path, self.release, self.preservation,
            COMMIT, self.registry.dispatch_control()["revision"],
            self.migration(), home=self.root / "home", run=launchctl, uid=501,
        )
        now = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        self.sync_workers(now)
        self._pause_canary_after_successful_implementation(observed_at=now)

        evidence = enable_live(
            self.database, self.config_path, self.release, self.preservation,
            COMMIT, self.registry.dispatch_control()["revision"],
            "A5-CANARY", home=self.root / "home", run=launchctl, uid=501,
        )

        self.assertEqual(
            evidence["worker_gate"]["independent_pairs"],
            [["codex-a", "claude"]],
        )
        self.assertEqual(self.registry.dispatch_control()["dispatch_mode"], "LIVE")

    def test_worker_gate_preserves_review_separation_during_resume(self):
        now = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        for payload in (
            self.telemetry("orchestra", role="ORCHESTRA", now=now),
            self.telemetry("codex-a", now=now),
        ):
            if payload["worker"]["id"] == "codex-a":
                payload["worker"]["capabilities"].extend(
                    ["review", "independent-review"]
                )
                payload["worker"]["approved_lanes"].append("ASSURANCE")
            worker, usage = validate_telemetry_payload(payload, now)
            self.registry.sync_worker_telemetry(
                worker, usage,
                expected_revision=self.registry.dispatch_control()["revision"],
                recorded_at=now,
            )
        self._pause_canary_after_successful_implementation(observed_at=now)

        with self.assertRaisesRegex(OperatorError, "reviewer is not independent"):
            preflight(
                self.database, self.config_path, self.release, self.preservation,
                COMMIT, self.registry.dispatch_control()["revision"],
                observed_at=utc_now(), require_permissions_gate=False,
                require_workers=True, canary_feature_id="A5-CANARY",
            )

    def test_worker_gate_preserves_review_package_gates_during_resume(self):
        now = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        self.sync_workers(now)
        self._pause_canary_after_successful_implementation(observed_at=now)
        future = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
        with sqlite3.connect(self.database) as connection:
            connection.execute(
                "UPDATE work_packages SET ready_at=? WHERE id='TASK-202'",
                (future,),
            )

        with self.assertRaisesRegex(OperatorError, "no eligible independent reviewer"):
            preflight(
                self.database, self.config_path, self.release, self.preservation,
                COMMIT, self.registry.dispatch_control()["revision"],
                observed_at=utc_now(), require_permissions_gate=False,
                require_workers=True, canary_feature_id="A5-CANARY",
            )

    def test_worker_gate_rejects_extra_same_feature_dispatchable_package(self):
        now = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        self.sync_workers(now)
        self._pause_canary_after_successful_implementation(observed_at=now)
        self.registry.register_work_package(WorkPackage(
            "TASK-203", "A5-CANARY", "Unexpected canary test", "OPERATIONS",
            Lane.PLATFORM, ("documentation",), 98,
            ("This package must not dispatch during the review canary.",),
            status=TaskStatus.READY, kind=PackageKind.TEST,
        ))

        with self.assertRaisesRegex(OperatorError, "REVIEW packages only"):
            preflight(
                self.database, self.config_path, self.release, self.preservation,
                COMMIT, self.registry.dispatch_control()["revision"],
                observed_at=utc_now(), require_permissions_gate=False,
                require_workers=True, canary_feature_id="A5-CANARY",
            )

    def test_status_cli_emits_structured_evidence(self):
        output = StringIO()
        with redirect_stdout(output):
            result = operator_main([
                "status",
                "--database",
                str(self.database),
                "--observed-at",
                "2026-09-25T08:00:00Z",
            ])
        self.assertEqual(result, 0)
        evidence = json.loads(output.getvalue())
        self.assertEqual(evidence["kind"], "threadline-factory-operator-status")
        self.assertEqual(evidence["database"], str(self.database))

    def test_queue_contract_is_checked_before_live_claim(self):
        now = utc_now()
        self.sync_workers(now)
        feature, implementation, review = parse_canary_spec(self.canary())
        revision = self.registry.dispatch_control()["revision"]
        self.registry.register_canary_bundle(
            feature, implementation, review,
            expected_revision=revision, recorded_at=now,
        )
        control = self.registry.dispatch_control()
        self.registry.set_dispatch_control(
            expected_revision=control["revision"], expected_mode="PAUSED",
            new_mode="LIVE", kill_switch_engaged=False, changed_at=utc_now(),
            reason="test canary",
        )
        body = dict(self.canary()["implementation"]["queue_contract"])
        body["instructions"] = "Different instructions"
        with self.assertRaisesRegex(RegistryConflict, "QUEUE_CONTRACT_MISMATCH"):
            RunnerRegistryControl(self.database).pre_claim(
                "TASK-201", "codex-a", task_contract=body
            )

    def test_review_outcome_is_bound_to_reviewer_attempt_and_evidence(self):
        now = datetime.now(timezone.utc) - timedelta(minutes=1)
        observed_at = now.isoformat()
        self.sync_workers(observed_at)
        feature, implementation, review = parse_canary_spec(self.canary())
        revision = self.registry.dispatch_control()["revision"]
        self.registry.register_canary_bundle(
            feature,
            implementation,
            review,
            expected_revision=revision,
            recorded_at=observed_at,
        )
        control = self.registry.dispatch_control()
        self.registry.set_dispatch_control(
            expected_revision=control["revision"],
            expected_mode="PAUSED",
            new_mode="LIVE",
            kill_switch_engaged=False,
            changed_at=(now + timedelta(seconds=1)).isoformat(),
            reason="fixture review lifecycle",
        )
        implementation_lease = self.registry.acquire_lease(
            "TASK-201",
            "codex-a",
            acquired_at=(now + timedelta(seconds=2)).isoformat(),
            expires_at=(now + timedelta(minutes=5)).isoformat(),
        )
        self.registry.begin_attempt_runtime(
            "implementation-attempt",
            package_id="TASK-201",
            worker_id="codex-a",
            runner_pid=os.getpid(),
            started_at=(now + timedelta(seconds=3)).isoformat(),
            expected_revision=self.registry.dispatch_control()["revision"],
        )
        self.registry.finish_attempt_runtime(
            "implementation-attempt",
            ended_at=(now + timedelta(seconds=4)).isoformat(),
            outcome="SUCCEEDED",
            next_status=TaskStatus.VERIFY_REVIEW,
            reason="implementation ready for review",
        )
        self.assertEqual(implementation_lease.package_id, "TASK-201")
        self.assertEqual(
            self.registry.review_implementer_worker("TASK-202"), "codex-a"
        )
        self.registry.acquire_lease(
            "TASK-202",
            "claude",
            acquired_at=(now + timedelta(seconds=5)).isoformat(),
            expires_at=(now + timedelta(minutes=5)).isoformat(),
        )
        self.registry.begin_attempt_runtime(
            "review-attempt",
            package_id="TASK-202",
            worker_id="claude",
            runner_pid=os.getpid(),
            started_at=(now + timedelta(seconds=6)).isoformat(),
            expected_revision=self.registry.dispatch_control()["revision"],
        )
        self.registry.finish_attempt_runtime(
            "review-attempt",
            ended_at=(now + timedelta(seconds=8)).isoformat(),
            outcome="SUCCEEDED",
            next_status=TaskStatus.VERIFY_REVIEW,
            reason="independent review completed",
        )
        self.registry.engage_dispatch_kill_switch(
            changed_at=(now + timedelta(seconds=9)).isoformat(),
            reason="record reviewed canary while paused",
        )
        RunnerRegistryControl(self.database).finalize_paused(reason="review ownership drained")
        self.state.chmod(0o700)
        self.worktrees.chmod(0o700)
        harden_paths(self.database, self.config_path, self.release)
        digest, input_id = self.record_review_input(
            "TASK-202", "review-attempt", (now + timedelta(seconds=5)).isoformat()
        )
        revision = self.registry.dispatch_control()["revision"]
        evidence = record_review_decision(
            self.database,
            self.config_path,
            self.release,
            self.preservation,
            COMMIT,
            revision,
            {
                "evidence": {
                    "id": "review-evidence",
                    "package_id": "TASK-202",
                    "kind": "review",
                    "uri": "https://example.invalid/review",
                    "summary": "Independent review approved the bounded canary.",
                    "recorded_at": (now + timedelta(seconds=7)).isoformat(),
                    "metadata": {
                        "attempt_id": "review-attempt", "reviewed_commit": COMMIT,
                        "reviewed_base_commit": "b" * 40, "contract_sha256": digest,
                        "review_input_evidence_id": input_id,
                    },
                },
                "outcome": {
                    "id": "review-outcome",
                    "review_package_id": "TASK-202",
                    "target_package_id": "TASK-201",
                    "implementer_worker_id": "codex-a",
                    "reviewer_worker_id": "claude",
                    "requested_at": (now + timedelta(seconds=5)).isoformat(),
                    "decided_at": (now + timedelta(seconds=9)).isoformat(),
                    "state": "APPROVED",
                    "findings": [],
                    "changes_requested": [],
                    "approval_evidence_ids": ["review-evidence"],
                    "reviewed_commit": COMMIT,
                    "reviewed_base_commit": "b" * 40,
                    "contract_sha256": digest,
                    "review_input_evidence_id": input_id,
                    "reviewer_attempt_id": "review-attempt",
                },
            },
        )
        self.assertEqual(evidence["reviewer_attempt_id"], "review-attempt")
        snapshot = self.registry.control_center_snapshot(observed_at=utc_now())
        self.assertEqual(snapshot.review_outcomes[0]["state"], "APPROVED")
        self.assertEqual(
            next(item for item in snapshot.evidence if item["id"] == "review-evidence")["metadata"]["attempt_id"],
            "review-attempt",
        )
        self.assertEqual(
            {
                item["id"]: item["status"] for item in snapshot.work_packages
                if item["feature_id"] == "A5-CANARY"
            },
            {"TASK-201": "DONE", "TASK-202": "DONE"},
        )
        self.assertEqual(
            next(item for item in snapshot.features if item["id"] == "A5-CANARY")["status"],
            "DONE",
        )

    def test_changes_requested_can_register_fresh_review_and_approval_finishes_feature(self):
        now = datetime.now(timezone.utc) - timedelta(minutes=5)
        observed_at = now.isoformat()
        self.sync_workers(observed_at)
        feature, implementation, review = parse_canary_spec(self.canary())
        self.registry.register_canary_bundle(
            feature,
            implementation,
            review,
            expected_revision=self.registry.dispatch_control()["revision"],
            recorded_at=observed_at,
        )
        control = self.registry.dispatch_control()
        self.registry.set_dispatch_control(
            expected_revision=control["revision"], expected_mode="PAUSED",
            new_mode="LIVE", kill_switch_engaged=False,
            changed_at=(now + timedelta(seconds=1)).isoformat(),
            reason="fixture lifecycle",
        )
        self.registry.acquire_lease(
            "TASK-201", "codex-a",
            acquired_at=(now + timedelta(seconds=2)).isoformat(),
            expires_at=(now + timedelta(minutes=1)).isoformat(),
        )
        self.registry.begin_attempt_runtime(
            "implementation-attempt", package_id="TASK-201", worker_id="codex-a",
            runner_pid=os.getpid(), started_at=(now + timedelta(seconds=3)).isoformat(),
            expected_revision=self.registry.dispatch_control()["revision"],
        )
        self.registry.finish_attempt_runtime(
            "implementation-attempt", ended_at=(now + timedelta(seconds=4)).isoformat(),
            outcome="SUCCEEDED", next_status=TaskStatus.VERIFY_REVIEW,
            reason="implementation ready for review",
        )
        self.registry.acquire_lease(
            "TASK-202", "claude",
            acquired_at=(now + timedelta(seconds=5)).isoformat(),
            expires_at=(now + timedelta(minutes=1)).isoformat(),
        )
        self.registry.begin_attempt_runtime(
            "review-attempt-1", package_id="TASK-202", worker_id="claude",
            runner_pid=os.getpid(), started_at=(now + timedelta(seconds=6)).isoformat(),
            expected_revision=self.registry.dispatch_control()["revision"],
        )
        self.registry.finish_attempt_runtime(
            "review-attempt-1", ended_at=(now + timedelta(seconds=8)).isoformat(),
            outcome="SUCCEEDED", next_status=TaskStatus.VERIFY_REVIEW,
            reason="first review completed",
        )
        self.registry.engage_dispatch_kill_switch(
            changed_at=(now + timedelta(seconds=9)).isoformat(), reason="review decision",
        )
        RunnerRegistryControl(self.database).finalize_paused(reason="ownership drained")
        followup = parse_followup_review_spec(self.followup_review())
        with self.assertRaisesRegex(
            RegistryConflict, "CHANGES_REQUESTED_REVIEW_REQUIRED"
        ):
            self.registry.register_followup_review(
                followup,
                expected_revision=self.registry.dispatch_control()["revision"],
                recorded_at=(now + timedelta(seconds=10)).isoformat(),
            )
        digest_1, input_id_1 = self.record_review_input(
            "TASK-202", "review-attempt-1", (now + timedelta(seconds=5)).isoformat()
        )
        self.registry.record_review_outcome(
            ReviewOutcome(
                id="review-outcome-1", review_package_id="TASK-202",
                target_package_id="TASK-201", implementer_worker_id="codex-a",
                reviewer_worker_id="claude",
                requested_at=(now + timedelta(seconds=5)).isoformat(),
                decided_at=(now + timedelta(seconds=9)).isoformat(),
                state=ReviewOutcomeState.CHANGES_REQUESTED,
                reviewed_commit=COMMIT, reviewed_base_commit="b" * 40,
                contract_sha256=digest_1, review_input_evidence_id=input_id_1,
                reviewer_attempt_id="review-attempt-1",
                findings=("Review targeted the wrong pull request.",),
                changes_requested=("Run a fresh review against the bound canary commit.",),
            ),
            evidence=Evidence(
                "review-evidence-1", "TASK-202", "review",
                "https://example.invalid/review-1", "Wrong target recorded safely.",
                (now + timedelta(seconds=8)).isoformat(),
                {"attempt_id": "review-attempt-1", "reviewed_commit": COMMIT,
                 "reviewed_base_commit": "b" * 40, "contract_sha256": digest_1,
                 "review_input_evidence_id": input_id_1},
            ),
            expected_revision=self.registry.dispatch_control()["revision"],
        )

        gate = followup_review_worker_gate(
            self.registry.dispatch_snapshot(
                observed_at=(now + timedelta(seconds=10)).isoformat()
            ),
            followup,
            implementer_worker_id=self.registry.successful_package_worker("TASK-201"),
            observed_at=(now + timedelta(seconds=10)).isoformat(),
        )
        self.assertEqual(gate["independent_pairs"], [["codex-a", "claude"]])
        self.registry.register_followup_review(
            followup,
            expected_revision=self.registry.dispatch_control()["revision"],
            recorded_at=(now + timedelta(seconds=10)).isoformat(),
        )
        snapshot = self.registry.dispatch_snapshot(
            observed_at=(now + timedelta(seconds=10)).isoformat()
        )
        registered = next(item for item in snapshot.work_packages if item["id"] == "TASK-203")
        self.assertEqual(registered["source_system"], "github_issue")
        self.assertEqual(registered["source_ref"], "312")
        control = self.registry.dispatch_control()
        self.registry.set_dispatch_control(
            expected_revision=control["revision"], expected_mode="PAUSED",
            new_mode="LIVE", kill_switch_engaged=False,
            changed_at=(now + timedelta(seconds=11)).isoformat(),
            reason="fresh independent review",
        )
        self.registry.acquire_lease(
            "TASK-203", "claude",
            acquired_at=(now + timedelta(seconds=12)).isoformat(),
            expires_at=(now + timedelta(minutes=2)).isoformat(),
        )
        self.registry.begin_attempt_runtime(
            "review-attempt-2", package_id="TASK-203", worker_id="claude",
            runner_pid=os.getpid(), started_at=(now + timedelta(seconds=13)).isoformat(),
            expected_revision=self.registry.dispatch_control()["revision"],
        )
        self.registry.finish_attempt_runtime(
            "review-attempt-2", ended_at=(now + timedelta(seconds=15)).isoformat(),
            outcome="SUCCEEDED", next_status=TaskStatus.VERIFY_REVIEW,
            reason="fresh review completed",
        )
        self.registry.engage_dispatch_kill_switch(
            changed_at=(now + timedelta(seconds=16)).isoformat(), reason="approval decision",
        )
        RunnerRegistryControl(self.database).finalize_paused(reason="ownership drained")
        digest_2, input_id_2 = self.record_review_input(
            "TASK-203", "review-attempt-2", (now + timedelta(seconds=12)).isoformat()
        )
        self.registry.record_review_outcome(
            ReviewOutcome(
                id="review-outcome-2", review_package_id="TASK-203",
                target_package_id="TASK-201", implementer_worker_id="codex-a",
                reviewer_worker_id="claude",
                requested_at=(now + timedelta(seconds=12)).isoformat(),
                decided_at=(now + timedelta(seconds=16)).isoformat(),
                state=ReviewOutcomeState.APPROVED,
                reviewed_commit=COMMIT, reviewed_base_commit="b" * 40,
                contract_sha256=digest_2, review_input_evidence_id=input_id_2,
                reviewer_attempt_id="review-attempt-2",
                findings=("Bound canary commit passes review.",),
                approval_evidence_ids=("review-evidence-2",),
            ),
            evidence=Evidence(
                "review-evidence-2", "TASK-203", "review",
                "https://example.invalid/review-2", "Fresh bound approval.",
                (now + timedelta(seconds=15)).isoformat(),
                {"attempt_id": "review-attempt-2", "reviewed_commit": COMMIT,
                 "reviewed_base_commit": "b" * 40, "contract_sha256": digest_2,
                 "review_input_evidence_id": input_id_2},
            ),
            expected_revision=self.registry.dispatch_control()["revision"],
        )
        snapshot = self.registry.control_center_snapshot(observed_at=utc_now())
        self.assertEqual(
            {
                item["id"]: item["status"] for item in snapshot.work_packages
                if item["feature_id"] == "A5-CANARY"
            },
            {"TASK-201": "DONE", "TASK-202": "DONE", "TASK-203": "DONE"},
        )
        self.assertEqual(
            next(item for item in snapshot.features if item["id"] == "A5-CANARY")["status"],
            "DONE",
        )

    def test_requeue_preserves_failed_attempt_and_requires_current_revision(self):
        now = utc_now()
        self.sync_workers(now)
        feature, implementation, review = parse_canary_spec(self.canary())
        revision = self.registry.dispatch_control()["revision"]
        self.registry.register_canary_bundle(
            feature, implementation, review,
            expected_revision=revision, recorded_at=now,
        )
        control = self.registry.dispatch_control()
        live_revision = self.registry.set_dispatch_control(
            expected_revision=control["revision"], expected_mode="PAUSED",
            new_mode="LIVE", kill_switch_engaged=False, changed_at=utc_now(),
            reason="test failure canary",
        )
        acquired = datetime.now(timezone.utc)
        lease = self.registry.acquire_lease(
            "TASK-201", "codex-a", acquired_at=acquired.isoformat(),
            expires_at=(acquired + timedelta(minutes=10)).isoformat(),
            expected_dispatch_revision=live_revision,
        )
        self.registry.begin_attempt_runtime(
            "attempt-failed", package_id="TASK-201", worker_id="codex-a",
            runner_pid=os.getpid(), started_at=(acquired + timedelta(seconds=1)).isoformat(),
            expected_revision=self.registry.dispatch_control()["revision"],
        )
        self.registry.finish_attempt_runtime(
            "attempt-failed", ended_at=(acquired + timedelta(seconds=2)).isoformat(),
            outcome="FAILED", next_status=TaskStatus.BLOCKED,
            reason="deterministic canary failure", failure_detail="expected fixture failure",
        )
        self.registry.engage_dispatch_kill_switch(
            changed_at=(acquired + timedelta(seconds=3)).isoformat(), reason="test stop"
        )
        RunnerRegistryControl(self.database).finalize_paused(reason="test drained")
        before = self.registry.control_center_snapshot(observed_at=utc_now())
        revision = self.registry.dispatch_control()["revision"]
        with self.assertRaisesRegex(RegistryConflict, "REGISTRY_REVISION_CHANGED"):
            self.registry.requeue_failed_package(
                "TASK-201", expected_revision=revision - 1,
                changed_at=utc_now(), reason="stale retry",
            )
        self.registry.requeue_failed_package(
            "TASK-201", expected_revision=revision,
            changed_at=utc_now(), reason="reviewed retry",
        )
        after = self.registry.control_center_snapshot(observed_at=utc_now())
        self.assertEqual(before.attempts, after.attempts)
        package = next(value for value in after.work_packages if value["id"] == "TASK-201")
        self.assertEqual(package["status"], "READY")
        self.assertEqual(lease.id, before.attempts[-1]["lease_id"])

    def test_prepare_dry_run_migrates_atomically_and_hardens_paths(self):
        self.config_path.write_text(json.dumps(self.config(strict=False)))
        control = self.registry.dispatch_control()
        revision = self.registry.set_dispatch_control(
            expected_revision=control["revision"],
            expected_mode="PAUSED",
            new_mode="LIVE",
            kill_switch_engaged=False,
            changed_at=utc_now(),
            reason="fixture starts live",
        )
        calls = []

        def launchctl(arguments, **kwargs):
            calls.append(arguments)
            if arguments[1] == "print":
                return subprocess.CompletedProcess(arguments, 1)
            return subprocess.CompletedProcess(arguments, 0)

        evidence = prepare_dry_run(
            self.database, self.config_path, self.release, self.preservation,
            COMMIT, revision, self.migration(), home=self.root / "home",
            run=launchctl, uid=501,
        )
        self.assertTrue(evidence["passed"])
        config = json.loads(self.config_path.read_text())
        self.assertEqual(config["registry_database"], str(self.database))
        self.assertEqual(config["usage_policy"]["hard_stop_percent"], 98)
        self.assertEqual(set(config["agents"]), {"codex-a", "codex-b", "claude"})
        self.assertTrue(all(value["slots"] == 1 for value in config["agents"].values()))
        self.assertEqual(
            config["gh"], str(self.release.resolve() / "scripts" / "runner" / "github.py")
        )
        self.assertEqual(
            config["agents"]["claude"]["command"][1],
            str(self.release.resolve() / "scripts" / "runner" / "claude_keychain.py"),
        )
        self.assertEqual(stat.S_IMODE(self.database.parent.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(self.database.stat().st_mode), 0o600)
        self.assertFalse(any(path.stat().st_mode & 0o222 for path in self.release.rglob("*")))
        for label in evidence["services"]:
            plist = self.root / "home" / "Library" / "LaunchAgents" / f"{label}.plist"
            data = plistlib.loads(plist.read_bytes())
            if "runner" in label:
                self.assertIn("--dry-run", data["ProgramArguments"])
        self.assertTrue(any(call[1] == "bootstrap" for call in calls))

    def test_enable_live_promotes_loaded_dry_run_then_cas_enables_canary(self):
        self.config_path.write_text(json.dumps(self.config(strict=False)))
        loaded = set()

        def launchctl(arguments, **kwargs):
            operation = arguments[1]
            if operation == "print":
                label = arguments[-1].rsplit("/", 1)[-1]
                return subprocess.CompletedProcess(arguments, 0 if label in loaded else 1)
            if operation == "bootout":
                loaded.discard(arguments[-1].rsplit("/", 1)[-1])
                return subprocess.CompletedProcess(arguments, 0)
            if operation == "bootstrap":
                loaded.add(Path(arguments[-1]).stem)
                return subprocess.CompletedProcess(arguments, 0)
            raise AssertionError(arguments)

        revision = self.registry.dispatch_control()["revision"]
        prepare_dry_run(
            self.database, self.config_path, self.release, self.preservation,
            COMMIT, revision, self.migration(), home=self.root / "home",
            run=launchctl, uid=501,
        )
        now = utc_now()
        self.sync_workers(now)
        feature, implementation, review = parse_canary_spec(self.canary())
        revision = self.registry.dispatch_control()["revision"]
        self.registry.register_canary_bundle(
            feature, implementation, review,
            expected_revision=revision, recorded_at=now,
        )
        revision = self.registry.dispatch_control()["revision"]
        evidence = enable_live(
            self.database, self.config_path, self.release, self.preservation,
            COMMIT, revision, "A5-CANARY", home=self.root / "home",
            run=launchctl, uid=501,
        )
        self.assertTrue(evidence["passed"])
        self.assertEqual(self.registry.dispatch_control()["dispatch_mode"], "LIVE")
        for label in evidence["services"]:
            plist = self.root / "home" / "Library" / "LaunchAgents" / f"{label}.plist"
            data = plistlib.loads(plist.read_bytes())
            if "runner" in label:
                self.assertNotIn("--dry-run", data["ProgramArguments"])

    def test_stale_or_secret_telemetry_fails_before_registry_write(self):
        payload = self.telemetry("codex-a", now="2026-09-25T08:00:00Z")
        with self.assertRaisesRegex(OperatorError, "stale"):
            validate_telemetry_payload(payload, "2026-09-25T08:20:00Z")
        payload = self.telemetry("codex-a", now="2026-09-25T08:00:00Z")
        payload["worker"]["provider_diagnostics"]["access_token"] = "do-not-store"
        with self.assertRaisesRegex(OperatorError, "secret-shaped"):
            validate_telemetry_payload(payload, "2026-09-25T08:00:01Z")

    def test_bounded_enable_supports_two_pairs_without_rewriting_historical_ready(self):
        self.config_path.write_text(json.dumps(self.config(strict=False)))
        loaded = set()
        def launchctl(arguments, **kwargs):
            operation = arguments[1]
            label = arguments[-1].rsplit('/', 1)[-1]
            if operation == 'print':
                return subprocess.CompletedProcess(arguments, 0 if label in loaded else 1)
            if operation == 'bootout':
                loaded.discard(label)
            elif operation == 'bootstrap':
                loaded.add(Path(arguments[-1]).stem)
            else:
                raise AssertionError(arguments)
            return subprocess.CompletedProcess(arguments, 0)
        prepare_dry_run(self.database, self.config_path, self.release, self.preservation,
            COMMIT, self.registry.dispatch_control()['revision'], self.migration(),
            home=self.root / 'home', run=launchctl, uid=501)
        now = utc_now()
        self.sync_workers(now)
        worker, usage = validate_telemetry_payload(self.telemetry('codex-b', now=now), now)
        self.registry.sync_worker_telemetry(worker, usage,
            expected_revision=self.registry.dispatch_control()['revision'], recorded_at=now)
        specs = []
        for number in (201, 301):
            spec = self.canary()
            spec['feature']['id'] = 'PILOT-' + str(number)
            for key, identifier in (('implementation', number), ('review', number + 1)):
                package = spec[key]
                package.update(id='TASK-' + str(identifier), feature_id=spec['feature']['id'], source_ref=str(identifier))
                package['queue_contract']['task'] = package['id']
                if key == 'review':
                    package['dependency_ids'] = ['TASK-' + str(number)]
                    package['queue_contract']['depends_on'] = [number]
            specs.append(spec)
        pairs = operator_module.parse_bounded_pilot_spec({'pairs': specs})
        self.registry.register_feature(Feature('HISTORICAL', 'Preserved backlog', 999, TaskStatus.READY))
        self.registry.register_work_package(WorkPackage('TASK-999', 'HISTORICAL', 'Unrelated',
            'test', Lane.PLATFORM, ('documentation',), 999, ('preserve',), status=TaskStatus.READY))
        self.registry.register_bounded_pilot(pairs,
            expected_revision=self.registry.dispatch_control()['revision'], recorded_at=now)
        scope = {'run_id': 'two-parent-pilot', 'package_ids': ['TASK-201', 'TASK-202', 'TASK-301', 'TASK-302'],
            'deadline': '2099-01-01T00:00:00Z', 'base_ref': 'main', 'parent_limit': 2}
        evidence = enable_live(self.database, self.config_path, self.release, self.preservation,
            COMMIT, self.registry.dispatch_control()['revision'], 'two-parent-pilot',
            home=self.root / 'home', run=launchctl, uid=501, bounded_run=scope)
        self.assertTrue(evidence['passed'])
        self.assertEqual(self.registry.dispatch_control()['bounded_run']['run_id'], scope['run_id'])
        from scripts.runner.registry_control import RunnerRegistryControl
        controller = RunnerRegistryControl(self.database)
        self.assertIsNone(controller.proposed_worker('TASK-999'))
        self.assertIsNotNone(controller.proposed_worker('TASK-201'))
        self.assertIsNotNone(controller.proposed_worker('TASK-301'))
        historical = next(p for p in self.registry.dispatch_snapshot(observed_at=now).work_packages if p['id'] == 'TASK-999')
        self.assertEqual(historical['status'], 'READY')

    def test_bounded_run_worker_gate_keeps_normal_ready_pair_path(self):
        now = utc_now()
        self.sync_workers(now)
        feature, implementation, review = parse_canary_spec(self.canary())
        self.registry.register_canary_bundle(
            feature, implementation, review,
            expected_revision=self.registry.dispatch_control()["revision"], recorded_at=now,
        )
        evidence = operator_module.bounded_run_worker_gate(
            self.registry.dispatch_snapshot(observed_at=now), ["TASK-201", "TASK-202"],
        )
        self.assertEqual(evidence["run_package_ids"], ["TASK-201", "TASK-202"])
        self.assertIn(["TASK-201", "codex-a", "claude"], evidence["independent_pairs"])

    def test_bounded_run_gate_accepts_a_capable_pair_waiting_on_a_blocked_parent(self):
        now = utc_now()
        self.sync_workers(now)
        feature, implementation, review = parse_canary_spec(self.canary())
        self.registry.register_canary_bundle(
            feature, implementation, review,
            expected_revision=self.registry.dispatch_control()["revision"], recorded_at=now,
        )
        self.registry.transition_work_package(
            implementation.id, expected_status=TaskStatus.READY,
            new_status=TaskStatus.BLOCKED, changed_at=now,
        )

        evidence = operator_module.bounded_run_worker_gate(
            self.registry.dispatch_snapshot(observed_at=now), [implementation.id, review.id],
        )

        self.assertEqual(evidence["implementation_assignments"][implementation.id], [])
        self.assertIn("codex-a", evidence["potential_implementation_assignments"][implementation.id])

    def test_bounded_pilot_parser_accepts_a_backlog_larger_than_wip(self):
        pairs = []
        for number in (401, 411, 421):
            spec = self.canary()
            spec["feature"]["id"] = f"BACKLOG-{number}"
            for key, identifier in (("implementation", number), ("review", number + 1)):
                package = spec[key]
                package.update(id=f"TASK-{identifier}", feature_id=spec["feature"]["id"],
                               source_ref=str(identifier))
                package["queue_contract"]["task"] = package["id"]
                if key == "review":
                    package["dependency_ids"] = [f"TASK-{number}"]
                    package["queue_contract"]["depends_on"] = [number]
            pairs.append(spec)
        self.assertEqual(len(operator_module.parse_bounded_pilot_spec({"pairs": pairs})), 3)

    def test_bounded_review_preflight_accepts_immutable_target_scoped_followup(self):
        now, _spec = self._bounded_review_fixture()
        observed_at = (now + timedelta(seconds=7)).isoformat()
        evidence = preflight(
            self.database, self.config_path, self.release, self.preservation, COMMIT,
            self.registry.dispatch_control()["revision"], observed_at=observed_at,
            require_permissions_gate=False, require_workers=True, run_package_ids=["TASK-202"],
        )
        self.assertEqual(evidence["worker_gate"]["independent_pairs"], [["TASK-202", "codex-a", "claude"]])
        followup = parse_followup_review_spec(self.followup_review())
        followup_gate = followup_review_worker_gate(
            self.registry.dispatch_snapshot(observed_at=observed_at), followup,
            implementer_worker_id=self.registry.successful_package_worker("TASK-201"),
            observed_at=observed_at,
        )
        self.assertEqual(followup_gate["independent_pairs"], [["codex-a", "claude"]])

    def test_followup_review_source_requires_a_positive_consistent_github_issue(self):
        cases = (
            ("missing", lambda spec: spec["review"].pop("source_ref")),
            ("zero", lambda spec: spec["review"].update(source_ref=0)),
            ("non-numeric", lambda spec: spec["review"].update(source_ref="issue-312")),
            ("inconsistent", lambda spec: spec["review"].update(
                provider_diagnostics={"github_source_ref": "313"}
            )),
        )
        for name, mutate in cases:
            with self.subTest(name=name):
                spec = self.followup_review()
                mutate(spec)
                with self.assertRaisesRegex(OperatorError, "source_ref|invalid"):
                    parse_followup_review_spec(spec)

        invalid = WorkPackage(
            "TASK-351", "A5-CANARY", "invalid source", "ASSURANCE", Lane.ASSURANCE,
            ("independent-review",), 1, ("review",), status=TaskStatus.READY,
            kind=PackageKind.REVIEW, dependency_ids=("TASK-201",),
            provider_diagnostics={"github_source_ref": "0"},
        )
        with self.assertRaisesRegex(RegistryConflict, "INVALID_FOLLOWUP_REVIEW"):
            self.registry.register_followup_review(
                invalid, expected_revision=self.registry.dispatch_control()["revision"],
                recorded_at=utc_now(),
            )

    def test_bounded_review_gate_rejects_each_isolated_target_and_provenance_failure(self):
        cases = (
            ("ready-target", "UPDATE work_packages SET status='READY' WHERE id='TASK-201'", "VERIFY_REVIEW parent"),
            ("active-target", "UPDATE work_packages SET status='ACTIVE' WHERE id='TASK-201'", "VERIFY_REVIEW parent"),
            ("non-parent-target", "UPDATE work_packages SET kind='REVIEW' WHERE id='TASK-201'", "VERIFY_REVIEW parent"),
            ("wrong-target", "UPDATE task_dependencies SET dependency_id='LEGACY-PARENT-1' WHERE package_id='TASK-202'", "does not bind its target"),
            ("missing-input", "DELETE FROM evidence WHERE package_id='TASK-202' AND kind='review-input'", "provenance gate failed: REVIEW_INPUT_REQUIRED"),
            ("self-review-provenance", "UPDATE attempts SET worker_id='claude' WHERE id='implementation-attempt'", "no independent reviewer"),
            ("zero-dependencies", "DELETE FROM task_dependencies WHERE package_id='TASK-202'", "exactly one dependency row"),
        )
        for index, (name, statement, message) in enumerate(cases):
            with self.subTest(name=name):
                if index:
                    self.tearDown()
                    self.setUp()
                now, _spec = self._bounded_review_fixture()
                with self.registry._connection() as connection:
                    connection.execute(statement)
                with self.assertRaisesRegex(OperatorError, message):
                    operator_module.bounded_run_worker_gate(
                        self.registry.dispatch_snapshot(observed_at=(now + timedelta(seconds=7)).isoformat()),
                        ["TASK-202"], review_input_lookup=self.registry.review_input,
                        successful_attempt_worker=self.registry.successful_attempt_worker,
                    )

    def test_bounded_review_gate_rejects_multiple_dependencies_and_stale_capacity(self):
        now, _spec = self._bounded_review_fixture()
        with self.registry._connection() as connection:
            connection.execute(
                "INSERT INTO task_dependencies(package_id, dependency_id) VALUES ('TASK-202', 'LEGACY-PARENT-1')"
            )
        with self.assertRaisesRegex(OperatorError, "exactly one dependency row"):
            operator_module.bounded_run_worker_gate(
                self.registry.dispatch_snapshot(observed_at=(now + timedelta(seconds=7)).isoformat()),
                ["TASK-202"], review_input_lookup=self.registry.review_input,
                successful_attempt_worker=self.registry.successful_attempt_worker,
            )
        self.tearDown()
        self.setUp()
        now, _spec = self._bounded_review_fixture()
        with self.assertRaisesRegex(OperatorError, "global worker/capacity gate failed"):
            operator_module.bounded_run_worker_gate(
                self.registry.dispatch_snapshot(observed_at=(now + timedelta(hours=2)).isoformat()),
                ["TASK-202"], review_input_lookup=self.registry.review_input,
                successful_attempt_worker=self.registry.successful_attempt_worker,
            )

    def test_record_review_input_cli_publishes_valid_packet_and_refuses_tampering(self):
        now, spec = self._bounded_review_fixture(publish_input=False)
        # The CLI's preflight deliberately rejects default-umask storage.  Make
        # this disposable fixture match the real private-storage contract for
        # both the tampered and restored-packet branches; do not bypass it.
        self.database.parent.chmod(0o700)
        self.database.chmod(0o600)
        for path in (Path(f"{self.database}-wal"), Path(f"{self.database}-shm")):
            if path.exists():
                path.chmod(0o600)
        self.config_path.chmod(0o600)
        self.state.chmod(0o700)
        self.worktrees.chmod(0o700)
        for path in sorted((self.release, *self.release.rglob("*")), key=lambda value: len(value.parts), reverse=True):
            path.chmod(0o500 if path.is_dir() else 0o400)
        spec_path = self.root / "review-input.json"
        spec_path.write_text(json.dumps(spec))
        packet_contract = Path(spec["validation_evidence"]["review_packet"]["path"]) / "contract.json"
        original_contract = packet_contract.read_bytes()
        packet_contract.write_text('{"task":"tampered"}')
        argv = [
            "record-review-input", "--database", str(self.database), "--config", str(self.config_path),
            "--release", str(self.release), "--release-commit", COMMIT,
            "--preservation", str(self.preservation), "--expect-revision",
            str(self.registry.dispatch_control()["revision"]), "--spec", str(spec_path),
        ]
        output, errors = StringIO(), StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            self.assertEqual(operator_main(argv), 1)
        self.assertIn("REVIEW_PACKET_FILE_MISMATCH", errors.getvalue())
        with self.assertRaisesRegex(RegistryConflict, "REVIEW_INPUT_REQUIRED"):
            self.registry.review_input("TASK-202")
        packet_contract.write_bytes(original_contract)
        output, errors = StringIO(), StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            self.assertEqual(operator_main(argv), 0)
        published = json.loads(output.getvalue())
        self.assertTrue(published["passed"])
        self.assertEqual(self.registry.review_input("TASK-202")["target_package_id"], "TASK-201")


if __name__ == "__main__":
    unittest.main()
