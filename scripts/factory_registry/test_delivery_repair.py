from pathlib import Path
import subprocess
import tempfile
import unittest

from scripts.factory_registry.delivery_repair import CorrectionError, materialize_correction


class DeliveryRepairTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.repo = Path(temporary.name)
        self.git("init", "-q")
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.invalid")
        self.git("checkout", "-qb", "main")
        (self.repo / "src").mkdir()
        (self.repo / "src/App.tsx").write_text("existing application\n")
        (self.repo / ".gitignore").write_text("ignored.bin\nlocal-only\n")
        self.commit("base")
        self.base = self.git("rev-parse", "HEAD")
        self.git("checkout", "-qb", "codex/rejected")
        (self.repo / "src/App.tsx").write_text("application wired to feature\n")
        (self.repo / "src/nested").mkdir()
        (self.repo / "src/nested/feature.ts").write_text("complete rejected behavior\n")
        (self.repo / "src/icon.bin").write_bytes(b"\0binary feature\xff\x01")
        self.commit("rejected implementation")
        self.implementation = self.git("rev-parse", "HEAD")
        self.paths = ["src/App.tsx", "src/nested/feature.ts", "src/icon.bin"]
        self.binding = {
            "previous_package_id": "TASK-501", "review_id": "TASK-502", "outcome_id": "outcome-502",
            "implementation_commit": self.implementation, "base_commit": self.base,
            "paths": self.paths, "changes_requested": ["Handle empty input without losing the current selection."],
        }
        self.git("checkout", "-qb", "codex/correction", self.base)

    def git(self, *args):
        result = subprocess.run(["git", "-C", str(self.repo), *args], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def commit(self, message):
        self.git("add", ".")
        self.git("commit", "-qm", message)

    def apply(self, *, binding=None, allowed=None, current=None):
        return materialize_correction(self.repo, current or self.git("rev-parse", "HEAD"),
                                      self.binding if binding is None else binding,
                                      self.paths if allowed is None else allowed)

    def snapshot(self):
        return self.git("rev-parse", "HEAD"), self.git("status", "--porcelain"), self.git("diff", "--cached")

    def test_correction_starts_with_prior_complete_code_and_binary_without_commit(self):
        result = self.apply()
        self.assertEqual(result["state"], "APPLIED")
        self.assertEqual(result["implementation_commit"], self.implementation)
        self.assertEqual(result["implementation_base"], self.base)
        self.assertEqual(result["current_base_commit"], self.base)
        self.assertEqual(set(result["applied_paths"]), set(self.paths))
        self.assertEqual(set(result["staged_paths"]), set(self.paths))
        self.assertEqual(result["changes_requested"], self.binding["changes_requested"])
        self.assertEqual((self.repo / "src/nested/feature.ts").read_text(), "complete rejected behavior\n")
        self.assertEqual((self.repo / "src/icon.bin").read_bytes(), b"\0binary feature\xff\x01")
        self.assertEqual(self.git("rev-parse", "HEAD"), self.base)
        self.assertEqual(self.git("rev-parse", "main"), self.base)
        self.assertEqual(self.git("show", self.implementation + ":src/App.tsx"), "application wired to feature")
        self.assertEqual(self.git("diff", "--name-only"), "")

    def test_unrelated_integration_advancement_is_preserved_while_prior_patch_applies(self):
        (self.repo / "src/independent.ts").write_text("another approved feature\n")
        self.commit("independent integration")
        advanced = self.git("rev-parse", "HEAD")
        result = self.apply(current=advanced)
        self.assertEqual(result["current_base_commit"], advanced)
        self.assertEqual(self.git("rev-parse", "HEAD"), advanced)
        self.assertEqual((self.repo / "src/independent.ts").read_text(), "another approved feature\n")
        self.assertNotIn("src/independent.ts", result["staged_paths"])

    def test_conflicts_are_preserved_with_evidence_and_do_not_modify_main_or_previous_commit(self):
        (self.repo / "src/App.tsx").write_text("independent incompatible application wiring\n")
        self.commit("integration changes same line")
        advanced = self.git("rev-parse", "HEAD")
        with self.assertRaisesRegex(CorrectionError, "REPAIR_APPLY_CONFLICT") as raised:
            self.apply(current=advanced)
        self.assertIn("src/App.tsx", raised.exception.evidence["conflicted_paths"])
        self.assertTrue(self.git("ls-files", "--unmerged"))
        self.assertEqual(self.git("rev-parse", "HEAD"), advanced)
        self.assertEqual(self.git("rev-parse", "main"), self.base)
        self.assertEqual(self.git("rev-parse", "codex/rejected"), self.implementation)

    def test_dirty_tracked_staged_and_untracked_checkout_fail_without_further_mutation(self):
        for kind in ("tracked", "staged", "untracked"):
            with self.subTest(kind=kind):
                if kind == "tracked":
                    (self.repo / "src/App.tsx").write_text("local work\n")
                elif kind == "staged":
                    self.git("add", "src/App.tsx")
                else:
                    (self.repo / "local.txt").write_text("local work\n")
                before = self.snapshot()
                with self.assertRaisesRegex(CorrectionError, "REPAIR_WORKTREE_NOT_CLEAN"):
                    self.apply()
                self.assertEqual(self.snapshot(), before)

    def test_malformed_binding_and_unowned_diff_fail_without_worktree_mutation(self):
        before = self.snapshot()
        cases = [{**self.binding, "paths": ["src/App.tsx"]},
                 {**self.binding, "paths": ["../escape.ts"]},
                 {**self.binding, "paths": ["src/*.tsx"]},
                 {**self.binding, "changes_requested": []},
                 {**self.binding, "implementation_commit": "HEAD"},
                 {**self.binding, "command": ["run"]},
                 {**self.binding, "review_id": "TASK-501"}]
        for binding in cases:
            with self.subTest(binding=binding), self.assertRaises(CorrectionError):
                self.apply(binding=binding)
            self.assertEqual(self.snapshot(), before)
        with self.assertRaisesRegex(CorrectionError, "REPAIR_PATH_OWNERSHIP_MISMATCH"):
            self.apply(allowed=["src/App.tsx"])
        self.assertEqual(self.snapshot(), before)

    def test_wrong_head_parent_missing_commit_and_main_checkout_are_rejected(self):
        before = self.snapshot()
        with self.assertRaisesRegex(CorrectionError, "REPAIR_CURRENT_BASE_MISMATCH"):
            self.apply(current=self.implementation)
        with self.assertRaisesRegex(CorrectionError, "REPAIR_IMPLEMENTATION_PARENT_MISMATCH"):
            self.apply(binding={**self.binding, "base_commit": self.implementation})
        with self.assertRaises(CorrectionError):
            self.apply(binding={**self.binding, "implementation_commit": "f" * 40})
        self.assertEqual(self.snapshot(), before)
        self.git("checkout", "-q", "main")
        with self.assertRaisesRegex(CorrectionError, "REPAIR_MAIN_CHECKOUT_FORBIDDEN"):
            self.apply()
        self.assertEqual(self.git("status", "--porcelain"), "")

    def test_detached_worker_checkout_is_supported(self):
        self.git("checkout", "-q", "--detach", self.base)
        self.assertEqual(self.apply()["state"], "APPLIED")

    def test_current_base_symlink_ancestor_is_rejected_before_apply(self):
        (self.repo / "src/nested").symlink_to("/tmp")
        self.commit("unusable ancestor")
        before = self.snapshot()
        with self.assertRaisesRegex(CorrectionError, "REPAIR_UNSAFE_PATH_ANCESTOR"):
            self.apply()
        self.assertEqual(self.snapshot(), before)

    def test_rejected_patch_cannot_introduce_symlink(self):
        self.git("checkout", "-qb", "codex/symlink-implementation", self.base)
        (self.repo / "src/nested").symlink_to("/tmp")
        self.commit("symlink implementation")
        symlink_commit = self.git("rev-parse", "HEAD")
        self.git("checkout", "-q", "codex/correction")
        before = self.snapshot()
        with self.assertRaisesRegex(CorrectionError, "REPAIR_NONREGULAR_PATH"):
            self.apply(binding={**self.binding, "implementation_commit": symlink_commit,
                                "paths": ["src/nested"]}, allowed=["src/nested"])
        self.assertEqual(self.snapshot(), before)

    def test_ignored_destination_cannot_be_overwritten(self):
        # The prior implementation owns a new path ignored by the current base.
        self.git("checkout", "-qb", "codex/ignored-implementation", self.base)
        (self.repo / "ignored.bin").write_bytes(b"previous implementation")
        self.git("add", "-f", "ignored.bin")
        self.git("commit", "-qm", "ignored file implementation")
        previous = self.git("rev-parse", "HEAD")
        self.git("checkout", "-q", "codex/correction")
        (self.repo / "ignored.bin").write_bytes(b"local ignored content")
        before = self.snapshot()
        with self.assertRaisesRegex(CorrectionError, "REPAIR_UNTRACKED_DESTINATION"):
            self.apply(binding={**self.binding, "implementation_commit": previous,
                                "paths": ["ignored.bin"]}, allowed=["ignored.bin"])
        self.assertEqual((self.repo / "ignored.bin").read_bytes(), b"local ignored content")
        self.assertEqual(self.snapshot(), before)

    def test_ignored_symlink_ancestor_cannot_escape_checkout(self):
        self.git("checkout", "-qb", "codex/local-implementation", self.base)
        (self.repo / "local-only").mkdir()
        (self.repo / "local-only/file.ts").write_text("owned feature")
        self.git("add", "-f", "local-only/file.ts")
        self.git("commit", "-qm", "local implementation")
        previous = self.git("rev-parse", "HEAD")
        self.git("checkout", "-q", "codex/correction")
        (self.repo / "local-only").symlink_to("/tmp")
        before = self.snapshot()
        with self.assertRaisesRegex(CorrectionError, "REPAIR_UNSAFE_WORKTREE_PATH"):
            self.apply(binding={**self.binding, "implementation_commit": previous,
                                "paths": ["local-only/file.ts"]}, allowed=["local-only/file.ts"])
        self.assertEqual(self.snapshot(), before)

    def test_replay_does_not_reapply_patch_or_commit(self):
        self.apply()
        before = self.snapshot()
        with self.assertRaisesRegex(CorrectionError, "REPAIR_WORKTREE_NOT_CLEAN"):
            self.apply()
        self.assertEqual(self.snapshot(), before)


if __name__ == "__main__":
    unittest.main()
