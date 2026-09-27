import pathlib
import subprocess
import tempfile
import unittest
import json
from datetime import datetime, timezone
from types import SimpleNamespace

from task_readiness import check_packet, inventory
from registry_control import RunnerRegistryControl, queue_contract_digest
from scripts.factory_registry import Feature, Lane, RegistryConflict, SQLiteRegistry, TaskStatus, Worker, WorkPackage


class TaskReadinessTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.repo = pathlib.Path(self.temporary.name)
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        for path in ("docs/PLAN.md", "src/existing.py", "tests/test_existing.py"):
            destination = self.repo / path
            destination.parent.mkdir(exist_ok=True)
            destination.write_text(path)
        subprocess.run(["git", "-C", str(self.repo), "add", "."], check=True)
        subprocess.run([
            "git", "-C", str(self.repo), "-c", "user.name=Test",
            "-c", "user.email=test@example.invalid", "commit", "-qm", "base",
        ], check=True)
        self.base = subprocess.check_output(
            ["git", "-C", str(self.repo), "rev-parse", "HEAD"], text=True,
        ).strip()
        self.package = {"id": "TASK-1", "source_system": "github_issue", "source_ref": "101"}
        self.snapshot = SimpleNamespace(work_packages=(self.package,), active_leases=(), dependencies=())
        self.contract = {
            "schema_version": 2, "paths": ["src/existing.py", "tests/test_existing.py", "src/new.py"],
            "depends_on": [], "readiness": {
                "base_commit": self.base, "planning_paths": ["docs/PLAN.md"],
                "existing_paths": ["src/existing.py", "tests/test_existing.py"],
                "new_paths": ["src/new.py"], "integration_paths": ["src/existing.py"],
                "test_paths": ["tests/test_existing.py"], "dependency_kinds": {},
            },
        }

    def check(self, contract=None, snapshot=None, github_issue=101):
        return check_packet(
            contract or self.contract, repository=self.repo, run_base=self.base,
            package=self.package, snapshot=snapshot or self.snapshot, github_issue=github_issue,
        )

    def test_complete_packet_is_ready_and_legacy_is_not_falsely_approved(self):
        self.assertEqual(self.check().state, "READY")
        self.assertEqual(self.check({"paths": ["src/existing.py"]}).state, "NEEDS_PREPARATION")

    def test_missing_files_base_source_and_unsafe_path_are_precise(self):
        self.assertIn("SOURCE_BINDING_MISMATCH", self.check(github_issue=102).reasons)
        contract = {**self.contract, "readiness": {**self.contract["readiness"],
                    "planning_paths": ["docs/MISSING.md"]}}
        self.assertIn("EXISTING_PATH_MISSING:docs/MISSING.md", self.check(contract).reasons)
        contract = {**self.contract, "readiness": {**self.contract["readiness"],
                    "base_commit": "a" * 40}}
        self.assertIn("BASE_COMMIT_MISSING", self.check(contract).reasons)
        contract = {**self.contract, "paths": ["../escape.py"]}
        self.assertIn("PATH_DECLARATION_MISMATCH", self.check(contract).reasons)
        contract = {**self.contract, "readiness": {**self.contract["readiness"],
                    "test_paths": ["tests/missing.py"]}}
        self.assertIn("EXISTING_PATH_MISSING:tests/missing.py", self.check(contract).reasons)

    def test_dependency_and_exclusive_path_guards(self):
        other = {"id": "TASK-2", "status": "ACTIVE",
                 "provider_diagnostics": {"exclusive_paths": ["src/existing.py"]}}
        snapshot = SimpleNamespace(work_packages=(self.package, other),
                                   active_leases=({"package_id": "TASK-2"},), dependencies=())
        self.assertIn("EXCLUSIVE_PATH_COLLISION:TASK-2", self.check(snapshot=snapshot).reasons)
        contract = {**self.contract, "depends_on": ["TASK-3"],
                    "readiness": {**self.contract["readiness"],
                                  "dependency_kinds": {"TASK-3": "integration"}}}
        snapshot = SimpleNamespace(work_packages=(self.package, {"id": "TASK-3", "status": "READY"}),
                                   active_leases=(), dependencies=(
                                       {"package_id": "TASK-1", "dependency_id": "TASK-3"},))
        self.assertIn("DEPENDENCY_UNMET:TASK-3", self.check(contract, snapshot).reasons)

    def test_inventory_does_not_equate_done_with_integration(self):
        snapshot = SimpleNamespace(work_packages=(
            {"id": "A", "status": "DONE", "source_ref": "101"},
            {"id": "B", "status": "BLOCKED", "source_ref": "102"},
        ), dependencies=())
        groups = {item["id"]: item["group"] for item in inventory(snapshot)}
        self.assertEqual(groups["A"], "RECORDED_DONE_INTEGRATION_UNVERIFIED")
        self.assertEqual(groups["B"], "BLOCKED")

    def test_real_registry_preclaim_blocks_unready_before_provider_and_allows_ready(self):
        database = self.repo / "registry.sqlite3"
        registry = SQLiteRegistry(database)
        registry.initialize()
        now = datetime.now(timezone.utc).isoformat()
        registry.register_feature(Feature("FEATURE", "Ready fixture", 10, TaskStatus.READY))
        registry.register_worker(Worker(
            "worker-a", "Worker A", ("registry",), (Lane.PLATFORM,),
            provider_diagnostics={"capacity_mode": "percentage", "capacity_scopes": ["worker-a"]},
            last_heartbeat_at=now, usage_state="NORMAL",
        ))
        registry.register_worker(Worker(
            "orchestra", "Orchestra", (), (), role="ORCHESTRA",
            provider_diagnostics={"capacity_mode": "percentage", "capacity_scopes": ["orchestra"]},
            last_heartbeat_at=now, usage_state="NORMAL",
        ))
        for worker_id in ("worker-a", "orchestra"):
            registry.record_worker_capacity_observations(worker_id, ({
                "id": f"usage-{worker_id}", "worker_id": worker_id,
                "observed_at": now, "reset_at": None, "consumed_percent": 10,
                "state": "NORMAL", "provider_diagnostics": {
                    "capacity_mode": "percentage", "capacity_scope": worker_id,
                },
            },), recorded_at=now)
        registry.register_work_package(WorkPackage(
            "TASK-1", "FEATURE", "Task", "ORCHESTRATION", Lane.PLATFORM,
            ("registry",), 10, ("verified",), status=TaskStatus.READY,
            provider_diagnostics={"queue_contract_sha256": queue_contract_digest(self.contract)},
        ))
        # The real package source binding is immutable once registered; the
        # fixture supplies it via the reviewed operator's Registry schema.
        with registry._connection() as connection:
            connection.execute("UPDATE work_packages SET source_system='github_issue', source_ref='101' WHERE id='TASK-1'")
        control = registry.dispatch_control()
        registry.set_dispatch_control(
            expected_revision=control["revision"], expected_mode="PAUSED",
            new_mode="LIVE", kill_switch_engaged=False, changed_at=now,
            reason="disposable readiness test",
        )
        controller = RunnerRegistryControl(database, self.repo)
        with self.assertRaisesRegex(RegistryConflict, "TASK_NOT_READY"):
            controller.pre_claim("TASK-1", "worker-a", task_contract=self.contract, github_issue=102)
        revision = controller.pre_claim("TASK-1", "worker-a", task_contract=self.contract, github_issue=101)
        lease = controller.claim_package("TASK-1", worker_id="worker-a", expected_revision=revision,
                                         lease_seconds=120)
        self.assertTrue(lease)


if __name__ == "__main__":
    unittest.main()
