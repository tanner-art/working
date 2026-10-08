"""Cross-module CP-03 v2 readiness canary against disposable Registry state."""

from __future__ import annotations

import hashlib
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone

from scripts.factory_registry import (
    Feature,
    Lane,
    RegistryConflict,
    SQLiteRegistry,
    TaskStatus,
    Worker,
    WorkPackage,
)
from scripts.runner.registry_control import RunnerRegistryControl, queue_contract_digest
from scripts.runner.task_readiness import registration_proof


RUNNER_DIRECTORY = pathlib.Path(__file__).resolve().parents[1] / "runner"
if str(RUNNER_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(RUNNER_DIRECTORY))
from runner import build_agent_prompt, verified_readiness_handoff  # noqa: E402


class CP03CanaryIntegrationTests(unittest.TestCase):
    """Exercise registered proof -> preclaim -> implementation-child handoff."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = pathlib.Path(self.temporary.name)
        self.repository = self.root / "repository"
        subprocess.run(["git", "init", "-q", str(self.repository)], check=True)
        for path, contents in {
            "docs/PLAN.md": "CP-03 planning evidence\n",
            "src/existing.py": "existing = True\n",
            "tests/test_existing.py": "def test_existing(): pass\n",
        }.items():
            destination = self.repository / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(contents)
        self.git("add", ".")
        self.git("-c", "user.name=Canary", "-c", "user.email=canary@example.invalid",
                 "commit", "-qm", "registered base")
        self.git("branch", "-M", "main")
        self.base = self.git_output("rev-parse", "HEAD")

        self.contract = {
            "schema_version": 2,
            "task": "TASK-413",
            "instructions": "Validate the installed CP-03 registration proof.",
            "paths": ["docs/PLAN.md", "src/existing.py", "tests/test_existing.py"],
            "depends_on": [],
            "readiness": {
                "base_commit": self.base,
                "planning_paths": ["docs/PLAN.md"],
                "existing_paths": ["docs/PLAN.md", "src/existing.py", "tests/test_existing.py"],
                "new_paths": [],
                "integration_paths": ["src/existing.py"],
                "test_paths": ["tests/test_existing.py"],
                "dependency_kinds": {},
            },
        }
        self.criteria = ("The implementation child receives the registered proof.",)
        self.database = self.root / "registry.sqlite3"
        self.registry = SQLiteRegistry(self.database)
        self.registry.initialize()
        self.registry.register_feature(Feature("CP-03", "CP-03 canary", 10, TaskStatus.ON_DECK))
        now = datetime.now(timezone.utc).isoformat()
        for worker in (
            Worker("codex-a", "Codex A", ("registry",), (Lane.PLATFORM,),
                   provider_diagnostics={"capacity_mode": "percentage", "capacity_scopes": ["codex-a"]},
                   last_heartbeat_at=now, usage_state="NORMAL"),
            Worker("orchestra", "Orchestra", (), (), role="ORCHESTRA",
                   provider_diagnostics={"capacity_mode": "percentage", "capacity_scopes": ["orchestra"]},
                   last_heartbeat_at=now, usage_state="NORMAL"),
        ):
            self.registry.register_worker(worker)
            self.registry.record_worker_capacity_observations(worker.id, ({
                "id": f"capacity-{worker.id}", "worker_id": worker.id,
                "observed_at": now, "reset_at": None, "consumed_percent": 10,
                "state": "NORMAL", "provider_diagnostics": {
                    "capacity_mode": "percentage", "capacity_scope": worker.id,
                },
            },), recorded_at=now)
        self.proof = registration_proof(
            self.contract, repository=self.repository, target_ref="main",
            acceptance_criteria=self.criteria,
        )
        self.registry.register_work_package(WorkPackage(
            "TASK-413", "CP-03", "CP-03 v2 handoff canary", "ORCHESTRATION",
            Lane.PLATFORM, ("registry",), 10, self.criteria, status=TaskStatus.READY,
            provider_diagnostics={
                "readiness_schema_version": 2,
                "queue_contract_sha256": queue_contract_digest(self.contract),
                "readiness_proof": self.proof,
            },
        ))
        self.registry.bind_legacy_package_source(
            "TASK-413", github_issue=413, queue_contract=self.contract,
            expected_revision=self.registry.dispatch_control()["revision"], recorded_at=now,
        )
        control = self.registry.dispatch_control()
        self.registry.set_dispatch_control(
            expected_revision=control["revision"], expected_mode="PAUSED", new_mode="LIVE",
            kill_switch_engaged=False, changed_at=now, reason="disposable CP-03 canary",
            bounded_run={"run_id": "cp03-canary", "package_ids": ["TASK-413"],
                         "deadline": "2026-10-09T00:00:00+00:00", "base_ref": "main",
                         "parent_limit": 1},
        )
        self.control = RunnerRegistryControl(self.database, self.repository)

    def git(self, *args: str) -> None:
        subprocess.run(["git", "-C", str(self.repository), *args], check=True)

    def git_output(self, *args: str) -> str:
        return subprocess.check_output(["git", "-C", str(self.repository), *args], text=True).strip()

    def preserved_ownership_and_history(self) -> tuple[int, int, int]:
        with self.registry._connection() as connection:
            return tuple(connection.execute(query).fetchone()[0] for query in (
                "SELECT count(*) FROM leases WHERE released_at IS NULL",
                "SELECT count(*) FROM attempts WHERE ended_at IS NULL",
                "SELECT count(*) FROM task_events WHERE package_id='TASK-413'",
            ))

    def assert_preclaim_rejects_without_launch(self, contract, issue: int, reason: str) -> None:
        before = self.preserved_ownership_and_history()
        provider_launches: list[str] = []
        with self.assertRaisesRegex(RegistryConflict, reason):
            self.control.pre_claim("TASK-413", "codex-a", task_contract=contract,
                                   github_issue=issue)
        self.assertEqual(provider_launches, [])
        self.assertEqual(self.preserved_ownership_and_history(), before)

    def test_registered_v2_proof_reaches_child_prompt_and_drift_never_launches(self) -> None:
        revision = self.control.pre_claim(
            "TASK-413", "codex-a", task_contract=self.contract, github_issue=413,
        )
        handoff, handoff_revision = verified_readiness_handoff(
            self.control, self.contract, self.base,
        )
        prompt = build_agent_prompt(413, self.contract, worker="codex-a", slot=1,
                                    readiness_handoff=handoff)
        self.assertEqual(handoff_revision, revision)
        self.assertEqual(self.proof["base_commit"], self.base)
        self.assertEqual(self.proof["target_ref"], "main")
        for value in (
            str(revision), self.base, "main", self.proof["queue_contract_sha256"],
            self.proof["acceptance_sha256"], self.proof["planning_sha256"]["docs/PLAN.md"],
            self.criteria[0],
        ):
            self.assertIn(value, prompt)

        # A replacement commit changes only the planning blob visible at the
        # registered base; main still resolves to the registered commit.
        (self.repository / "docs/PLAN.md").write_text("changed planning blob\n")
        self.git("add", "docs/PLAN.md")
        self.git("-c", "user.name=Canary", "-c", "user.email=canary@example.invalid",
                 "commit", "-qm", "replacement planning blob")
        replacement = self.git_output("rev-parse", "HEAD")
        self.git("replace", self.base, replacement)
        self.assertEqual(self.git_output("rev-parse", "main"), self.base)
        self.assert_preclaim_rejects_without_launch(
            self.contract, 413, "REGISTRATION_PROOF_CHANGED",
        )
        self.git("replace", "-d", self.base)

        # Advancing the target ref is distinct from changing the registered blob.
        self.git("checkout", "-q", "main")
        (self.repository / "src/existing.py").write_text("existing = 'moved base'\n")
        self.git("add", "src/existing.py")
        self.git("-c", "user.name=Canary", "-c", "user.email=canary@example.invalid",
                 "commit", "-qm", "move main")
        self.assert_preclaim_rejects_without_launch(
            self.contract, 413, "REGISTRATION_PROOF_INVALID:BASE_REF_CHANGED",
        )

        changed_contract = {**self.contract, "instructions": "different source contract"}
        self.assert_preclaim_rejects_without_launch(
            changed_contract, 413, "QUEUE_CONTRACT_MISMATCH",
        )
        self.assert_preclaim_rejects_without_launch(
            self.contract, 414, "GITHUB_SOURCE_MISMATCH",
        )


if __name__ == "__main__":
    unittest.main()
