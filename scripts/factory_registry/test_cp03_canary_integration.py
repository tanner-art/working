"""Cross-module canary for the CP-03 v2 registration-to-child handoff."""

import json
import pathlib
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import Mock


ROOT = pathlib.Path(__file__).resolve().parents[2]
RUNNER = ROOT / "scripts" / "runner"
if str(RUNNER) not in sys.path:
    sys.path.insert(0, str(RUNNER))

from scripts.factory_registry import (  # noqa: E402
    Feature,
    Lane,
    PackageCapacityRisk,
    PackageCapacitySize,
    PackageKind,
    RegistryConflict,
    SQLiteRegistry,
    TaskStatus,
    Worker,
    WorkPackage,
)
from scripts.factory_registry.operator import prepare_ready_package  # noqa: E402
from scripts.runner.registry_control import RunnerRegistryControl, queue_contract_digest  # noqa: E402
from scripts.runner.runner import build_agent_prompt, verified_readiness_handoff  # noqa: E402


class CP03CanaryIntegrationTests(unittest.TestCase):
    """Exercise the installed registration proof across Registry and runner seams."""

    def test_registered_v2_proof_reaches_child_handoff_and_rejects_drift(self):
        fixture = self._fixture()
        try:
            revision = fixture["control"].pre_claim(
                "TASK-419", "codex-a", task_contract=fixture["contract"], github_issue=419,
            )
            handoff, handoff_revision = verified_readiness_handoff(
                fixture["control"], fixture["contract"], fixture["base"],
            )
            prompt = build_agent_prompt(419, fixture["contract"], worker="codex-a",
                                      readiness_handoff=handoff)
            proof = fixture["proof"]
            self.assertEqual(handoff_revision, revision)
            for value in (
                f"Registry revision: {revision}", fixture["base"], "Target ref: main",
                proof["queue_contract_sha256"], proof["acceptance_sha256"],
                proof["planning_sha256"]["docs/PLAN.md"],
            ):
                self.assertIn(value, prompt)
            self._assert_no_active_ownership(fixture["registry"])

            # A stored planning digest that no longer represents the immutable
            # base blob must stop at preclaim, before any provider invocation.
            self._replace_stored_planning_hash(fixture, "0" * 64)
            history = self._historical_evidence_counts(fixture["registry"])
            provider_launch = Mock()
            with self.assertRaisesRegex(
                RegistryConflict, "DISPATCH_PAIR_INELIGIBLE.*REGISTRATION_PROOF_CHANGED",
            ):
                fixture["control"].pre_claim(
                    "TASK-419", "codex-a", task_contract=fixture["contract"], github_issue=419,
                )
            provider_launch.assert_not_called()
            self._assert_no_active_ownership(fixture["registry"])
            self.assertEqual(self._historical_evidence_counts(fixture["registry"]), history)
        finally:
            fixture["temporary"].cleanup()

        # Moving main after registration invalidates the exact base identity.
        fixture = self._fixture()
        try:
            (fixture["repository"] / "later.md").write_text("main moved\n")
            self._git(fixture["repository"], "add", "later.md")
            self._git(fixture["repository"], "-c", "user.name=Canary", "-c",
                      "user.email=canary@example.invalid", "commit", "-qm", "move main")
            history = self._historical_evidence_counts(fixture["registry"])
            provider_launch = Mock()
            with self.assertRaisesRegex(
                RegistryConflict, "DISPATCH_PAIR_INELIGIBLE.*BASE_REF_CHANGED",
            ):
                fixture["control"].pre_claim(
                    "TASK-419", "codex-a", task_contract=fixture["contract"], github_issue=419,
                )
            provider_launch.assert_not_called()
            self._assert_no_active_ownership(fixture["registry"])
            self.assertEqual(self._historical_evidence_counts(fixture["registry"]), history)
        finally:
            fixture["temporary"].cleanup()

        # Both provenance and contract substitutions are rejected before launch.
        fixture = self._fixture()
        try:
            history = self._historical_evidence_counts(fixture["registry"])
            provider_launch = Mock()
            with self.assertRaisesRegex(
                RegistryConflict, "DISPATCH_PAIR_INELIGIBLE.*SOURCE_BINDING_MISMATCH",
            ):
                fixture["control"].pre_claim(
                    "TASK-419", "codex-a", task_contract=fixture["contract"], github_issue=420,
                )
            changed_contract = {**fixture["contract"], "instructions": "Different scope"}
            with self.assertRaisesRegex(RegistryConflict, "QUEUE_CONTRACT_MISMATCH"):
                fixture["control"].pre_claim(
                    "TASK-419", "codex-a", task_contract=changed_contract, github_issue=419,
                )
            provider_launch.assert_not_called()
            self._assert_no_active_ownership(fixture["registry"])
            self.assertEqual(self._historical_evidence_counts(fixture["registry"]), history)
        finally:
            fixture["temporary"].cleanup()

    def _fixture(self):
        temporary = tempfile.TemporaryDirectory()
        repository = pathlib.Path(temporary.name) / "repository"
        repository.mkdir()
        self._git(repository, "init", "-q")
        (repository / "docs").mkdir()
        (repository / "docs/PLAN.md").write_text("CP-03 immutable plan\n")
        (repository / "scripts").mkdir()
        (repository / "scripts/canary.py").write_text("# canary\n")
        self._git(repository, "add", ".")
        self._git(repository, "-c", "user.name=Canary", "-c",
                  "user.email=canary@example.invalid", "commit", "-qm", "base")
        self._git(repository, "branch", "-M", "main")
        base = subprocess.check_output(
            ["git", "-C", str(repository), "rev-parse", "HEAD"], text=True,
        ).strip()
        contract = {
            "schema_version": 2,
            "task": "TASK-419",
            "instructions": "Validate only the CP-03 Registry handoff.",
            "paths": ["scripts/canary.py"],
            "depends_on": [],
            "readiness": {
                "base_commit": base,
                "planning_paths": ["docs/PLAN.md"],
                "existing_paths": ["scripts/canary.py"],
                "new_paths": [],
                "integration_paths": ["scripts/canary.py"],
                "test_paths": ["scripts/canary.py"],
                "dependency_kinds": {},
            },
        }
        implementation = WorkPackage(
            "TASK-419", "CP-03-CANARY", "CP-03 registration canary", "OPERATIONS",
            Lane.PLATFORM, ("cp03-canary",), 100,
            ("The v2 proof reaches the implementation child prompt.",),
            status=TaskStatus.READY, kind=PackageKind.PARENT,
            capacity_size=PackageCapacitySize.VERY_SMALL,
            capacity_risk=PackageCapacityRisk.BOUNDED,
            provider_diagnostics={
                "readiness_schema_version": 2,
                "queue_contract_sha256": queue_contract_digest(contract),
                "github_source_ref": "419",
            },
        )
        implementation = prepare_ready_package(
            implementation, contract, repository=repository, target_ref="main",
        )
        review = WorkPackage(
            "TASK-420", "CP-03-CANARY", "CP-03 paired review", "ASSURANCE",
            Lane.ASSURANCE, ("independent-review",), 99, ("Independent review is paired.",),
            status=TaskStatus.READY, kind=PackageKind.REVIEW,
            capacity_size=PackageCapacitySize.VERY_SMALL,
            capacity_risk=PackageCapacityRisk.BOUNDED, dependency_ids=("TASK-419",),
            provider_diagnostics={"github_source_ref": "420"},
        )
        registry = SQLiteRegistry(pathlib.Path(temporary.name) / "registry.sqlite3")
        registry.initialize()
        now = datetime.now(timezone.utc).isoformat()
        self._register_dispatchable_workers(registry, now)
        registry.register_bounded_pilot(
            [(Feature("CP-03-CANARY", "CP-03 canary", 100), implementation, review)],
            expected_revision=registry.dispatch_control()["revision"], recorded_at=now,
        )
        registry.set_dispatch_control(
            expected_revision=registry.dispatch_control()["revision"], expected_mode="PAUSED",
            new_mode="LIVE", kill_switch_engaged=False, changed_at=now,
            reason="disposable CP-03 canary",
        )
        return {
            "temporary": temporary, "repository": repository, "registry": registry,
            "control": RunnerRegistryControl(registry.database, repository),
            "base": base, "contract": contract,
            "proof": implementation.provider_diagnostics["readiness_proof"],
        }

    def _register_dispatchable_workers(self, registry, now):
        for worker in (
            Worker("codex-a", "Codex A", ("cp03-canary",), (Lane.PLATFORM,),
                   provider_diagnostics={"capacity_mode": "percentage", "capacity_scopes": ["codex-a"]},
                   last_heartbeat_at=now, usage_state="NORMAL"),
            Worker("orchestra", "Orchestra", (), (), role="ORCHESTRA",
                   provider_diagnostics={"capacity_mode": "percentage", "capacity_scopes": ["orchestra"]},
                   last_heartbeat_at=now, usage_state="NORMAL"),
        ):
            registry.register_worker(worker)
            registry.record_worker_capacity_observations(worker.id, ({
                "id": f"usage-{worker.id}", "worker_id": worker.id, "observed_at": now,
                "reset_at": None, "consumed_percent": 10, "state": "NORMAL",
                "provider_diagnostics": {"capacity_mode": "percentage", "capacity_scope": worker.id},
            },), recorded_at=now)

    @staticmethod
    def _replace_stored_planning_hash(fixture, value):
        with sqlite3.connect(fixture["registry"].database) as connection:
            row = connection.execute(
                "SELECT provider_diagnostics_json FROM work_packages WHERE id='TASK-419'"
            ).fetchone()
            diagnostics = json.loads(row[0])
            diagnostics["readiness_proof"]["planning_sha256"]["docs/PLAN.md"] = value
            connection.execute(
                "UPDATE work_packages SET provider_diagnostics_json=? WHERE id='TASK-419'",
                (json.dumps(diagnostics, separators=(",", ":"), sort_keys=True),),
            )

    def _git(self, repository, *args):
        subprocess.run(["git", "-C", str(repository), *args], check=True)

    def _assert_no_active_ownership(self, registry):
        snapshot = registry.dispatch_snapshot(observed_at=datetime.now(timezone.utc).isoformat())
        self.assertFalse(snapshot.active_leases)
        self.assertFalse(registry.active_attempt_runtimes())

    @staticmethod
    def _historical_evidence_counts(registry):
        with sqlite3.connect(registry.database) as connection:
            return tuple(
                connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in ("attempts", "evidence", "task_events")
            )


if __name__ == "__main__":
    unittest.main()
