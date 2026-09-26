import json
import unittest
from types import SimpleNamespace

from review_protocol import (
    ReviewBlockedError,
    ReviewProtocolError,
    parse_review_verdict,
)


class ReviewProtocolTests(unittest.TestCase):
    def setUp(self):
        self.review_input = SimpleNamespace(
            implementation_commit="a" * 40,
            evidence_id="review-input:attempt-review",
        )

    def verdict(self, **changes):
        value = {
            "schema_version": 1,
            "decision": "APPROVED",
            "findings": ["The contract is satisfied."],
            "changes_requested": [],
            "reviewed_commit": "a" * 40,
            "review_input_evidence_id": "review-input:attempt-review",
        }
        value.update(changes)
        return json.dumps(value)

    def test_accepts_only_exact_structured_verdict(self):
        verdict = parse_review_verdict(self.verdict(), self.review_input)
        self.assertEqual(verdict.decision, "APPROVED")
        self.assertEqual(verdict.reviewed_commit, "a" * 40)

    def test_rejects_wrong_commit_and_wrong_review_input(self):
        for changes, message in (
            ({"reviewed_commit": "b" * 40}, "wrong commit"),
            ({"review_input_evidence_id": "review-input:other"}, "wrong review input"),
        ):
            with self.subTest(changes=changes):
                with self.assertRaisesRegex(ReviewProtocolError, message):
                    parse_review_verdict(self.verdict(**changes), self.review_input)

    def test_rejects_unparseable_blocked_and_invalid_decisions(self):
        for output in (
            "provider unavailable",
            "```json\n{}\n```",
            self.verdict(decision="BLOCKED"),
            self.verdict(extra="not allowed"),
        ):
            with self.subTest(output=output):
                with self.assertRaises(ReviewProtocolError):
                    parse_review_verdict(output, self.review_input)

    def test_reports_blocked_inspection_separately_from_a_verdict(self):
        with self.assertRaisesRegex(ReviewBlockedError, "contract is missing"):
            parse_review_verdict(json.dumps({
                "schema_version": 1,
                "attempt_outcome": "BLOCKED",
                "detail": "contract is missing",
            }), self.review_input)

    def test_changes_requested_requires_specific_change(self):
        with self.assertRaisesRegex(ReviewProtocolError, "specific change"):
            parse_review_verdict(
                self.verdict(decision="CHANGES_REQUESTED"), self.review_input
            )
        verdict = parse_review_verdict(
            self.verdict(
                decision="CHANGES_REQUESTED",
                changes_requested=["Fix the exact-SHA comparison."],
            ),
            self.review_input,
        )
        self.assertEqual(verdict.decision, "CHANGES_REQUESTED")


if __name__ == "__main__":
    unittest.main()
