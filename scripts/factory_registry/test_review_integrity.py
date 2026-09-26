from __future__ import annotations
import json, pathlib, sys, unittest
ROOT = pathlib.Path(__file__).resolve().parents[2]
RUNNER = ROOT / "scripts" / "runner"
if str(RUNNER) not in sys.path: sys.path.insert(0, str(RUNNER))
from scripts.factory_registry.models import ReviewInput, ReviewOutcomeState
from scripts.factory_registry.sqlite_registry import _request_sha256, _review_contract_sha256
from registry_control import queue_contract_digest
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

    def test_successful_claude_json_envelope_is_normalized_but_errors_are_rejected(self):
        envelope = json.dumps({
            "type": "result", "is_error": False, "result": self.verdict(),
            "session_id": "diagnostic-only",
        })
        self.assertEqual(
            parse_review_verdict(envelope, self.input).state,
            ReviewOutcomeState.APPROVED,
        )
        for value in (
            {"type": "result", "is_error": True, "result": self.verdict()},
            {"type": "assistant", "is_error": False, "result": self.verdict()},
            {"type": "result", "is_error": False, "result": "prose"},
            {"type": "result", "is_error": False, "subtype": "error_during_execution", "result": self.verdict()},
            {"type": "result", "is_error": False, "error": {"message": "no"}, "result": self.verdict()},
        ):
            with self.subTest(value=value["type"]):
                with self.assertRaises(ReviewProtocolError):
                    parse_review_verdict(json.dumps(value), self.input)

    def test_duplicate_keys_and_ambiguous_verdicts_are_rejected(self):
        duplicate_state = (
            '{"state":"APPROVED","state":"CHANGES_REQUESTED",'
            f'"reviewed_commit":"{self.commit}","reviewed_base_commit":"{self.base}",'
            f'"contract_sha256":"{self.input.contract_sha256}",'
            '"findings":[],"changes_requested":[]}'
        )
        duplicate_envelope = (
            '{"type":"result","is_error":false,"is_error":false,'
            + '"result":' + json.dumps(self.verdict()) + '}'
        )
        for value in (duplicate_state, duplicate_envelope):
            with self.subTest(value=value[:20]):
                with self.assertRaisesRegex(ReviewProtocolError, "duplicate JSON key"):
                    parse_review_verdict(value, self.input)

    def test_schema_output_is_authoritative_and_prose_is_never_salvaged(self):
        envelope = {"type": "result", "subtype": "success", "is_error": False,
            "result": "Review complete. See structured output.",
            "structured_output": json.loads(self.verdict())}
        self.assertEqual(parse_review_verdict(json.dumps(envelope), self.input).state,
                         ReviewOutcomeState.APPROVED)
        for invalid in (None, "APPROVED", {"state": "APPROVED"}):
            envelope['structured_output'] = invalid
            with self.assertRaises(ReviewProtocolError):
                parse_review_verdict(json.dumps(envelope), self.input)
        envelope.pop('structured_output')
        envelope['result'] = 'Review complete.\n```json\n' + self.verdict() + '\n```'
        with self.assertRaises(ReviewProtocolError):
            parse_review_verdict(json.dumps(envelope), self.input)

    def test_non_ascii_contract_digests_match_without_changing_receipt_digest(self):
        contract = {"task": "TÄSK-1", "instructions": "résumé ✅"}
        sqlite_review = _review_contract_sha256(contract)
        runner_queue = queue_contract_digest(contract)
        review_protocol = contract_digest(contract)
        self.assertEqual(sqlite_review, runner_queue)
        self.assertEqual(sqlite_review, review_protocol)
        escaped_receipt = json.dumps(contract, sort_keys=True, separators=(",", ":")).encode("utf-8")
        self.assertEqual(
            _request_sha256(contract),
            __import__("hashlib").sha256(escaped_receipt).hexdigest(),
        )
        self.assertNotEqual(_request_sha256(contract), sqlite_review)
