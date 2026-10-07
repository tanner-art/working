"""CP-03 canary: registered v2 proof reaches the implementation child handoff."""
from __future__ import annotations

import pathlib
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock
from unittest.mock import patch


ROOT = pathlib.Path(__file__).resolve().parents[2]
RUNNER = ROOT / "scripts" / "runner"
if str(RUNNER) not in sys.path:
    sys.path.insert(0, str(RUNNER))

from registry_control import RunnerRegistryControl, queue_contract_digest  # noqa: E402
from runner import build_agent_prompt, verified_readiness_handoff  # noqa: E402
from task_readiness import registration_proof  # noqa: E402
from scripts.factory_registry import Feature, Lane, RegistryConflict, SQLiteRegistry, TaskStatus, Worker, WorkPackage  # noqa: E402


BASE = "f5b3535764161649639be06724bddd863f28869b"
TARGET = "main"
ISSUE = 408
PLANNING_HASHES = {
    "AGENTS.md": "b1de2b77b56b147a701550ed738c1e19203bec39399dbf8f25fd6255c6f387ac",
    "TASKS.md": "04ab551e9057b445ceb313ce77556d902801bcc7f7cdf704f7e7f3b87c694038",
    "docs/ARCHITECTURE.md": "d0f9feafa19aa2368348094e01fe52424282db1d1183f453a398e5b4845d24dd",
    "docs/DECISIONS.md": "cf72aab01fe62d89d43c254d0114c0c6c7b9c1ed4e100352e8b0ee4a2c69252e",
    "docs/NORTH_STAR.md": "f187c86595999dc5806f422de317094f7c911c3fc2479a5b4acb4b791839a70c",
    "docs/ROADMAP.md": "e741b94c4a827df12e8a684122c4275dd12535cdbf75856d7301efe5e46a8bb2",
    "docs/factory/CONTROL_PLANE_HARDENING_RECONCILIATION_2026-09-25.md": "78450414cba865b5a3dbcca6f811a57fbef518fbb29ce1006daf28834cd4cacd",
    "docs/factory/CP_03_READINESS_EVIDENCE.md": "148a93ee593ec66929b11c6b27073c35ba4a1b00f747c46a46bfc2bc35c9699f",
    "docs/factory/R1_READINESS_SOLO_VALIDATION_2026-09-27.md": "2844aa34589865d16c1ff2b1d64e4af794d2ddd0b132670cb6a6d795ecc6a305",
}


