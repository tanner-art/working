from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.runner.runtime_accounting import collect, report


class RuntimeAccountingTest(unittest.TestCase):
    def test_actual_envelopes_are_sanitized_and_identity_deduplicated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "provider.jsonl"
            path.write_text(json.dumps({"type": "result", "session_id": "same", "invocation_id": "invoke-1", "timestamp": "2026-09-27T10:01:00Z", "duration_ms": 60000, "prompt": "secret", "environment": "secret"}) + "\n")
            events = collect([str(path)]) + collect([str(path)])
        self.assertNotIn("secret", json.dumps(events))
        result = report(events)
        self.assertEqual(result["eventCount"], 1)
        self.assertEqual(result["providerChildSeconds"], 60)

    def test_distinct_simultaneous_sessions_are_additive_not_deduplicated(self) -> None:
        result = report([
            {"source": "codex", "type": "turn.completed", "sessionId": "one", "invocationId": "one", "timestamp": "2026-09-27T10:01:00Z", "durationMs": 60000},
            {"source": "claude", "type": "result", "sessionId": "two", "invocationId": "two", "timestamp": "2026-09-27T10:01:00Z", "durationMs": 60000},
        ])
        self.assertEqual(result["providerChildSeconds"], 120)
        self.assertEqual(result["providerChildUnionSeconds"], 60)

    def test_repeated_coordinator_turn_is_deduplicated_and_not_worker_compute(self) -> None:
        turn = {"source": "coordinator", "type": "task_complete", "sessionId": "turn", "invocationId": "turn", "timestamp": "2026-09-27T10:01:00Z", "durationMs": 60000}
        result = report([turn, turn])
        self.assertEqual(result["coordinatorTurnSeconds"], 60)
        self.assertEqual(result["providerChildSeconds"], None)


if __name__ == "__main__": unittest.main()
