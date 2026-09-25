import hashlib
import json
import os
import plistlib
import shutil
import stat
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path

from scripts.factory_registry.models import Lane, TaskStatus
from scripts.factory_registry.operator import (
    OperatorError,
    canary_worker_gate,
    enable_live,
    harden_paths,
    parse_canary_spec,
    preflight,
    prepare_dry_run,
    utc_now,
    validate_telemetry_payload,
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
        self.preservation = self.root / "preservation.json"
        snapshot = {
            "snapshot_version": 1,
            "canonical_repository": {
                "origin_main": "abc",
                "path": "/preserved/canonical",
            },
            "services": {"heartbeats": {"codex-a": {"time": 1000, "status": "idle"}}},
            "open_task_mapping": [],
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
        digest = hashlib.sha256(self.preservation.read_bytes()).hexdigest()
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
        self.temporary.cleanup()

    def _release(self):
        source_root = Path(__file__).resolve().parents[2]
        files = (
            "scripts/runner/runner.py",
            "scripts/runner/install_launchd.py",
            "scripts/runner/factory_dashboard.py",
            "scripts/factory_registry/sqlite_registry.py",
            "scripts/factory_registry/operator.py",
            "scripts/factory_registry/operator_cli.py",
        )
        manifest = []
        for relative in files:
            source = source_root / relative
            destination = self.release / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            manifest.append(f"{hashlib.sha1(destination.read_bytes()).hexdigest()}  {relative}")
        (self.release / "COMMIT").write_text(COMMIT + "\n")
        (self.release / "MANIFEST.sha1").write_text("\n".join(manifest) + "\n")

    def config(self, *, strict):
        value = {
            "repo": str(self.root / "repo"),
            "github": "owner/repo",
            "state": str(self.state),
            "worktrees": str(self.worktrees),
            "path": "/usr/bin:/bin",
            "gh": "/usr/bin/true",
            "git": "/usr/bin/git",
            "pnpm": "/usr/bin/true",
            "allowed_authors": ["owner"],
            "agent_timeout": 1800,
            "agents": {
                "codex-a": {
                    "provider": "openai", "account": "a", "slots": 1,
                    "model": "model",
                    "command": ["/usr/bin/true", "--disable", "multi_agent"],
                    "env": {},
                },
                "codex-b": {
                    "provider": "openai", "account": "b", "slots": 1,
                    "model": "model",
                    "command": ["/usr/bin/true", "--disable", "multi_agent"],
                    "env": {},
                },
                "claude": {
                    "provider": "anthropic", "account": "c", "slots": 1,
                    "model": "model",
                    "command": ["/usr/bin/true", "--tools", "Read,Edit,Write,Glob,Grep"],
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


if __name__ == "__main__":
    unittest.main()
