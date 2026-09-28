from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.runner.runtime_accounting import collect, report


class RuntimeAccountingTest(unittest.TestCase):
    def test_collects_only_allowlisted_lifecycle_fields_and_deduplicates_replay(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "provider.jsonl"
            path.write_text("\n".join((
                json.dumps({"type": "thread.started", "thread_id": "thread-1", "prompt": "do not retain", "timestamp": "2026-09-27T10:00:00Z"}),
                json.dumps({"type": "thread.started", "thread_id": "thread-1", "prompt": "do not retain", "timestamp": "2026-09-27T10:00:00Z"}),
                json.dumps({"type": "result", "session_id": "claude-1", "duration_ms": 60, "environment": "secret"}),
            )))
            events = collect([str(path)])
        self.assertNotIn("prompt", json.dumps(events))
        self.assertNotIn("environment", json.dumps(events))
        summary = report(events)
        self.assertEqual(summary["eventCount"], 2)
        self.assertEqual(summary["replayedEventCount"], 1)
        self.assertIsNone(summary["providerChildSeconds"])

    def test_coordinator_turn_uses_real_outer_timestamps_or_explicit_duration(self) -> None:
        events = [
            {"source": "coordinator", "type": "task_started", "sessionId": "turn-1", "parentId": None, "timestamp": "2026-09-27T10:00:00Z", "durationMs": None},
            {"source": "coordinator", "type": "task_complete", "sessionId": "turn-1", "parentId": None, "timestamp": "2026-09-27T10:01:00Z", "durationMs": None},
        ]
        self.assertEqual(report(events)["coordinatorTurnSeconds"], 60)


if __name__ == "__main__":
    unittest.main()
