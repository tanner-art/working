import copy
from dataclasses import replace
import json
import pathlib
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from scripts.factory_registry.delivery_plan import (
    FeatureBrief, PlanError, build_packages, build_planner_prompt, validate_plan, validate_prepared_pair,
)
from scripts.factory_registry.models import Lane, PackageKind, TaskStatus
from scripts.runner.task_readiness import check_packet, ready_contract_reasons


class DeliveryPlanTests(unittest.TestCase):
    """Exercise planning against real immutable Git trees, not path mocks."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.repo = pathlib.Path(temporary.name)
        self.git("init", "-q")
        for path in ("docs/PLAN.md", "src/App.tsx", "src/ideas.ts", "tests/ideas.test.ts"):
            destination = self.repo / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(f"Existing content for {path}\n")
        self.git("add", ".")
        self.git("-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "base")
        self.git("branch", "-M", "main")
        self.base = self.git("rev-parse", "HEAD").strip()
        self.owner = {
            "id": "FEATURE-IDEA-SEARCH", "title": "Search saved ideas",
            "user_experience": "I want to type a phrase and open the matching saved idea.",
        }
        self.brief = FeatureBrief.from_dict(self.owner)
        self.payload = {
            "state": "PREPARED", "feature_id": self.brief.id, "base_commit": self.base,
            "user_experience": self.brief.user_experience, "dependency_feature_ids": [], "decisions_needed": [],
            "package": {
                "behavior": "Search and open matching saved ideas from the Ideas screen.",
                "module_boundary": "ideaSearch owns filtering; App owns selection and rendering.",
                "public_interface": ["findIdeas(query, ideas) returns stable idea IDs for the Ideas screen."],
                "persistence_owner": "none",
                "end_to_end": {"entry_point": "Ideas screen", "user_action": "Type a phrase and select a result",
                               "observable_result": "The selected saved idea opens with its original content."},
                "acceptance_criteria": ["Typing a matching phrase shows the idea; choosing it opens the correct content."],
                "out_of_scope": ["Semantic ranking and separate search services"],
                "instructions": "Reuse stored ideas and expose a small pure filter module. Wire results into existing selection.",
                "planning_paths": ["docs/PLAN.md"],
                "existing_paths": ["src/App.tsx", "src/ideas.ts", "tests/ideas.test.ts"],
                "new_paths": ["src/ideaSearch.ts"], "integration_paths": ["src/App.tsx"],
                "test_paths": ["tests/ideas.test.ts"], "required_capabilities": ["frontend", "testing"],
                "capacity_size": "SMALL", "capacity_risk": "BOUNDED",
            },
        }

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.repo), *args], text=True, stderr=subprocess.DEVNULL)

    def validate(self, payload=None, brief=None):
        return validate_plan(self.payload if payload is None else payload,
                             brief=self.brief if brief is None else brief,
                             repository=self.repo, target_ref="main")

    def build(self, plan=None, **kwargs):
        return build_packages(plan or self.validate(), repository=self.repo, target_ref="main",
                              implementation_issue=501, review_issue=502, **kwargs)

    def advance(self):
        (self.repo / "docs/PLAN.md").write_text("Updated intent\n")
        self.git("add", "docs/PLAN.md")
        self.git("-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "advance")

    def test_minimal_owner_input_is_preserved_and_needs_no_operational_metadata(self):
        self.assertEqual(self.brief.as_dict(), self.owner)
        owner = {**self.owner, "user_experience": "  Keep the owner's spacing.\n", "constraints": ["No new fields"]}
        brief = FeatureBrief.from_dict(owner)
        self.assertEqual(brief.as_dict(), owner)
        owner["constraints"].append("Later mutation")
        self.assertEqual(brief.as_dict()["constraints"], ["No new fields"])
        for invalid in ({"id": "a", "title": "b"}, {**self.owner, "command": ["run"]},
                        {**self.owner, "dependency_feature_ids": [self.brief.id]},
                        {**self.owner, "constraints": "not a list"}):
            with self.subTest(invalid=invalid), self.assertRaises(PlanError):
                FeatureBrief.from_dict(invalid)

    def test_prompt_contains_exact_tree_owner_input_and_read_only_contract(self):
        prompt = build_planner_prompt(self.brief, repository=self.repo, target_ref="main")
        self.assertIn(self.base, prompt)
        self.assertIn(self.brief.request_json, prompt)
        self.assertIn("src/App.tsx", prompt)
        self.assertIn("NEEDS_DECISION", prompt)
        self.assertIn("read-only", prompt)
        (self.repo / "untracked-secret.txt").write_text("never included")
        self.assertNotIn("untracked-secret", build_planner_prompt(self.brief, repository=self.repo, target_ref="main"))
        with self.assertRaisesRegex(PlanError, "TARGET_REF_INVALID"):
            build_planner_prompt(self.brief, repository=self.repo, target_ref="--output=oops")

    def test_prepared_pair_has_independent_review_and_valid_registration_proofs(self):
        pair = self.build()
        self.assertEqual(pair.implementation.status, TaskStatus.ON_DECK)
        self.assertEqual(pair.review.status, TaskStatus.ON_DECK)
        self.assertEqual(pair.implementation.lane, Lane.FEATURE)
        self.assertEqual(pair.review.lane, Lane.ASSURANCE)
        self.assertEqual(pair.review.kind, PackageKind.REVIEW)
        self.assertEqual(pair.review.required_capabilities, ("independent-review",))
        self.assertEqual(pair.review.dependency_ids, ("TASK-501",))
        self.assertEqual(pair.review_contract["depends_on"], [501])
        self.assertEqual(pair.implementation_contract["readiness"]["base_commit"], self.base)
        for package in (pair.implementation, pair.review):
            self.assertEqual(ready_contract_reasons({
                "lane": package.lane, "acceptance_criteria": package.acceptance_criteria,
                "provider_diagnostics": package.provider_diagnostics,
            }), ())
            self.assertEqual(package.provider_diagnostics["owner_request"], self.owner)
            self.assertEqual(package.provider_diagnostics["persistence_owner"], "none")
            self.assertIn("docs/PLAN.md", package.provider_diagnostics["readiness_proof"]["planning_sha256"])
        package = {**pair.implementation.__dict__, "source_system": "github_issue", "source_ref": "501"}
        snapshot = SimpleNamespace(work_packages=(package,), dependencies=(), active_leases=())
        self.assertEqual(check_packet(pair.implementation_contract, repository=self.repo, run_base="main",
                                      package=package, snapshot=snapshot, github_issue=501).state, "READY")

    def test_returned_contract_mutation_cannot_change_preserved_plan_or_other_contracts(self):
        plan = self.validate()
        plan.package["new_paths"].append("src/out-of-scope.ts")
        self.assertEqual(plan.package["new_paths"], ["src/ideaSearch.ts"])
        pair = self.build(plan)
        pair.implementation_contract["paths"].append("src/out-of-scope.ts")
        self.assertNotIn("src/out-of-scope.ts", pair.implementation_contract["paths"])

    def test_unresolved_decisions_produce_explicit_blocked_result_and_no_package(self):
        data = {key: value for key, value in self.payload.items() if key != "package"}
        data.update(state="NEEDS_DECISION", decisions_needed=["Should shared ideas be searchable by other users?"])
        plan = self.validate(data)
        self.assertEqual(plan.state, "NEEDS_DECISION")
        self.assertIsNone(plan.package)
        self.assertTrue(plan.decisions_needed)
        with self.assertRaisesRegex(PlanError, "requires owner decision"):
            self.build(plan)
        for changed in ({**data, "package": self.payload["package"]}, {**data, "decisions_needed": []},
                        {**self.payload, "decisions_needed": ["Unresolved choice"]}):
            with self.subTest(changed=changed), self.assertRaises(PlanError):
                self.validate(changed)

    def test_malformed_provider_output_never_becomes_a_ready_package(self):
        cases = ["APPROVED", "```json\n{}\n```", "[]", '{"state":"PREPARED","state":"NEEDS_DECISION"}',
                 {**self.payload, "commands": ["anything"]}, {**self.payload, "state": "READY"},
                 {**self.payload, "state": "APPROVED"}]
        for case in cases:
            with self.subTest(case=case), self.assertRaises(PlanError):
                self.validate(case)

    def test_missing_observable_product_behavior_and_public_interface_are_rejected(self):
        for key, value in (("end_to_end", {}), ("behavior", ""), ("public_interface", []),
                           ("module_boundary", ""), ("acceptance_criteria", [])):
            data = copy.deepcopy(self.payload)
            data["package"][key] = value
            with self.subTest(key=key), self.assertRaises(PlanError):
                self.validate(data)

    def test_owner_intent_criteria_and_constraints_survive_into_handoff(self):
        owner = {**self.owner, "constraints": ["Do not create calendar events"],
                 "acceptance_criteria": ["Existing ideas remain unchanged"]}
        brief = FeatureBrief.from_dict(owner)
        with self.assertRaisesRegex(PlanError, "OWNER_ACCEPTANCE_CRITERIA_OMITTED"):
            self.validate(brief=brief)
        data = copy.deepcopy(self.payload)
        data["package"]["acceptance_criteria"].extend(owner["acceptance_criteria"])
        pair = self.build(self.validate(data, brief))
        self.assertIn(owner["constraints"][0], pair.implementation_contract["instructions"])
        self.assertIn(owner["acceptance_criteria"][0], pair.implementation.acceptance_criteria)
        for field, value in (("feature_id", "OTHER"), ("user_experience", "Add a social network")):
            with self.subTest(field=field), self.assertRaisesRegex(PlanError, "OWNER_REQUEST_MISMATCH"):
                self.validate({**self.payload, field: value})

    def test_dependency_features_must_match_and_resolve_to_unique_package_ids(self):
        brief = FeatureBrief.from_dict({**self.owner, "dependency_feature_ids": ["FEATURE-IDEAS"]})
        with self.assertRaisesRegex(PlanError, "DEPENDENCY_FEATURE_MISMATCH"):
            self.validate(brief=brief)
        data = {**self.payload, "dependency_feature_ids": ["FEATURE-IDEAS"]}
        plan = self.validate(data, brief)
        for mapping in ({}, {"UNRELATED": "TASK-400"}, {"FEATURE-IDEAS": "TASK-501"}, {"FEATURE-IDEAS": "main;run"}):
            with self.subTest(mapping=mapping), self.assertRaises(PlanError):
                self.build(plan, dependency_packages=mapping)
        pair = self.build(plan, dependency_packages={"FEATURE-IDEAS": "TASK-400"})
        self.assertEqual(pair.implementation.dependency_ids, ("TASK-400",))
        self.assertEqual(pair.implementation_contract["readiness"]["dependency_kinds"], {"TASK-400": "integration"})

    def test_base_advancing_invalidates_validation_and_previously_prepared_pair(self):
        plan = self.validate()
        self.advance()
        with self.assertRaisesRegex(PlanError, "BASE_REF_CHANGED"):
            self.validate()
        with self.assertRaisesRegex(PlanError, "BASE_REF_CHANGED"):
            self.build(plan)

    def test_planning_files_must_exist_and_contain_material_at_pinned_commit(self):
        data = copy.deepcopy(self.payload)
        data["package"]["planning_paths"] = ["docs/MISSING.md"]
        (self.repo / "docs/MISSING.md").write_text("Uncommitted is not a contract")
        with self.assertRaisesRegex(PlanError, "PLANNING_CONTRACT_UNREADABLE"):
            self.validate(data)
        (self.repo / "docs/PLAN.md").write_text("Uncommitted edits do not replace the pinned content")
        self.assertEqual(self.validate().state, "PREPARED")

    def test_unsafe_paths_and_product_control_plane_scope_expansion_are_rejected(self):
        for path in ("../escape", "/tmp/escape", "src/*.tsx", "src//file.ts", "src/./file.ts",
                     "src/../file.ts", "src/file.ts\nignored", "src/$(secret).ts", ".env", ".git/config",
                     "scripts/runner/runner.py", "scripts/factory_registry/sqlite_registry.py",
                     "AGENTS.md", "docs/NORTH_STAR.md", "docs/ARCHITECTURE.md"):
            data = copy.deepcopy(self.payload)
            data["package"]["new_paths"] = [path]
            with self.subTest(path=path), self.assertRaises(PlanError):
                self.validate(data)

    def test_missing_owned_paths_existing_new_collision_and_unowned_wiring_fail(self):
        for field, value, reason in (
            ("existing_paths", ["src/App.tsx", "tests/ideas.test.ts", "src/MISSING.ts"], "EXISTING_PATH_MISSING"),
            ("new_paths", ["src/App.tsx"], "PATH_DECLARATION_MISMATCH"),
            ("new_paths", ["docs/PLAN.md"], "NEW_PATH_ALREADY_EXISTS"),
            ("integration_paths", ["src/not-owned.ts"], "INTEGRATION_OR_TEST_UNOWNED"),
            ("test_paths", [], "list required"),
            ("persistence_owner", "src/storage.ts", "PERSISTENCE_OWNER_UNOWNED"),
        ):
            data = copy.deepcopy(self.payload)
            data["package"][field] = value
            with self.subTest(field=field, value=value), self.assertRaisesRegex(PlanError, reason):
                self.validate(data)

    def test_symlink_planning_or_existing_files_are_not_usable_inputs(self):
        (self.repo / "docs/link.md").symlink_to("PLAN.md")
        self.git("add", "docs/link.md")
        self.git("-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "link")
        data = copy.deepcopy(self.payload)
        data["base_commit"] = self.git("rev-parse", "HEAD").strip()
        data["package"]["planning_paths"] = ["docs/link.md"]
        with self.assertRaisesRegex(PlanError, "PLANNING_CONTRACT_UNREADABLE"):
            self.validate(data)

    def test_declared_new_tests_are_permitted_without_an_existing_test_file(self):
        data = copy.deepcopy(self.payload)
        data["package"]["new_paths"].append("tests/ideaSearch.test.ts")
        data["package"]["test_paths"] = ["tests/ideaSearch.test.ts"]
        self.assertEqual(self.validate(data).state, "PREPARED")

    def test_new_path_cannot_descend_through_a_tracked_symlink_or_regular_file(self):
        (self.repo / "src/link").symlink_to("/tmp")
        self.git("add", "src/link")
        self.git("-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "link")
        for path in ("src/link/escape.ts", "src/ideas.ts/impossible.ts"):
            data = copy.deepcopy(self.payload)
            data["base_commit"] = self.git("rev-parse", "HEAD").strip()
            data["package"]["new_paths"] = [path]
            with self.subTest(path=path), self.assertRaisesRegex(PlanError, "PATH_ANCESTOR_NOT_DIRECTORY"):
                self.validate(data)

    def test_invalid_package_identity_and_capacity_never_become_dispatchable(self):
        for impl, review in ((True, 502), (501, 501), (0, 502), (501, -1)):
            with self.subTest(impl=impl, review=review), self.assertRaises(PlanError):
                build_packages(self.validate(), repository=self.repo, target_ref="main",
                               implementation_issue=impl, review_issue=review)
        for field, value in (("capacity_size", "TINY"), ("capacity_size", {}),
                             ("capacity_risk", "EMERGENCY_RECOVERY"), ("capacity_risk", []),
                             ("required_capabilities", [])):
            data = copy.deepcopy(self.payload)
            data["package"][field] = value
            with self.subTest(field=field), self.assertRaises(PlanError):
                self.validate(data)

    def test_registry_pair_binding_is_pure_and_accepts_the_exact_saved_plan(self):
        plan = self.validate()
        pair = self.build(plan)
        with patch("scripts.factory_registry.delivery_plan.subprocess.run", side_effect=AssertionError("no Git in transaction")):
            validate_prepared_pair(plan.as_dict(), brief=self.brief, implementation=pair.implementation,
                                   review=pair.review, target_ref="main")

    def test_registry_pair_binding_rejects_a_valid_pair_for_different_owner_intent(self):
        other_brief = FeatureBrief.from_dict({**self.owner, "user_experience": "I want to export every idea."})
        other_payload = {**self.payload, "user_experience": other_brief.user_experience}
        other_pair = self.build(self.validate(other_payload, other_brief))
        with self.assertRaisesRegex(PlanError, "PACKAGE_PLAN_CONTRACT_MISMATCH"):
            validate_prepared_pair(self.payload, brief=self.brief, implementation=other_pair.implementation,
                                   review=other_pair.review, target_ref="main")

    def test_registry_pair_binding_rejects_forged_diagnostics_and_semantic_fields(self):
        pair = self.build()
        cases = [replace(pair.implementation, title="Different work"),
                 replace(pair.implementation, lane=Lane.PLATFORM),
                 replace(pair.implementation, required_capabilities=("anything",)),
                 replace(pair.implementation, acceptance_criteria=("Locally correct only",)),
                 replace(pair.implementation, branch="main"),
                 replace(pair.implementation, status=TaskStatus.READY)]
        for key, value in (("exclusive_paths", ["src/unrelated.ts"]), ("github_source_ref", "999"),
                           ("owner_request_sha256", "a" * 64), ("delivery_plan_sha256", "a" * 64),
                           ("persistence_owner", "src/unrelated.ts"), ("queue_contract_sha256", "a" * 64),
                           ("owner_request", {**self.owner, "user_experience": "Different work"})):
            cases.append(replace(pair.implementation, provider_diagnostics={**pair.implementation.provider_diagnostics, key: value}))
        for changed in cases:
            with self.subTest(changed=changed), self.assertRaises(PlanError):
                validate_prepared_pair(self.payload, brief=self.brief, implementation=changed,
                                       review=pair.review, target_ref="main")

    def test_registry_pair_binding_rejects_different_instructions_with_valid_proof(self):
        payload = copy.deepcopy(self.payload)
        payload["package"]["instructions"] = "Change the filtering API in a different way."
        other_pair = self.build(self.validate(payload))
        with self.assertRaisesRegex(PlanError, "PACKAGE_PLAN_CONTRACT_MISMATCH"):
            validate_prepared_pair(self.payload, brief=self.brief, implementation=other_pair.implementation,
                                   review=other_pair.review, target_ref="main")

    def test_registry_pair_binding_cannot_swap_review_target_or_planning_proof(self):
        pair = self.build()
        diagnostics = copy.deepcopy(pair.review.provider_diagnostics)
        diagnostics["readiness_proof"]["planning_sha256"]["docs/PLAN.md"] = "b" * 64
        changed = replace(pair.review, provider_diagnostics=diagnostics)
        with self.assertRaisesRegex(PlanError, "PLANNING_PROOF_MISMATCH"):
            validate_prepared_pair(self.payload, brief=self.brief, implementation=pair.implementation,
                                   review=changed, target_ref="main")
        with self.assertRaisesRegex(PlanError, "PACKAGE_PLAN_FIELDS_MISMATCH"):
            validate_prepared_pair(self.payload, brief=self.brief, implementation=pair.implementation,
                                   review=replace(pair.review, dependency_ids=("TASK-999",)), target_ref="main")


if __name__ == "__main__":
    unittest.main()
