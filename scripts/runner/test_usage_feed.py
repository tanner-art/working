import datetime as dt
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
from usage_feed import (UsageFeedError, atomic_write_usage, codex_record,
                        configured_targets, read_codex_rate_limits, refresh_codex_usage)
from usage_policy import worker_state


OBSERVED = "2026-09-24T10:00:00Z"
LIMITS = {"rateLimits": {"primary": {"used_percent": 20, "resets_at": 1790247600},
                          "secondary": {"used_percent": 75, "resets_at": 1790251200}}}


def record(percent=10, model="model"):
    return {"provider": "openai", "model": model, "used_percent": percent,
            "observed_at": OBSERVED}


class UsageFeedTests(unittest.TestCase):
    def test_multiple_windows_select_the_most_constrained(self):
        result = codex_record(LIMITS, "gpt-test", OBSERVED)
        self.assertEqual(result["used_percent"], 75.0)
        self.assertEqual(result["reset_at"], "2026-09-24T12:00:00Z")

    def test_raw_provider_fields_are_never_in_the_sanitized_record(self):
        result = codex_record({"rateLimits": {"primary": {"used_percent": 20}},
                               "accountId": "secret-account", "email": "secret@example.test"},
                              "gpt-test", OBSERVED)
        self.assertEqual(set(result), {"provider", "model", "used_percent", "observed_at"})
        self.assertNotIn("secret", json.dumps(result))

    def test_malformed_codex_output_is_unknown_and_prior_record_survives(self):
        existing = {"codex-b": {"account-b": record(44)}}
        output, updated, unknown = refresh_codex_usage(
            existing, [("codex-b", "account-b", "/private/home", "gpt-test")],
            reader=lambda _: {"rateLimits": {"primary": {"used_percent": "bad"}}}, observed_at=OBSERVED)
        self.assertEqual((updated, unknown), (0, 1))
        self.assertEqual(output, existing)

    def test_distinct_codex_accounts_are_updated_independently(self):
        responses = {"/home/a": {"rateLimits": {"primary": {"used_percent": 12}}},
                     "/home/b": {"rateLimits": {"primary": {"used_percent": 68}}}}
        output, updated, unknown = refresh_codex_usage(
            {}, [("codex-a", "account-a", "/home/a", "model-a"),
                 ("codex-b", "account-b", "/home/b", "model-b")],
            reader=responses.__getitem__, observed_at=OBSERVED)
        self.assertEqual((updated, unknown), (2, 0))
        self.assertEqual(output["codex-a"]["account-a"]["used_percent"], 12.0)
        self.assertEqual(output["codex-b"]["account-b"]["used_percent"], 68.0)

    def test_config_discovers_each_codex_home_and_claude_unknown(self):
        config = {"agents": {
            "codex-a": {"provider": "openai", "account": "a", "model": "model-a",
                        "env": {"CODEX_HOME": "/home/a"}},
            "codex-b": {"provider": "openai", "account": "b", "model": "model-b",
                        "env": {"CODEX_HOME": "/home/b"}},
            "claude": {"provider": "anthropic", "account": "c", "model": "claude-model", "env": {}},
        }}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps(config))
            targets, claude = configured_targets(path)
        self.assertEqual(targets, [("codex-a", "a", "/home/a", "model-a"),
                                   ("codex-b", "b", "/home/b", "model-b")])
        self.assertEqual(claude, 1)

    def test_timeout_is_reported_without_provider_output(self):
        class Process:
            def communicate(self, *args, **kwargs):
                raise subprocess.TimeoutExpired("codex", 1)

            def kill(self):
                pass

        with patch("usage_feed.subprocess.Popen", return_value=Process()):
            with self.assertRaises(UsageFeedError) as error:
                read_codex_rate_limits("/private/secret-home", timeout=0.01)
        self.assertNotIn("secret", str(error.exception))

    def test_claude_logged_out_or_unknown_cannot_create_a_green_record(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "usage.json"
            completed = subprocess.run(
                [sys.executable, "usage_feed.py", "--usage", str(path),
                 "--claude", "claude/account=logged-out"], cwd=Path(__file__).parent,
                text=True, capture_output=True, check=False)
            self.assertEqual(completed.returncode, 0)
            self.assertEqual(json.loads(completed.stdout), {"unknown": 1, "updated": 0})
            self.assertFalse(path.exists())

    def test_failed_cli_observation_does_not_rewrite_prior_valid_record(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "usage.json"
            original = json.dumps({"codex-a": {"account": record(12)}}) + "\n"
            path.write_text(original)
            completed = subprocess.run(
                [sys.executable, "usage_feed.py", "--usage", str(path),
                 "--codex-home", "codex-a/account=/private/home",
                 "--codex-model", "codex-a/account=model", "--codex", "not-a-real-codex"],
                cwd=Path(__file__).parent, text=True, capture_output=True, check=False)
            self.assertEqual(completed.returncode, 0)
            self.assertEqual(path.read_text(), original)

    def test_missing_or_stale_records_remain_unknown_to_the_policy(self):
        config = {"usage_policy": {"stale_after_seconds": 60}, "agents": {}}
        now = dt.datetime(2026, 9, 24, 10, 2, tzinfo=dt.timezone.utc)
        stale = {"claude": {"account": {**record(), "observed_at": OBSERVED}}}
        self.assertEqual(worker_state(config, {}, "claude", "account", now), "unknown")
        self.assertEqual(worker_state(config, stale, "claude", "account", now), "unknown")

    def test_atomic_file_is_private_and_preserves_unrelated_workers(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "usage.json"
            existing = {"unrelated": {"other": record(30, "other-model")},
                        "codex-a": {"account-a": record(5, "old-model")}}
            atomic_write_usage(path, existing)
            output, updated, unknown = refresh_codex_usage(
                existing, [("codex-a", "account-a", "/home/a", "new-model")],
                reader=lambda _: {"rateLimits": {"primary": {"used_percent": 61}}}, observed_at=OBSERVED)
            self.assertEqual((updated, unknown), (1, 0))
            atomic_write_usage(path, output)
            self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
            stored = json.loads(path.read_text())
            self.assertEqual(stored["unrelated"]["other"]["provider"], "openai")
            self.assertEqual(stored["unrelated"]["other"]["model"], "other-model")
            self.assertEqual(stored["unrelated"]["other"]["used_percent"], 30.0)
            self.assertEqual(stored["codex-a"]["account-a"]["used_percent"], 61.0)

    def test_cli_output_never_echoes_secret_values(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "usage.json"
            secret = "do-not-echo-this-home"
            completed = subprocess.run(
                [sys.executable, "usage_feed.py", "--usage", str(path),
                 "--codex-home", "codex-a/account=" + secret,
                 "--codex-model", "codex-a/account=model", "--codex", "not-a-real-codex"],
                cwd=Path(__file__).parent, text=True, capture_output=True, check=False)
            self.assertEqual(completed.returncode, 0)
            self.assertNotIn(secret, completed.stdout + completed.stderr)
            self.assertEqual(json.loads(completed.stdout), {"unknown": 1, "updated": 0})


if __name__ == "__main__":
    unittest.main()
