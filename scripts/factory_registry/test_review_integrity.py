from __future__ import annotations
import json, pathlib, sys, unittest
ROOT = pathlib.Path(__file__).resolve().parents[2]
RUNNER = ROOT / "scripts" / "runner"
if str(RUNNER) not in sys.path: sys.path.insert(0, str(RUNNER))
from scripts.factory_registry.models import ReviewInput, ReviewOutcomeState
from review_protocol import ReviewProtocolError, contract_digest, parse_review_verdict, review_handoff
class ReviewIntegrityProtocolTests(unittest.TestCase):
    def setUp(self):
        self.commit, self.base, self.contract = "a" * 40, "b" * 40, {"task": "TÄSK-1", "paths": ["scripts/example.py"]}
        self.input = ReviewInput(id="review-input-1", review_package_id="TASK-2", target_package_id="TASK-1", implementation_attempt_id="implementation-attempt", implementation_commit=self.commit, base_commit=self.base, pr_url="https://example.invalid/pr/1", contract_sha256=contract_digest(self.contract), contract=self.contract, validation_evidence={"repository_validation": "passed"}, recorded_at="2026-09-26T12:00:00Z")
    def verdict(self, **changes):
        value = {"state": "APPROVED", "reviewed_commit": self.commit, "reviewed_base_commit": self.base, "contract_sha256": self.input.contract_sha256, "findings": ["Reviewed exact target."], "changes_requested": []}; value.update(changes); return json.dumps(value)
    def test_handoff_contains_contract_and_exact_target(self):
        handoff = json.loads(review_handoff(self.input, reviewer_worker_id="reviewer", review_attempt_id="attempt")); self.assertEqual(handoff["implementation_commit"], self.commit); self.assertEqual(handoff["contract"], self.contract)
    def test_approval_requires_exact_commit_base_and_contract(self):
        self.assertEqual(parse_review_verdict(self.verdict(), self.input).state, ReviewOutcomeState.APPROVED)
        for field, value in (("reviewed_commit", "c" * 40), ("reviewed_base_commit", "d" * 40), ("contract_sha256", "e" * 64)):
            with self.subTest(field=field):
                with self.assertRaisesRegex(ReviewProtocolError, "different implementation input"): parse_review_verdict(self.verdict(**{field: value}), self.input)
    def test_unparseable_or_blocked_provider_output_is_not_approval(self):
        with self.assertRaisesRegex(ReviewProtocolError, "unparseable"): parse_review_verdict("provider unavailable", self.input)
        with self.assertRaisesRegex(ReviewProtocolError, "changes-requested"): parse_review_verdict(self.verdict(state="CHANGES_REQUESTED"), self.input)
    def test_verdict_schema_rejects_extra_provider_text(self):
        with self.assertRaisesRegex(ReviewProtocolError, "schema"): parse_review_verdict(self.verdict(extra="not allowed"), self.input)
