from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts.factory_registry import (
    Attempt,
    ClaudeTelemetryError,
    Feature,
    Lane,
    RegistryConflict,
    SQLiteRegistry,
    TaskStatus,
    UsageLedgerEntry,
    UsageObservationClass,
    UsageSource,
    Worker,
    WorkPackage,
    classify_limit_signal,
    parse_claude_json,
    parse_claude_stream_json,
    parse_claude_transcript,
)


def cli_result(**overrides: object) -> bytes:
    payload: dict[str, object] = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "session_id": "11111111-1111-4111-8111-111111111111",
        "uuid": "22222222-2222-4222-8222-222222222222",
        "duration_ms": 1500,
        "duration_api_ms": 1200,
        "num_turns": 1,
        "stop_reason": "end_turn",
        "total_cost_usd": 0.05,
        "result": "ordinary assistant response that must not be retained",
        "usage": {
            "input_tokens": 10,
            "output_tokens": 20,
            "cache_read_input_tokens": 30,
            "cache_creation_input_tokens": 40,
        },
        "modelUsage": {"claude-sonnet-test": {"inputTokens": 10}},
    }
    payload.update(overrides)
    return json.dumps(payload).encode()


class ClaudeParserTest(unittest.TestCase):
    def test_json_captures_structured_usage_without_message_content(self) -> None:
        entry = parse_claude_json(
            cli_result(),
            worker_id="claude",
            account_id="account",
            observed_at="2026-09-24T20:00:00Z",
            cli_version="2.1.278",
            package_id="TASK-1",
            attempt_id="ATTEMPT-1",
        )
        self.assertEqual(entry.session_id, "11111111-1111-4111-8111-111111111111")
        self.assertEqual(entry.model_diagnostic, "claude-sonnet-test")
        self.assertEqual(entry.input_tokens, 10)
        self.assertEqual(entry.output_tokens, 20)
        self.assertEqual(entry.cache_read_input_tokens, 30)
        self.assertEqual(entry.cache_creation_input_tokens, 40)
        self.assertEqual(entry.duration_ms, 1500)
        self.assertEqual(entry.outcome, "SUCCEEDED")
        self.assertEqual(entry.source_metadata["cli_version"], "2.1.278")
        self.assertEqual(entry.source_metadata["result_metadata"]["duration_api_ms"], 1200)
        self.assertEqual(
            entry.source_metadata["model_usage"]["claude-sonnet-test"],
            {"inputTokens": 10},
        )
        self.assertNotIn("result", entry.source_metadata)
        self.assertIsNone(entry.limit_raw_error)

    def test_parser_metadata_uses_explicit_privacy_allowlists(self) -> None:
        entry = parse_claude_json(
            cli_result(
                usage={
                    "input_tokens": 10,
                    "output_tokens": 20,
                    "private_payload": {"prompt": "do not retain"},
                },
                modelUsage={
                    "claude-sonnet-test": {
                        "inputTokens": 10,
                        "private_payload": {"answer": "do not retain"},
                    }
                },
                subagent_stats={"agent": {"prompt": "do not retain"}},
            ),
            worker_id="claude",
            account_id="account",
            observed_at="2026-09-24T20:00:00Z",
            package_id="TASK-1",
            attempt_id="ATTEMPT-1",
        )
        metadata = json.dumps(entry.source_metadata)
        self.assertNotIn("do not retain", metadata)
        self.assertNotIn("private_payload", metadata)
        self.assertNotIn("subagent_stats", metadata)
        self.assertEqual(entry.source_metadata["subagent_count"], 1)
        with self.assertRaisesRegex(ClaudeTelemetryError, "duration_api_ms"):
            parse_claude_json(
                cli_result(duration_api_ms={"private": "value"}),
                worker_id="claude",
                account_id="account",
                observed_at="2026-09-24T20:00:00Z",
                package_id="TASK-1",
                attempt_id="ATTEMPT-1",
            )

    def test_autonomous_provenance_is_required_and_diagnostics_are_explicit(self) -> None:
        with self.assertRaisesRegex(ClaudeTelemetryError, "package_id and attempt_id"):
            parse_claude_json(
                cli_result(),
                worker_id="claude",
                account_id="account",
                observed_at="2026-09-24T20:00:00Z",
            )
        diagnostic = parse_claude_json(
            cli_result(),
            worker_id="claude",
            account_id="account",
            observed_at="2026-09-24T20:00:00Z",
            observation_class=UsageObservationClass.DIAGNOSTIC,
        )
        self.assertEqual(diagnostic.observation_class, UsageObservationClass.DIAGNOSTIC)

    def test_explicit_limit_error_is_preserved_for_calibration(self) -> None:
        raw_error = "Rate limit reached; retry after the supplied reset time"
        entry = parse_claude_json(
            cli_result(
                is_error=True,
                result=raw_error,
                reset_at="2026-09-24T21:00:00Z",
                usage={"input_tokens": 0, "output_tokens": 0},
            ),
            worker_id="claude",
            account_id="account",
            observed_at="2026-09-24T20:00:00Z",
            package_id="TASK-1",
            attempt_id="ATTEMPT-1",
        )
        self.assertEqual(entry.outcome, "LIMITED")
        self.assertEqual(entry.limit_signal, "RATE_LIMIT")
        self.assertEqual(entry.limit_raw_error, raw_error)
        self.assertEqual(entry.limit_reset_at, "2026-09-24T21:00:00.000000Z")
        self.assertIsNone(classify_limit_signal("service unavailable"))

    def test_http_429_and_retry_timing_are_structured_limit_evidence(self) -> None:
        entry = parse_claude_json(
            cli_result(
                is_error=True,
                result="",
                api_error_status=429,
                error={"message": "request rejected", "retry_after": 120},
            ),
            worker_id="claude",
            account_id="account",
            observed_at="2026-09-24T20:00:00Z",
            package_id="TASK-1",
            attempt_id="ATTEMPT-1",
        )
        self.assertEqual(entry.limit_signal, "RATE_LIMIT")
        self.assertEqual(entry.calibration_metadata["provider_retry_after"], 120)
        self.assertIn("request rejected", entry.limit_raw_error or "")

    def test_stream_json_uses_final_aggregate_result(self) -> None:
        records = [
            {"type": "system", "session_id": "session"},
            {"type": {"private": "must not be stringified"}},
            json.loads(cli_result()),
        ]
        entry = parse_claude_stream_json(
            "\n".join(json.dumps(record) for record in records).encode(),
            worker_id="claude",
            account_id="account",
            observed_at="2026-09-24T20:00:00Z",
            package_id="TASK-1",
            attempt_id="ATTEMPT-1",
        )
        self.assertEqual(entry.source_type, UsageSource.CLI_STREAM_JSON)
        self.assertEqual(entry.input_tokens, 10)
        self.assertEqual(entry.source_metadata["record_count"], 3)
        self.assertEqual(entry.source_metadata["record_types"], ["result", "system"])
        self.assertEqual(entry.source_metadata["unknown_record_type_count"], 1)
        self.assertNotIn("private", json.dumps(entry.source_metadata))

    def test_transcript_deduplicates_repeated_provider_message_records(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "projects"
            project = root / "-private-tmp"
            project.mkdir(parents=True)
            session_id = "33333333-3333-4333-8333-333333333333"
            transcript = project / f"{session_id}.jsonl"
            usage = {
                "input_tokens": 2,
                "output_tokens": 7,
                "cache_read_input_tokens": 11,
                "cache_creation_input_tokens": 13,
                "private_payload": {"answer": "private usage"},
            }
            assistant = {
                "type": "assistant",
                "sessionId": session_id,
                "timestamp": "2026-09-24T20:00:02Z",
                "version": "2.1.278",
                "uuid": "assistant-record",
                "message": {
                    "id": "provider-message",
                    "role": "assistant",
                    "model": "claude-sonnet-test",
                    "stop_reason": "end_turn",
                    "usage": usage,
                    "content": [{"type": "text", "text": "private answer"}],
                },
            }
            records = [
                {
                    "type": "user",
                    "sessionId": session_id,
                    "timestamp": "2026-09-24T20:00:00Z",
                    "version": "2.1.278",
                    "message": {"role": "user", "content": "private prompt"},
                },
                assistant,
                {**assistant, "uuid": "repeated-content-block"},
                {
                    "type": "cost-state",
                    "sessionId": session_id,
                    "startTime": 1_790_284_800_000,
                    "totalAPIDuration": 1200,
                    "totalAPIDurationWithoutRetries": 1100,
                    "totalCostUSD": 0.01,
                    "totalDuration": 2000,
                    "totalToolDuration": 500,
                    "totalLinesAdded": 3,
                    "totalLinesRemoved": 1,
                    "hasUnknownModelCost": False,
                    "modelUsage": {
                        "claude-sonnet-test": {
                            "inputTokens": 2,
                            "outputTokens": 7,
                            "costUSD": 0.01,
                        }
                    },
                    "private_payload": {"prompt": "private cost state"},
                },
            ]
            transcript.write_text("\n".join(json.dumps(record) for record in records))
            entry = parse_claude_transcript(
                transcript,
                transcript_root=root,
                worker_id="claude",
                account_id="account",
                package_id="TASK-1",
                attempt_id="ATTEMPT-1",
            )
            self.assertEqual(entry.output_tokens, 7)
            self.assertEqual(entry.duration_ms, 2000)
            self.assertEqual(entry.source_metadata["unique_assistant_messages"], 1)
            self.assertEqual(entry.source_metadata["duplicate_assistant_records_ignored"], 1)
            self.assertEqual(len(entry.source_metadata["assistant_usage_records"]), 1)
            self.assertEqual(
                entry.source_metadata["cost_state"],
                {
                    "start_time": 1_790_284_800_000,
                    "total_api_duration_ms": 1200,
                    "total_api_duration_without_retries_ms": 1100,
                    "total_cost_usd": 0.01,
                    "total_duration_ms": 2000,
                    "total_tool_duration_ms": 500,
                    "total_lines_added": 3,
                    "total_lines_removed": 1,
                    "has_unknown_model_cost": False,
                    "model_usage": {
                        "claude-sonnet-test": {
                            "inputTokens": 2,
                            "outputTokens": 7,
                            "costUSD": 0.01,
                        }
                    },
                },
            )
            self.assertNotIn("private", json.dumps(entry.source_metadata))
            self.assertIsNone(entry.limit_raw_error)
            transcript.write_text(
                transcript.read_text()
                + "\n"
                + json.dumps({"type": "cost-state", "sessionId": session_id})
            )
            with self.assertRaisesRegex(ClaudeTelemetryError, "exactly one terminal"):
                parse_claude_transcript(
                    transcript,
                    transcript_root=root,
                    worker_id="claude",
                    account_id="account",
                    package_id="TASK-1",
                    attempt_id="ATTEMPT-1",
                )

    def test_transcript_requires_verified_root_and_terminal_record(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "root"
            outside = Path(temporary) / "outside"
            root.mkdir()
            outside.mkdir()
            transcript = outside / "session.jsonl"
            transcript.write_text("{}")
            with self.assertRaisesRegex(ClaudeTelemetryError, "outside the verified root"):
                parse_claude_transcript(
                    transcript,
                    transcript_root=root,
                    worker_id="claude",
                    account_id="account",
                    package_id="TASK-1",
                    attempt_id="ATTEMPT-1",
                )


class UsageLedgerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.database = Path(self.temporary.name) / "registry.sqlite3"
        self.registry = SQLiteRegistry(self.database)
        self.registry.initialize()
        self.registry.register_worker(
            Worker(
                "claude",
                "Claude",
                ("review",),
                (Lane.ASSURANCE,),
                provider_diagnostics={"provider": "anthropic"},
                usage_state="HEALTHY",
            )
        )
        self.registry.register_feature(Feature("FEATURE", "Telemetry", 1))
        self.registry.register_work_package(
            WorkPackage(
                "TASK-1",
                "FEATURE",
                "Capture usage",
                "platform",
                Lane.ASSURANCE,
                ("review",),
                1,
                ("Usage is attributable",),
                status=TaskStatus.READY,
            )
        )
        self.registry.register_attempt(
            Attempt(
                "ATTEMPT-1",
                "TASK-1",
                "claude",
                "2026-09-22T19:00:00Z",
            )
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def entry(
        self,
        invocation: str,
        observed_at: str,
        *,
        source: UsageSource = UsageSource.CLI_JSON,
        source_identity: str | None = None,
        output_tokens: int = 20,
        duration_ms: float = 1000,
        task_completed: bool = False,
        review_completed: bool = False,
        limit_signal: str | None = None,
        model: str | None = "claude-sonnet-test",
        outcome: str | None = None,
        observation_class: UsageObservationClass = UsageObservationClass.AUTONOMOUS,
    ) -> UsageLedgerEntry:
        return UsageLedgerEntry(
            id=f"ledger-{invocation}",
            provider="anthropic",
            worker_id="claude",
            account_id="account",
            invocation_id=invocation,
            session_id=f"session-{invocation}",
            observed_at=observed_at,
            outcome=outcome or ("LIMITED" if limit_signal else "SUCCEEDED"),
            source_type=source,
            source_identity=source_identity or f"source-{invocation}-{source.value}",
            package_id="TASK-1",
            attempt_id="ATTEMPT-1",
            observation_class=observation_class,
            model_diagnostic=model,
            input_tokens=10,
            output_tokens=output_tokens,
            cache_read_input_tokens=30,
            cache_creation_input_tokens=40,
            duration_ms=duration_ms,
            task_completed=task_completed,
            review_completed=review_completed,
            limit_signal=limit_signal,
            limit_raw_error="rate limit reached" if limit_signal else None,
            source_metadata={
                "duration_basis": (
                    "first_to_last_timestamp"
                    if source is UsageSource.TRANSCRIPT
                    else "provider_result"
                )
            },
        )

    def test_cross_source_ingestion_counts_invocation_once(self) -> None:
        first = self.entry("one", "2026-09-24T20:00:00Z")
        second = self.entry(
            "one",
            "2026-09-24T20:00:01Z",
            source=UsageSource.TRANSCRIPT,
        )
        self.assertTrue(self.registry.record_usage(first).inserted)
        duplicate = self.registry.record_usage(second)
        self.assertFalse(duplicate.inserted)
        self.assertTrue(duplicate.source_added)
        same_source = self.registry.record_usage(second)
        self.assertFalse(same_source.inserted)
        self.assertFalse(same_source.source_added)
        entries = self.registry.usage_entries(worker_id="claude")
        self.assertEqual(len(entries), 1)
        self.assertEqual(len(entries[0]["sources"]), 2)

    def test_cross_source_canonicalization_is_order_independent_and_keeps_limits(self) -> None:
        for invocation, transcript_first in (("first", True), ("second", False)):
            transcript = self.entry(
                invocation,
                "2026-09-24T20:00:01Z",
                source=UsageSource.TRANSCRIPT,
                duration_ms=2_000,
            )
            cli = self.entry(
                invocation,
                "2026-09-24T20:00:02Z",
                duration_ms=1_000,
                task_completed=True,
                limit_signal="RATE_LIMIT",
            )
            ordered = (transcript, cli) if transcript_first else (cli, transcript)
            for value in ordered:
                self.registry.record_usage(value)
        entries = {entry["invocation_id"]: entry for entry in self.registry.usage_entries()}
        for invocation in ("first", "second"):
            canonical = entries[invocation]
            self.assertEqual(canonical["outcome"], "LIMITED")
            self.assertEqual(canonical["limit_signal"], "RATE_LIMIT")
            self.assertTrue(canonical["task_completed"])
            self.assertEqual(canonical["duration_ms"], 1_000)
            self.assertEqual(canonical["duration_basis"], "provider_result")

    def test_cross_source_canonical_identity_fields_conflict(self) -> None:
        self.registry.record_usage(self.entry("one", "2026-09-24T20:00:00Z"))
        with self.assertRaisesRegex(
            RegistryConflict, "USAGE_SOURCE_MISMATCH: model_diagnostic"
        ):
            self.registry.record_usage(
                self.entry(
                    "one",
                    "2026-09-24T20:00:01Z",
                    source=UsageSource.TRANSCRIPT,
                    model="claude-opus-test",
                )
            )
        with self.assertRaisesRegex(RegistryConflict, "USAGE_SOURCE_MISMATCH: outcome"):
            self.registry.record_usage(
                self.entry(
                    "one",
                    "2026-09-24T20:00:01Z",
                    source=UsageSource.TRANSCRIPT,
                    source_identity="different-outcome-source",
                    outcome="FAILED",
                )
            )
        with self.assertRaisesRegex(
            RegistryConflict, "USAGE_SOURCE_MISMATCH: duration_ms"
        ):
            self.registry.record_usage(
                self.entry(
                    "one",
                    "2026-09-24T20:00:01Z",
                    source=UsageSource.CLI_STREAM_JSON,
                    source_identity="different-duration-source",
                    duration_ms=2_000,
                )
            )

    def test_cross_source_measurement_disagreement_fails_closed(self) -> None:
        self.registry.record_usage(self.entry("one", "2026-09-24T20:00:00Z"))
        conflicting = self.entry(
            "one",
            "2026-09-24T20:00:01Z",
            source=UsageSource.TRANSCRIPT,
            output_tokens=21,
        )
        with self.assertRaisesRegex(
            RegistryConflict, "USAGE_SOURCE_MISMATCH: output_tokens"
        ):
            self.registry.record_usage(conflicting)
        entries = self.registry.usage_entries(worker_id="claude")
        self.assertEqual(len(entries), 1)
        self.assertEqual(len(entries[0]["sources"]), 1)

    def test_source_identity_cannot_be_reassigned_to_another_invocation(self) -> None:
        first = self.entry("one", "2026-09-24T20:00:00Z")
        self.registry.record_usage(first)
        reassigned = self.entry(
            "two",
            "2026-09-24T20:00:01Z",
            source_identity=first.source_identity,
        )
        with self.assertRaisesRegex(
            RegistryConflict, "USAGE_SOURCE_MISMATCH: invocation_id"
        ):
            self.registry.record_usage(reassigned)

    def test_ledger_and_source_rows_are_append_only(self) -> None:
        self.registry.record_usage(self.entry("one", "2026-09-24T20:00:00Z"))
        with sqlite3.connect(self.database) as connection:
            with self.assertRaisesRegex(sqlite3.IntegrityError, "USAGE_LEDGER_APPEND_ONLY"):
                connection.execute("UPDATE usage_ledger SET outcome='FAILED'")
            with self.assertRaisesRegex(
                sqlite3.IntegrityError, "USAGE_LEDGER_SOURCES_APPEND_ONLY"
            ):
                connection.execute("DELETE FROM usage_ledger_sources")

    def test_rolling_analytics_and_limit_calibration(self) -> None:
        self.registry.record_usage(
            self.entry(
                "old",
                "2026-09-22T20:00:00Z",
                output_tokens=100,
                duration_ms=3_600_000,
                task_completed=True,
            )
        )
        self.registry.record_usage(
            self.entry(
                "recent",
                "2026-09-24T19:30:00Z",
                output_tokens=50,
                duration_ms=1_800_000,
                review_completed=True,
            )
        )
        self.registry.record_usage(
            self.entry(
                "limited",
                "2026-09-24T20:00:00Z",
                output_tokens=0,
                duration_ms=0,
                limit_signal="RATE_LIMIT",
            )
        )
        analytics = self.registry.usage_analytics(
            "claude", observed_at="2026-09-24T20:30:00Z"
        )
        self.assertEqual(analytics["rolling_24h"]["invocations"], 2)
        self.assertEqual(analytics["rolling_7d"]["invocations"], 3)
        self.assertEqual(analytics["rolling_7d"]["tasks_completed"], 1)
        self.assertEqual(analytics["rolling_7d"]["review_throughput"], 1)
        self.assertAlmostEqual(analytics["output_tokens_per_productive_hour_7d"], 100)
        self.assertIsNone(analytics["provider_reported_percent"])
        self.assertIsNone(analytics["inferred_capacity_percent"])
        self.assertEqual(len(analytics["limit_events_7d"]), 1)
        calibration = analytics["limit_events_7d"][0]["rolling_consumption"]
        self.assertEqual(
            calibration["factory_measured_before_limit"]["rolling_7d"]["invocations"],
            2,
        )

    def test_negative_measurement_is_rejected(self) -> None:
        bad = UsageLedgerEntry(
            **{**self.entry("bad", "2026-09-24T20:00:00Z").__dict__, "input_tokens": -1}
        )
        with self.assertRaisesRegex(RegistryConflict, "INVALID_USAGE_MEASUREMENT"):
            self.registry.record_usage(bad)

    def test_autonomous_attempt_must_belong_to_package_and_diagnostic_is_distinct(self) -> None:
        self.registry.register_work_package(
            WorkPackage(
                "TASK-2",
                "FEATURE",
                "Other package",
                "platform",
                Lane.ASSURANCE,
                ("review",),
                1,
                ("Remain attributable",),
            )
        )
        self.registry.register_attempt(
            Attempt("ATTEMPT-2", "TASK-2", "claude", "2026-09-24T19:00:00Z")
        )
        mismatched = UsageLedgerEntry(
            **{
                **self.entry("mismatch", "2026-09-24T20:00:00Z").__dict__,
                "attempt_id": "ATTEMPT-2",
            }
        )
        with self.assertRaisesRegex(RegistryConflict, "USAGE_ATTEMPT_PACKAGE_MISMATCH"):
            self.registry.record_usage(mismatched)
        diagnostic = UsageLedgerEntry(
            **{
                **self.entry("probe", "2026-09-24T20:00:00Z").__dict__,
                "package_id": None,
                "attempt_id": None,
                "observation_class": UsageObservationClass.DIAGNOSTIC,
            }
        )
        self.assertTrue(self.registry.record_usage(diagnostic).inserted)
        legacy = UsageLedgerEntry(
            **{
                **diagnostic.__dict__,
                "id": "legacy",
                "invocation_id": "legacy",
                "source_identity": "legacy-source",
                "observation_class": UsageObservationClass.LEGACY_UNCLASSIFIED,
            }
        )
        with self.assertRaisesRegex(RegistryConflict, "LEGACY_USAGE_CLASS_RESERVED"):
            self.registry.record_usage(legacy)
        with sqlite3.connect(self.database) as connection:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    """INSERT INTO usage_ledger
                       (id, provider, worker_id, account_id, invocation_id, session_id,
                        observation_class, observed_at, outcome, task_completed,
                        review_completed, calibration_metadata_json, primary_source_type,
                        primary_source_identity, primary_source_metadata_json, created_at)
                       VALUES ('bad', 'anthropic', 'claude', 'account', 'bad', 'bad',
                               'AUTONOMOUS', '2026-09-24T20:00:00Z', 'SUCCEEDED', 0,
                               0, '{}', 'CLI_JSON', 'bad-source', '{}',
                               '2026-09-24T20:00:00Z')"""
                )


if __name__ == "__main__":
    unittest.main()
