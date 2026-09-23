import json
import pathlib
import sys
import tempfile
import unittest

from review_queue import packet_for, reviewer_for, main


class ReviewQueueTests(unittest.TestCase):
    def record(self, **changes):
        value = {"issue": 7, "status": "review", "agent": "codex-b",
                 "commit": "abcdef1234567", "pr": "https://github.com/o/r/pull/8"}
        value.update(changes)
        return value

    def test_routing(self):
        self.assertEqual(reviewer_for("codex-a"), "claude")
        self.assertEqual(reviewer_for("codex-b"), "claude")
        self.assertEqual(reviewer_for("claude"), "codex-a")

    def test_no_author_as_reviewer(self):
        packet = packet_for(self.record(agent="claude"), pathlib.Path("issue-7.json"))
        self.assertNotEqual(packet["authored_by"], packet["reviewer"])

    def test_missing_data_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "PR URL"):
            packet_for(self.record(pr=None), pathlib.Path("issue-7.json"))
        with self.assertRaisesRegex(ValueError, "commit"):
            packet_for(self.record(commit=""), pathlib.Path("issue-7.json"))

    def test_once_suppresses_duplicate_commit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            state = root / "state"
            state.mkdir()
            record = state / "issue-7.json"
            record.write_text(json.dumps(self.record()))
            config = root / "config.json"
            config.write_text(json.dumps({"state": str(state), "reviewers": {
                "claude": {"command": [sys.executable, "-c", "import sys; sys.stdin.read()"],
                            "read_only": True}}}))
            main(["--config", str(config), "--once"])
            first = state / "review-7-abcdef1234567.json"
            self.assertTrue(first.exists())
            first_mtime = first.stat().st_mtime_ns
            main(["--config", str(config), "--once"])
            self.assertEqual(first.stat().st_mtime_ns, first_mtime)


if __name__ == "__main__":
    unittest.main()
