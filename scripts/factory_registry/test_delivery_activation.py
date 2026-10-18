"""Mixed resumed-front activation keeps historical context out of dispatch."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

from scripts.factory_registry.operator import (
    OperatorError, REQUIRED_RELEASE_FILES, _validate_plan, bounded_run_worker_gate,
)
from scripts.factory_registry.repository import RegistryConflict
from scripts.factory_registry.test_shadow_dispatch import package, snapshot, worker


class DeliveryActivationTests(unittest.TestCase):
    def setUp(self):
        self.packages = (
            package("TASK-1", capabilities=("implementation",)),
            package("TASK-2", kind="REVIEW", status="ON_DECK", lane="ASSURANCE", capabilities=("review",)),
            package("TASK-3", status="VERIFY_REVIEW", capabilities=("implementation",)),
            package("TASK-4", kind="REVIEW", status="READY", lane="ASSURANCE", capabilities=("review",)),
        )
        self.dependencies = (
            {"package_id": "TASK-2", "dependency_id": "TASK-1"},
            {"package_id": "TASK-4", "dependency_id": "TASK-3"},
        )
        self.snapshot = snapshot(packages=self.packages, dependencies=self.dependencies, workers=(
            worker("builder", capabilities=("implementation",)),
            worker("reviewer", capabilities=("review",), lanes=("ASSURANCE",)),
        ))
        self.lookup = Mock(return_value={"target_package_id": "TASK-3",
            "review_package_id": "TASK-4", "implementation_attempt_id": "exact-implementation-attempt",
            "implementation_commit": "a" * 40})
        self.implementer = Mock(return_value="builder")
        self.ids = ["TASK-1", "TASK-2", "TASK-4"]

    def gate(self, candidate=None, **kwargs):
        return bounded_run_worker_gate(candidate or self.snapshot, self.ids,
            review_input_lookup=self.lookup, successful_attempt_worker=self.implementer, **kwargs)

    def test_mixed_ready_pair_and_review_context_preserves_both_provenance_paths(self):
        evidence = self.gate()
        self.lookup.assert_called_once_with("TASK-4")
        self.implementer.assert_called_once_with("TASK-3", "exact-implementation-attempt")
        self.assertEqual(evidence["run_package_ids"], self.ids)
        self.assertEqual(evidence["independent_pairs"],
                         [["TASK-1", "builder", "reviewer"], ["TASK-4", "builder", "reviewer"]])
        self.assertNotIn("TASK-3", evidence["implementation_assignments"])
        self.assertEqual(evidence["implementation_assignments"]["TASK-1"], ["builder"])

    def test_external_review_cannot_skip_authoritative_provenance_lookup(self):
        with self.assertRaisesRegex(OperatorError, "provenance lookup is required"):
            bounded_run_worker_gate(self.snapshot, self.ids)

    def test_external_review_uses_registry_review_implementer_resolver_when_available(self):
        resolver = Mock(return_value="builder")
        self.gate(review_implementer_worker=resolver)
        resolver.assert_called_once_with("TASK-4")
        self.implementer.assert_not_called()

    def test_external_review_refuses_invalid_target_status_or_kind(self):
        for mutation in ({"status": "READY"}, {"status": "BLOCKED"}, {"status": "DONE"},
                         {"status": "ACTIVE"}, {"kind": "REVIEW"}):
            with self.subTest(mutation=mutation):
                packages = tuple({**row, **mutation} if row["id"] == "TASK-3" else row for row in self.packages)
                with self.assertRaisesRegex(OperatorError, "VERIFY_REVIEW parent"):
                    self.gate(replace(self.snapshot, work_packages=packages))

    def test_external_review_refuses_missing_or_wrong_attempt_binding(self):
        for packet in ({"target_package_id": "TASK-99", "implementation_attempt_id": "attempt"},
                       {"target_package_id": "TASK-3"},
                       {"target_package_id": "TASK-3", "implementation_attempt_id": ""}):
            with self.subTest(packet=packet), self.assertRaisesRegex(OperatorError, "does not bind its target"):
                self.lookup.return_value = packet
                self.gate()

    def test_external_review_propagates_unsuccessful_attempt_and_missing_implementer(self):
        self.implementer.side_effect = RegistryConflict("SUCCESSFUL_ATTEMPT_REQUIRED")
        with self.assertRaisesRegex(OperatorError, "provenance gate failed: SUCCESSFUL_ATTEMPT_REQUIRED"):
            self.gate()
        self.implementer.side_effect = None
        self.implementer.return_value = None
        with self.assertRaisesRegex(OperatorError, "no authoritative implementer"):
            self.gate()

    def test_healthy_pair_does_not_hide_external_self_review(self):
        self.implementer.return_value = "reviewer"
        with self.assertRaisesRegex(OperatorError, "no independent reviewer for TASK-4"):
            self.gate()

    def test_healthy_pair_does_not_hide_internal_self_review(self):
        packages = (
            *self.packages[:2],
            package("TASK-3", capabilities=("special-implementation",)),
            package("TASK-4", kind="REVIEW", lane="ASSURANCE", capabilities=("special-review",)),
        )
        candidate = snapshot(packages=packages, dependencies=self.dependencies, workers=(
            worker("builder", capabilities=("implementation",)),
            worker("reviewer", capabilities=("review",), lanes=("ASSURANCE",)),
            worker("self-only", capabilities=("special-implementation", "special-review"), lanes=("PLATFORM", "ASSURANCE")),
        ))
        with self.assertRaisesRegex(OperatorError, "no independent reviewer for TASK-4"):
            bounded_run_worker_gate(candidate, ["TASK-1", "TASK-2", "TASK-3", "TASK-4"])

    def test_every_scoped_parent_requires_exactly_one_review(self):
        for dependencies in (
            (self.dependencies[1],),
            (self.dependencies[0], {"package_id": "TASK-4", "dependency_id": "TASK-1"}),
        ):
            with self.subTest(dependencies=dependencies), self.assertRaises(OperatorError):
                self.gate(replace(self.snapshot, dependencies=dependencies))

    def test_mixed_front_preserves_global_capacity_gate(self):
        with self.assertRaisesRegex(OperatorError, "global worker/capacity gate failed"):
            self.gate(replace(self.snapshot, observed_at="2026-09-24T14:00:00Z"))

    def test_review_only_independence_is_required_for_every_review(self):
        packages = tuple({**row, "status": "VERIFY_REVIEW"} if row["id"] == "TASK-1" else row for row in self.packages)
        lookup = Mock(side_effect=lambda review: {
            "target_package_id": "TASK-1" if review == "TASK-2" else "TASK-3",
            "implementation_attempt_id": "attempt-" + review,
        })
        implementer = Mock(side_effect=lambda target, attempt: "builder" if target == "TASK-1" else "reviewer")
        with self.assertRaisesRegex(OperatorError, "no independent reviewer for TASK-4"):
            bounded_run_worker_gate(replace(self.snapshot, work_packages=packages), ["TASK-2", "TASK-4"],
                review_input_lookup=lookup, successful_attempt_worker=implementer)
        self.assertEqual(lookup.call_count, 2)


class DeliveryServicePlanTests(unittest.TestCase):
    """Validation only: no service installation or provider is invoked."""

    def setUp(self):
        self.release = Path("/private/tmp/reviewed-delivery-release").resolve()
        self.database = Path("/private/tmp/private-factory/registry.sqlite3")
        self.config_path = Path("/private/tmp/private-factory/config.json")
        self.config = {"registry_database": str(self.database), "delivery": {
            "run_id": "run-1", "planner_agent": "codex-b", "coordinator_worker_id": "orchestra",
            "validation_commands": [["npm", "test"]],
        }}
        self.label = "life.threadline.factory.delivery"

    def data(self, live):
        args = [sys.executable, "-m", "scripts.factory_registry.delivery_cli", "tick" if live else "status",
                "--database", str(self.database)]
        args.extend(["--config", str(self.config_path.resolve())] if live else ["--run-id", "run-1"])
        return {"Label": self.label, "ProgramArguments": args, "WorkingDirectory": str(self.release)}

    def validate(self, data, live, label=None):
        _validate_plan([(label or self.label, data)], self.release, live=live,
                       config=self.config, config_path=self.config_path, database=self.database)

    def test_exact_live_tick_and_readonly_dry_status_are_accepted(self):
        self.validate(self.data(True), True)
        self.validate(self.data(False), False)

    def test_live_tick_cannot_be_installed_as_a_dry_service(self):
        with self.assertRaisesRegex(OperatorError, "exact pinned live/status command"):
            self.validate(self.data(True), False)
        data = self.data(True)
        data["ProgramArguments"].append("--dry-run")
        with self.assertRaisesRegex(OperatorError, "exact pinned live/status command"):
            self.validate(data, False)
        with self.assertRaisesRegex(OperatorError, "exact pinned live/status command"):
            self.validate(self.data(False), True)

    def test_delivery_command_cannot_change_module_interpreter_database_config_or_verb(self):
        mutations = (
            (0, "/unreviewed/python3"), (1, "-c"), (2, "unreviewed.delivery"), (3, "authorize"),
            (4, "--other-database"), (5, "/private/tmp/other.sqlite3"),
            (6, "--environment"), (7, "/private/tmp/other-config.json"),
        )
        for index, value in mutations:
            with self.subTest(index=index), self.assertRaisesRegex(OperatorError, "exact pinned live/status command"):
                data = self.data(True)
                data["ProgramArguments"][index] = value
                self.validate(data, True)
        data = self.data(True)
        data["ProgramArguments"].append("unreviewed-argument")
        with self.assertRaisesRegex(OperatorError, "exact pinned live/status command"):
            self.validate(data, True)

    def test_delivery_dry_status_cannot_query_another_run(self):
        data = self.data(False)
        data["ProgramArguments"][-1] = "run-2"
        with self.assertRaisesRegex(OperatorError, "exact pinned live/status command"):
            self.validate(data, False)

    def test_delivery_requires_exact_label_and_immutable_release_working_directory(self):
        for key, value in (("Label", "unreviewed.delivery"), ("WorkingDirectory", str(self.release.parent))):
            with self.subTest(key=key), self.assertRaisesRegex(OperatorError, "exact pinned live/status command"):
                data = self.data(True)
                data[key] = value
                self.validate(data, True)
        with self.assertRaisesRegex(OperatorError, "not pinned to release"):
            self.validate(self.data(True), True, label="life.threadline.runner.codex-a")

    def test_delivery_requires_independent_expected_configuration(self):
        with self.assertRaisesRegex(OperatorError, "exact operator configuration"):
            _validate_plan([(self.label, self.data(True))], self.release, live=True)
        self.config["registry_database"] = "/private/tmp/another.sqlite3"
        with self.assertRaisesRegex(OperatorError, "exact operator configuration"):
            self.validate(self.data(True), True)

    def test_legacy_script_validation_remains_required(self):
        root = self.release / "scripts/runner"
        data = {"ProgramArguments": [sys.executable, str(root / "runner.py"), "--dry-run"]}
        _validate_plan([("life.threadline.runner.codex-a", data)], self.release, live=False)
        with self.assertRaisesRegex(OperatorError, "live/dry-run mismatch"):
            _validate_plan([("life.threadline.runner.codex-a", data)], self.release, live=True)
        data["ProgramArguments"][1] = "/unreviewed/runner.py"
        with self.assertRaisesRegex(OperatorError, "not pinned to release"):
            _validate_plan([("life.threadline.runner.codex-a", data)], self.release, live=False)

    def test_release_manifest_requires_entire_delivery_runtime_import_closure(self):
        names = ("sqlite_delivery", "delivery_plan", "delivery_runtime", "delivery_integration",
                 "delivery_repair", "delivery_coordinator", "delivery_service", "delivery_cli",
                 "delivery_planner_barrier")
        self.assertTrue({"scripts/factory_registry/" + name + ".py" for name in names} <= REQUIRED_RELEASE_FILES)


if __name__ == "__main__":
    unittest.main()
