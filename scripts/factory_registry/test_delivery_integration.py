from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import fcntl
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts.factory_registry.delivery_integration import (
    ApprovalBinding, IntegrationError, IntegrationPolicy, prepare_integration, publish_integration,
)


class DeliveryIntegrationTests(unittest.TestCase):
    """Real Git repositories exercise remote CAS and crash replay, without GitHub."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.remote = self.root / "remote.git"
        self.repo = self.root / "repo"
        self.git(self.root, "init", "--bare", str(self.remote))
        self.git(self.root, "clone", str(self.remote), str(self.repo))
        self.git(self.repo, "config", "user.name", "Test author")
        self.git(self.repo, "config", "user.email", "author@example.invalid")
        self.git(self.repo, "checkout", "-b", "codex/delivery")
        (self.repo / "base.txt").write_text("base\n")
        self.git(self.repo, "add", ".")
        self.git(self.repo, "commit", "-m", "base")
        self.base = self.git(self.repo, "rev-parse", "HEAD")
        self.git(self.repo, "push", "origin", "codex/delivery")
        self.git(self.repo, "checkout", "-b", "codex/feature")
        (self.repo / "feature.txt").write_text("user-visible feature\n")
        self.git(self.repo, "add", ".")
        self.git(self.repo, "commit", "-m", "feature")
        self.implementation = self.git(self.repo, "rev-parse", "HEAD")
        self.approval = ApprovalBinding(
            feature_id="FEATURE-1", package_id="TASK-1", implementation_commit=self.implementation,
            implementation_base=self.base, contract_sha256="a" * 64,
            review_outcome_id="outcome-1", review_attempt_id="review-attempt-1",
            reviewer_worker_id="claude", implementer_worker_id="codex-b-child",
            reviewed_commit=self.implementation, reviewed_base_commit=self.base,
            pr_url="https://github.com/example/app/pull/123",
            reviewed_pr_url="https://github.com/example/app/pull/123",
            validation_commit=self.implementation, validation_evidence_ids=("validation-1",),
            review_input_evidence_id="review-input-1", approval_evidence_ids=("approval-1",),
        )
        self.policy = IntegrationPolicy(
            remote="origin", target_branch="codex/delivery",
            validation_commands=((sys.executable, "-c", "from pathlib import Path; "
                                  "assert Path('feature.txt').read_text() == 'user-visible feature\\n'"),),
        )

    @staticmethod
    def git(directory, *args):
        result = subprocess.run(["git", *args], cwd=directory, capture_output=True, text=True)
        if result.returncode:
            raise AssertionError(f"git {' '.join(args)}: {result.stderr}")
        return result.stdout.strip()

    def prepare(self, **kwargs):
        return prepare_integration(self.repo, kwargs.pop("approval", self.approval),
                                   kwargs.pop("policy", self.policy), expected_target_sha=kwargs.pop("expected", self.base),
                                   integration_id=kwargs.pop("integration_id", "integration-1"),
                                   workspace_parent=self.root, **kwargs)

    def remote_sha(self):
        return self.git(self.remote, "rev-parse", "refs/heads/codex/delivery")

    def move_target(self):
        self.git(self.repo, "checkout", "codex/delivery")
        (self.repo / "other.txt").write_text("independent work\n")
        self.git(self.repo, "add", ".")
        self.git(self.repo, "commit", "-m", "advance target")
        self.git(self.repo, "push", "origin", "codex/delivery")
        return self.git(self.repo, "rev-parse", "HEAD")

    def test_clean_candidate_and_publication_preserve_reviewed_artifact(self):
        receipt = self.prepare()
        self.assertEqual(self.remote_sha(), self.base)
        self.assertEqual(self.git(self.repo, "rev-parse", "HEAD"), self.implementation)
        parents = self.git(self.repo, "rev-list", "--parents", "-n", "1", receipt["target_after"]).split()[1:]
        self.assertEqual(parents, [self.base, self.implementation])
        self.assertEqual(receipt["validation"][0]["validated_commit"], receipt["target_after"])
        # Registry serialization must preserve the adapter's binding checks.
        persisted = json.loads(json.dumps(receipt))
        result = publish_integration(self.repo, persisted, self.approval, self.policy)
        self.assertEqual(result["state"], "PUBLISHED")
        self.assertEqual(self.remote_sha(), receipt["target_after"])
        self.assertEqual(self.git(self.remote, "show", "codex/delivery:feature.txt"), "user-visible feature")
        self.assertEqual(result["approval"]["reviewed_commit"], self.implementation)

    def test_wrong_review_or_provenance_prevents_even_preparation(self):
        for changed in (
            replace(self.approval, reviewed_commit=self.base),
            replace(self.approval, reviewed_base_commit=self.implementation),
            replace(self.approval, verdict="CHANGES_REQUESTED"),
            replace(self.approval, reviewer_worker_id=self.approval.implementer_worker_id),
            replace(self.approval, reviewed_pr_url="https://github.com/example/app/pull/124"),
            replace(self.approval, validation_commit=self.base),
            replace(self.approval, validation_evidence_ids=()),
            replace(self.approval, approval_evidence_ids=()),
        ):
            with self.subTest(changed=changed):
                with self.assertRaisesRegex(IntegrationError, "EXACT_INDEPENDENT_APPROVAL_REQUIRED"):
                    self.prepare(approval=changed)
                self.assertEqual(self.remote_sha(), self.base)

    def test_ambient_follow_tags_cannot_publish_additional_remote_refs(self):
        self.git(self.repo, "tag", "-a", "unapproved-release", "-m", "Not authorized for publication",
                 self.implementation)
        self.git(self.repo, "config", "push.followTags", "true")
        self.git(self.repo, "config", "push.recurseSubmodules", "on-demand")
        receipt = self.prepare()
        publish_integration(self.repo, receipt, self.approval, self.policy)
        refs = self.git(self.remote, "for-each-ref", "--format=%(refname)").splitlines()
        self.assertEqual(refs, ["refs/heads/codex/delivery"])
        self.assertEqual(self.remote_sha(), receipt["target_after"])

    def test_local_replace_refs_cannot_substitute_unreviewed_commit_content(self):
        self.git(self.repo, "checkout", "-b", "codex/unreviewed-replacement", self.base)
        (self.repo / "feature.txt").write_text("unreviewed replacement\n")
        self.git(self.repo, "add", ".")
        self.git(self.repo, "commit", "-m", "unreviewed tree")
        replacement = self.git(self.repo, "rev-parse", "HEAD")
        self.git(self.repo, "replace", self.implementation, replacement)
        # Prove ordinary Git is now seeing the substituted object under the
        # original approved identity, before exercising the hardened adapter.
        self.assertEqual(self.git(self.repo, "show", self.implementation + ":feature.txt"),
                         "unreviewed replacement")
        receipt = self.prepare()
        publish_integration(self.repo, receipt, self.approval, self.policy)
        self.assertEqual(self.git(self.remote, "show", "codex/delivery:feature.txt"), "user-visible feature")

    def test_changed_target_rejects_candidate_and_repreparation_validates_new_merge(self):
        receipt = self.prepare()
        moved = self.move_target()
        with self.assertRaisesRegex(IntegrationError, "TARGET_MOVED"):
            publish_integration(self.repo, receipt, self.approval, self.policy)
        with self.assertRaisesRegex(IntegrationError, "TARGET_MOVED"):
            self.prepare()
        next_receipt = self.prepare(expected=moved, integration_id="integration-2")
        self.assertEqual(next_receipt["target_before"], moved)
        publish_integration(self.repo, next_receipt, self.approval, self.policy)
        self.assertEqual(self.git(self.remote, "show", "codex/delivery:other.txt"), "independent work")

    def test_failed_validation_preserves_evidence_without_publishing(self):
        failing = replace(self.policy, validation_commands=((sys.executable, "-c", "print('finding'); exit(3)"),))
        with self.assertRaisesRegex(IntegrationError, "INTEGRATION_VALIDATION_FAILED") as caught:
            self.prepare(policy=failing)
        self.assertTrue(Path(caught.exception.evidence["workspace"]).exists())
        self.assertEqual(caught.exception.evidence["validation"][0]["returncode"], 3)
        self.assertIn("finding", caught.exception.evidence["validation"][0]["stdout"])
        self.assertEqual(self.remote_sha(), self.base)

    def test_validation_cannot_change_the_artifact_it_claims_to_validate(self):
        changing = replace(self.policy, validation_commands=((sys.executable, "-c", "from pathlib import Path; "
                                                               "Path('feature.txt').write_text('changed')"),))
        with self.assertRaisesRegex(IntegrationError, "VALIDATION_CHANGED_ARTIFACT"):
            self.prepare(policy=changing)
        self.assertEqual(self.remote_sha(), self.base)

    def test_merge_conflict_is_retained_and_has_no_target_side_effect(self):
        self.git(self.repo, "checkout", "-b", "codex/conflict", self.base)
        (self.repo / "base.txt").write_text("feature edit\n")
        self.git(self.repo, "add", ".")
        self.git(self.repo, "commit", "-m", "feature conflict")
        implementation = self.git(self.repo, "rev-parse", "HEAD")
        self.git(self.repo, "checkout", "codex/delivery")
        (self.repo / "base.txt").write_text("target edit\n")
        self.git(self.repo, "add", ".")
        self.git(self.repo, "commit", "-m", "target conflict")
        target = self.git(self.repo, "rev-parse", "HEAD")
        self.git(self.repo, "push", "origin", "codex/delivery")
        approval = replace(self.approval, implementation_commit=implementation, reviewed_commit=implementation,
                           validation_commit=implementation)
        with self.assertRaisesRegex(IntegrationError, "INTEGRATION_MERGE_FAILED") as caught:
            self.prepare(approval=approval, expected=target)
        self.assertEqual(caught.exception.evidence["conflicted_paths"], ["base.txt"])
        self.assertEqual(self.remote_sha(), target)

    def test_replay_after_push_before_registry_recording_never_pushes_twice(self):
        receipt = self.prepare()
        first = publish_integration(self.repo, receipt, self.approval, self.policy)
        # Simulate the coordinator dying before recording the returned receipt.
        second = publish_integration(self.repo, receipt, self.approval, self.policy,
                                     before_publish=lambda: self.fail("replay must not mutate"))
        self.assertEqual(second["state"], "ALREADY_PUBLISHED")
        self.assertEqual(first["target_after"], second["target_after"])
        self.assertEqual(self.remote_sha(), receipt["target_after"])

    def test_uncertain_transport_after_success_is_reconciled_from_remote(self):
        from scripts.factory_registry import delivery_integration as adapter
        receipt = self.prepare()
        original = adapter._git
        def lost_response(repo, policy, *args, **kwargs):
            result = original(repo, policy, *args, **kwargs)
            if args[0] == "push":
                return {**result, "returncode": 128, "stderr": "connection lost after server update"}
            return result
        with patch.object(adapter, "_git", side_effect=lost_response):
            result = publish_integration(self.repo, receipt, self.approval, self.policy)
        self.assertEqual(result["state"], "PUBLISHED")
        self.assertEqual(result["push"]["returncode"], 128)

    def test_lost_post_push_observation_is_uncertain_until_replay(self):
        from scripts.factory_registry import delivery_integration as adapter
        receipt = self.prepare()
        original = adapter._fetch_head
        observations = []
        def lose_after_push(*args):
            observations.append(True)
            if len(observations) == 2:
                raise IntegrationError("GIT_OPERATION_FAILED", {"stderr": "network unavailable"})
            return original(*args)
        with patch.object(adapter, "_fetch_head", side_effect=lose_after_push):
            with self.assertRaisesRegex(IntegrationError, "PUBLICATION_UNCERTAIN"):
                publish_integration(self.repo, receipt, self.approval, self.policy)
        self.assertEqual(self.remote_sha(), receipt["target_after"])
        result = publish_integration(self.repo, receipt, self.approval, self.policy)
        self.assertEqual(result["state"], "ALREADY_PUBLISHED")

    def test_timeout_returns_failed_validation_and_preserves_target(self):
        timeout = replace(self.policy, validation_timeout_seconds=1,
                          validation_commands=((sys.executable, "-c", "import time; time.sleep(10)"),))
        with self.assertRaisesRegex(IntegrationError, "INTEGRATION_VALIDATION_FAILED") as caught:
            self.prepare(policy=timeout)
        self.assertTrue(caught.exception.evidence["validation"][0]["timed_out"])
        self.assertEqual(self.remote_sha(), self.base)

    def test_two_concurrent_candidates_have_one_winner_and_no_history_rewrite(self):
        first, second = self.prepare(), self.prepare(integration_id="integration-2")
        def publish(candidate):
            try:
                return publish_integration(self.repo, candidate, self.approval, self.policy)["state"]
            except IntegrationError as error:
                return error.code
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(publish, (first, second)))
        self.assertCountEqual(outcomes, ["PUBLISHED", "TARGET_MOVED"])
        self.assertIn(self.remote_sha(), (first["target_after"], second["target_after"]))
        self.assertEqual(self.git(self.remote, "rev-parse", "codex/delivery^1"), self.base)

    def test_race_after_remote_observation_is_rejected_by_exact_lease(self):
        receipt = self.prepare()
        moved = []
        def move_immediately_before_push():
            moved.append(self.move_target())
        with self.assertRaisesRegex(IntegrationError, "TARGET_MOVED"):
            publish_integration(self.repo, receipt, self.approval, self.policy,
                                before_publish=move_immediately_before_push)
        self.assertEqual(self.remote_sha(), moved[0])

    def test_authoritative_run_guard_can_block_publication(self):
        receipt = self.prepare()
        def paused():
            raise IntegrationError("FACTORY_PAUSED")
        with self.assertRaisesRegex(IntegrationError, "FACTORY_PAUSED"):
            publish_integration(self.repo, receipt, self.approval, self.policy, before_publish=paused)
        self.assertEqual(self.remote_sha(), self.base)

    def test_suspended_publisher_cannot_hold_second_coordinator_indefinitely(self):
        policy = replace(self.policy, git_timeout_seconds=1)
        receipt = self.prepare(policy=policy)
        with (self.repo / ".git/factory-integration.lock").open("a") as held_lock:
            fcntl.flock(held_lock, fcntl.LOCK_EX)
            with self.assertRaisesRegex(IntegrationError, "INTEGRATION_BUSY"):
                publish_integration(self.repo, receipt, self.approval, policy)
        self.assertEqual(self.remote_sha(), self.base)

    def test_main_requires_both_operator_and_repository_authorization(self):
        for flags in ({}, {"allow_main": True}, {"repository_policy_allows_main": True}):
            with self.subTest(flags=flags):
                with self.assertRaisesRegex(IntegrationError, "MAIN_INTEGRATION_NOT_AUTHORIZED"):
                    self.prepare(policy=replace(self.policy, target_branch="main", **flags))

    def test_receipt_policy_or_remote_change_is_rejected(self):
        receipt = self.prepare()
        altered = {**receipt, "target_after": self.implementation}
        with self.assertRaisesRegex(IntegrationError, "CANDIDATE_BINDING_MISMATCH"):
            publish_integration(self.repo, altered, self.approval, self.policy)
        changed_policy = replace(self.policy, validation_commands=((sys.executable, "-c", "pass"),))
        with self.assertRaisesRegex(IntegrationError, "CANDIDATE_BINDING_MISMATCH"):
            publish_integration(self.repo, receipt, self.approval, changed_policy)
        self.git(self.repo, "remote", "set-url", "--push", "origin", str(self.root / "other.git"))
        with self.assertRaisesRegex(IntegrationError, "CANDIDATE_BINDING_MISMATCH"):
            publish_integration(self.repo, receipt, self.approval, self.policy)


if __name__ == "__main__":
    unittest.main()