class CP03CanaryIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = pathlib.Path(self.temporary.name)
        self.repository = root / "repository"
        subprocess.run(["git", "clone", "-q", str(ROOT), str(self.repository)], check=True)
        subprocess.run(["git", "-C", str(self.repository), "checkout", "-q", "-B", TARGET, BASE], check=True)
        self.database = root / "registry.sqlite3"
        self.registry = SQLiteRegistry(self.database)
        self.registry.initialize()
        self.contract = self.contract_for_base(BASE)
        self.criteria = ("CP-03 canary handoff preserves the registered proof.",)
        proof = registration_proof(
            self.contract, repository=self.repository, target_ref=TARGET,
            acceptance_criteria=self.criteria,
        )
        self.assertEqual(proof["base_commit"], BASE)
        self.assertEqual(proof["target_ref"], TARGET)
        self.assertEqual(proof["planning_sha256"], PLANNING_HASHES)
        now = datetime.now(timezone.utc).isoformat()
        self.registry.register_feature(Feature("FEATURE-408", "CP-03 canary", 1, TaskStatus.READY))
        self.registry.register_worker(Worker(
            "codex-a", "Codex A", ("registry",), (Lane.PLATFORM,),
            provider_diagnostics={"capacity_mode": "percentage", "capacity_scopes": ["codex-a"]},
            last_heartbeat_at=now, usage_state="NORMAL",
        ))
        self.registry.register_worker(Worker(
            "orchestra", "Orchestra", (), (), role="ORCHESTRA",
            provider_diagnostics={"capacity_mode": "percentage", "capacity_scopes": ["orchestra"]},
            last_heartbeat_at=now, usage_state="NORMAL",
        ))
        for worker_id in ("codex-a", "orchestra"):
            self.registry.record_worker_capacity_observations(worker_id, ({
                "id": f"capacity-{worker_id}", "worker_id": worker_id,
                "observed_at": now, "reset_at": None, "consumed_percent": 10,
                "state": "NORMAL", "provider_diagnostics": {
                    "capacity_mode": "percentage", "capacity_scope": worker_id,
                },
            },), recorded_at=now)
        self.registry.register_work_package(WorkPackage(
            "TASK-408", "FEATURE-408", "CP-03 proof canary", "ORCHESTRATION",
            Lane.PLATFORM, ("registry",), 1, self.criteria, status=TaskStatus.READY,
            provider_diagnostics={
                "readiness_schema_version": 2,
                "queue_contract_sha256": queue_contract_digest(self.contract),
                "readiness_proof": proof,
            },
        ))
        self.registry.bind_legacy_package_source(
            "TASK-408", github_issue=ISSUE, queue_contract=self.contract,
            expected_revision=self.registry.dispatch_control()["revision"], recorded_at=now,
        )
        control = self.registry.dispatch_control()
        self.registry.set_dispatch_control(
            expected_revision=control["revision"], expected_mode="PAUSED", new_mode="LIVE",
            kill_switch_engaged=False, changed_at=now, reason="disposable CP-03 canary",
        )
        self.control = RunnerRegistryControl(self.database, self.repository)

    @staticmethod
    def contract_for_base(base: str) -> dict:
        return {
            "schema_version": 2,
            "task": "TASK-408",
            "paths": [
                "docs/factory/CP_03_READINESS_EVIDENCE.md",
                "scripts/factory_registry/test_cp03_canary_integration.py",
            ],
            "instructions": "Validate the already-installed CP-03 v2 registration proof.",
            "depends_on": [],
            "lane": "PLATFORM",
            "kind": "PARENT",
            "capacity_size": "VERY_SMALL",
            "capacity_risk": "BOUNDED",
            "readiness": {
                "base_commit": base,
                "planning_paths": sorted(PLANNING_HASHES),
                "existing_paths": ["docs/factory/CP_03_READINESS_EVIDENCE.md"],
                "new_paths": ["scripts/factory_registry/test_cp03_canary_integration.py"],
                "integration_paths": ["docs/factory/CP_03_READINESS_EVIDENCE.md"],
                "test_paths": ["scripts/factory_registry/test_cp03_canary_integration.py"],
                "dependency_kinds": {},
            },
        }

    def assert_no_ownership(self) -> None:
        snapshot = self.registry.dispatch_snapshot(observed_at=datetime.now(timezone.utc).isoformat())
        self.assertFalse(snapshot.active_leases)
        self.assertEqual(next(item for item in snapshot.work_packages if item["id"] == "TASK-408")["status"], "READY")

    def test_registered_proof_reaches_preclaim_and_implementation_prompt(self) -> None:
        revision = self.control.pre_claim(
            "TASK-408", "codex-a", task_contract=self.contract, github_issue=ISSUE,
        )
        handoff, handoff_revision = verified_readiness_handoff(self.control, self.contract, BASE)
        prompt = build_agent_prompt(ISSUE, self.contract, worker="codex-a", readiness_handoff=handoff)
        self.assertEqual(revision, handoff_revision)
        for value in (BASE, TARGET, queue_contract_digest(self.contract), *self.criteria,
                      *PLANNING_HASHES.values()):
            self.assertIn(value, prompt)
        self.assert_no_ownership()

    def test_drift_or_source_mismatch_fails_before_provider_launch(self) -> None:
        cases = (
            ("changed planning blob", self.contract, ISSUE, "DISPATCH_PAIR_INELIGIBLE", {
                "planning_sha256": {**PLANNING_HASHES, "AGENTS.md": "0" * 64},
            }),
            ("source issue mismatch", self.contract, ISSUE + 1, "DISPATCH_PAIR_INELIGIBLE", None),
            ("source contract mismatch", {**self.contract, "instructions": "Changed after registration."}, ISSUE,
             "QUEUE_CONTRACT_MISMATCH", None),
        )
        for name, contract, issue, code, proof_change in cases:
            with self.subTest(name=name):
                launch = Mock()
                snapshot = self.registry.dispatch_snapshot(observed_at=datetime.now(timezone.utc).isoformat())
                packages = list(snapshot.work_packages)
                if proof_change is not None:
                    diagnostics = dict(packages[0]["provider_diagnostics"])
                    diagnostics["readiness_proof"] = {**diagnostics["readiness_proof"], **proof_change}
                    packages[0] = {**packages[0], "provider_diagnostics": diagnostics}
                with patch.object(self.control.registry, "dispatch_snapshot", return_value=SimpleNamespace(
                    revision=snapshot.revision, work_packages=tuple(packages),
                    active_leases=snapshot.active_leases, dependencies=snapshot.dependencies,
                    workers=snapshot.workers,
                )):
                    with self.assertRaises(RegistryConflict) as raised:
                        self.control.pre_claim("TASK-408", "codex-a", task_contract=contract, github_issue=issue)
                self.assertEqual(raised.exception.code, code)
                if proof_change is not None:
                    self.assertIn("REGISTRATION_PROOF_CHANGED", raised.exception.detail)
                launch.assert_not_called()
                self.assert_no_ownership()
        (self.repository / "moved-base.txt").write_text("main advanced\n")
        subprocess.run(["git", "-C", str(self.repository), "add", "moved-base.txt"], check=True)
        subprocess.run([
            "git", "-C", str(self.repository), "-c", "user.name=Canary",
            "-c", "user.email=canary@example.invalid", "commit", "-qm", "move main",
        ], check=True)
        launch = Mock()
        with self.assertRaises(RegistryConflict) as raised:
            self.control.pre_claim("TASK-408", "codex-a", task_contract=self.contract, github_issue=ISSUE)
        self.assertEqual(raised.exception.code, "DISPATCH_PAIR_INELIGIBLE")
        self.assertIn("BASE_REF_CHANGED", raised.exception.detail)
        launch.assert_not_called()
        self.assert_no_ownership()


if __name__ == "__main__":
    unittest.main()
