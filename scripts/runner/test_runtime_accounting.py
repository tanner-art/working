import json
import tempfile
import unittest
from pathlib import Path

from scripts.runner.runtime_accounting import collect_events, report

class RuntimeAccountingTest(unittest.TestCase):
    def test_clips_unions_and_keeps_children_additive(self):
        events = [
            {"kind":"session_started","at":"2026-01-01T00:00:00Z","session_id":"root","attempt_kind":"implementation"},
            {"kind":"session_completed","at":"2026-01-01T00:10:00Z","session_id":"root"},
            {"kind":"session_started","at":"2026-01-01T00:05:00Z","session_id":"child","parent_session_id":"root","attempt_kind":"review"},
            {"kind":"session_completed","at":"2026-01-01T00:12:00Z","session_id":"child","parent_session_id":"root"},
            {"kind":"wait_started","at":"2026-01-01T00:03:00Z","session_id":"coordinator-1"},
            {"kind":"wait_complete","at":"2026-01-01T00:06:00Z","session_id":"coordinator-1"},
        ]
        result = report(events, start="2026-01-01T00:02:00Z", end="2026-01-01T00:11:00Z")
        self.assertEqual(result["parentAttemptSeconds"], 480)
        self.assertEqual(result["parentUnionSeconds"], 480)
        self.assertEqual(result["knownAdditiveChildSeconds"], 360)
        self.assertEqual(result["implementationSeconds"], 480)
        self.assertEqual(result["reviewSeconds"], 360)
        self.assertEqual(result["identifiableWaitSeconds"], 180)
        self.assertEqual(result["noAttemptSeconds"], 60)

    def test_collector_deduplicates_replayed_events_and_ignores_prompt(self):
        row = {"kind":"session_started","at":"2026-01-01T00:00:00Z","session_id":"root","prompt":"secret"}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "provided.jsonl"; path.write_text("\n".join([json.dumps(row), json.dumps(row)]))
            events = collect_events([path])
        self.assertEqual(events, [{"kind":"session_started","at":"2026-01-01T00:00:00Z","session_id":"root"}])

    def test_wrapper_and_provider_observations_share_an_invocation_identity(self):
        rows = [
            {"kind":"session_started","at":"2026-01-01T00:00:00Z","session_id":"wrapper","invocation_id":"invoke-1"},
            {"kind":"session_started","at":"2026-01-01T00:00:00Z","session_id":"provider","invocation_id":"invoke-1"},
            {"kind":"session_completed","at":"2026-01-01T00:01:00Z","session_id":"provider","invocation_id":"invoke-1"},
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "provided.jsonl"; path.write_text("\n".join(json.dumps(row) for row in rows))
            result = report(collect_events([path]), start="2026-01-01T00:00:00Z", end="2026-01-01T00:02:00Z")
        self.assertEqual(result["parentAttemptSeconds"], 60)

    def test_open_intervals_and_missing_children_are_unknown(self):
        result = report([{"kind":"task_started","at":"2026-01-01T00:00:00Z","session_id":"root"}], start="2026-01-01T00:00:00Z", end="2026-01-01T01:00:00Z")
        self.assertEqual(result["parentUnionSeconds"], 0)
        self.assertEqual(result["childTelemetry"], "unknown_or_disabled")

if __name__ == "__main__": unittest.main()
