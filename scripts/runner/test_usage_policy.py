import datetime as dt
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from usage_policy import UsagePolicyError, dispatch_decision, validate_policy, validate_usage, worker_state


NOW = dt.datetime(2026, 9, 22, 10, tzinfo=dt.timezone.utc)


def usage(percent=10, observed="2026-09-22T09:30:00Z", worker="w", account="a"):
    return {worker: {account: {"provider": "provider-x", "model": "expensive-model",
                               "used_percent": percent, "observed_at": observed}}}


class UsagePolicyTests(unittest.TestCase):
    def config(self, **policy):
        return {"usage_policy": {"fallback_models": {"w": {"a": "cheap-model"}}, **policy}}

    def test_boundaries_are_green_slow_stop(self):
        self.assertEqual(worker_state(self.config(), usage(69.9), "w", "a", NOW), "green")
        self.assertEqual(worker_state(self.config(), usage(70), "w", "a", NOW), "slow")
        self.assertEqual(worker_state(self.config(), usage(79.99), "w", "a", NOW), "slow")
        self.assertEqual(worker_state(self.config(), usage(80), "w", "a", NOW), "stop")

    def test_missing_and_stale_are_conservative(self):
        self.assertEqual(worker_state(self.config(), {}, "w", "a", NOW), "unknown")
        self.assertEqual(worker_state(self.config(), usage(observed="2026-09-22T08:00:00Z"), "w", "a", NOW), "unknown")
        result = dispatch_decision(self.config(), {}, "w", "a", NOW)
        self.assertEqual((result["decision"], result["low_cost_only"]), ("fallback", True))

    def test_unknown_can_be_configured_to_stop(self):
        result = dispatch_decision(self.config(unknown_behavior="stop"), {}, "w", "a", NOW)
        self.assertEqual(result["decision"], "stop")

    def test_invalid_thresholds(self):
        for policy in ({"stop_percent": 81}, {"slowdown_percent": 80}, {"slowdown_percent": 81, "stop_percent": 80}):
            with self.assertRaises(UsagePolicyError):
                validate_policy({"usage_policy": policy})

    def test_fallback_is_configured_and_provider_neutral(self):
        result = dispatch_decision(self.config(), usage(80), "w", "a", NOW)
        self.assertEqual(result["fallback_model"], "cheap-model")
        self.assertNotIn("api", result)

    def test_separate_accounts_have_separate_budgets(self):
        data = usage(80)
        data["w"]["b"] = {"provider": "provider-x", "model": "expensive-model", "used_percent": 5,
                            "observed_at": "2026-09-22T09:30:00Z"}
        self.assertEqual(worker_state(self.config(), data, "w", "a", NOW), "stop")
        self.assertEqual(worker_state(self.config(), data, "w", "b", NOW), "green")

    def test_schema_rejects_secrets_and_bad_values(self):
        bad = usage()
        bad["w"]["a"]["token"] = "secret"
        with self.assertRaises(UsagePolicyError):
            validate_usage(bad)
        with self.assertRaises(UsagePolicyError):
            validate_usage(usage(101))

    def test_cli_does_not_echo_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config.json"
            data = root / "usage.json"
            config.write_text(json.dumps(self.config()))
            data.write_text(json.dumps(usage()))
            completed = subprocess.run([sys.executable, "usage_policy.py", "--config", str(config),
                                        "--usage", str(data), "--worker", "w/a", "--json"],
                                       cwd=Path(__file__).parent, text=True, capture_output=True)
            self.assertEqual(completed.returncode, 0)
            self.assertNotIn("secret", completed.stdout + completed.stderr)


if __name__ == "__main__":
    unittest.main()
