from __future__ import annotations

import unittest
import subprocess
import sys
import time

from scripts.factory_registry.codex_capacity import CapacityCollectorError, normalize_buckets, _read_reply


class CodexCapacityTests(unittest.TestCase):
    def test_sanitized_real_rate_limits_shape_records_collection_time_and_both_scopes(self):
        values = normalize_buckets("codex-a", {
            "ordinary_usage_allowed": True,
            "account_identity_sha256": "pool-a", "observed_at": "2026-09-26T10:00:00.000000Z",
            "primary": {"usedPercent": 12.5, "windowDurationMins": 300, "resetsAt": 1790412000},
            "secondary": {"usedPercent": 44.0, "windowDurationMins": 10080, "resetsAt": 1791016800},
        })
        self.assertEqual([item["provider_diagnostics"]["capacity_scope"] for item in values], ["short_window", "weekly_window"])
        self.assertTrue(all(item["observed_at"] == "2026-09-26T10:00:00.000000Z" for item in values))
        self.assertTrue(all(item["provider_diagnostics"]["capacity_pool"] == "pool-a" for item in values))

    def test_missing_fresh_collection_timestamp_fails_closed(self):
        with self.assertRaisesRegex(CapacityCollectorError, "timestamped"):
            normalize_buckets("codex-a", {"ordinary_usage_allowed": True,
                "account_identity_sha256": "pool-a", "primary": {"usedPercent": 10, "windowDurationMins": 300, "resetsAt": 1}})

    def test_weekly_only_primary_is_not_mislabeled_as_short_window(self):
        values = normalize_buckets("codex-b", {
            "ordinary_usage_allowed": True,
            "account_identity_sha256": "pool-b", "observed_at": "2026-09-26T19:00:00Z",
            "primary": {"usedPercent": 12, "windowDurationMins": 10080, "resetsAt": 1791016800},
            "secondary": None,
        })
        self.assertEqual(len(values), 1)
        self.assertEqual(values[0]["provider_diagnostics"]["capacity_scope"], "weekly_window")

    def test_unknown_or_duplicate_window_fails_closed(self):
        base = {"ordinary_usage_allowed": True, "account_identity_sha256": "pool-a",
                "observed_at": "2026-09-26T19:00:00Z"}
        with self.assertRaisesRegex(CapacityCollectorError, "unrecognized"):
            normalize_buckets("codex-a", {**base, "primary": {
                "usedPercent": 10, "windowDurationMins": 60}})
        with self.assertRaisesRegex(CapacityCollectorError, "duplicate"):
            normalize_buckets("codex-a", {**base,
                "primary": {"usedPercent": 10, "windowDurationMins": 300},
                "secondary": {"usedPercent": 20, "windowDurationMins": 300}})

    def test_unavailable_account_is_not_reported_as_capacity(self):
        with self.assertRaisesRegex(CapacityCollectorError, "ordinary usage"):
            normalize_buckets("codex-a", {"ordinary_usage_allowed": False})

    def test_partial_response_cannot_block_past_timeout(self):
        process = subprocess.Popen([sys.executable, '-u', '-c',
            'import sys,time; sys.stdout.write("{"); sys.stdout.flush(); time.sleep(5)'],
            stdout=subprocess.PIPE, text=True)
        started = time.monotonic()
        try:
            with self.assertRaisesRegex(CapacityCollectorError, "timed out"):
                _read_reply(process, 1, timeout=0.1)
            self.assertLess(time.monotonic() - started, 2)
        finally:
            process.terminate()
            process.wait(timeout=2)
            process.stdout.close()

    def test_buffered_notifications_do_not_hide_reply(self):
        process = subprocess.Popen([sys.executable, '-u', '-c',
            'print(\'{"method":"notice"}\\n{"id":1,"result":{"ok":true}}\\n{"id":2,"result":{"ok":true}}\')'],
            stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(_read_reply(process, 1, timeout=1), {"ok": True})
            self.assertEqual(_read_reply(process, 2, timeout=1), {"ok": True})
        finally:
            process.wait(timeout=2)
            process.stdout.close()
