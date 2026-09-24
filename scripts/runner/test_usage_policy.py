import datetime as dt
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from usage_policy import (UsagePolicyError, dispatch_decision, validate_policy,
                          validate_usage, worker_state)


NOW = dt.datetime(2026, 9, 22, 10, tzinfo=dt.timezone.utc)


def usage(percent=10, observed="2026-09-22T09:30:00Z", worker="w", account="a"):
    return {worker: {account: {"provider": "provider-x", "model": "expensive-model",
                               "used_percent": percent, "observed_at": observed}}}


def provider_signal(*, service="healthy", auth="valid", live="succeeded",
                    limit="NONE", observed="2026-09-22T09:30:00Z"):
    return {"w": {"a": {
        "provider": "provider-x", "model": "diagnostic-model",
        "capacity_mode": "provider_signal", "observed_at": observed,
        "service_state": service, "authentication_state": auth,
        "live_invocation_state": live, "limit_signal": limit,
    }}}


def scoped_usage(short=0, weekly=73, *, short_observed="2026-09-22T09:30:00Z",
                 weekly_observed="2026-09-22T09:30:00Z"):
    return {"w": {"a": {
        "provider": "provider-x", "model": "diagnostic-model",
        "capacity_mode": "percentage",
        "scopes": {
            "short_window": {"used_percent": short, "observed_at": short_observed},
            "weekly_window": {"used_percent": weekly, "observed_at": weekly_observed},
        },
    }}}


SMALL_BOUNDED = {
    "capacity_size": "SMALL", "capacity_risk": "BOUNDED",
    "lane": "PLATFORM", "kind": "PARENT",
}
SUBSTANTIAL = {
    "capacity_size": "SUBSTANTIAL", "capacity_risk": "BOUNDED",
    "lane": "PLATFORM", "kind": "PARENT",
}
TINY_ASSURANCE = {
    "capacity_size": "VERY_SMALL", "capacity_risk": "BOUNDED",
    "lane": "ASSURANCE", "kind": "REVIEW",
}


class UsagePolicyTests(unittest.TestCase):
    def config(self, **policy):
        return {"usage_policy": {"fallback_models": {"w": {"a": "cheap-model"}}, **policy},
                "agents": {"w": {"account": "a", "model": "expensive-model",
                                   "command": ["expensive"], "fallback_model": "cheap-model",
                                   "fallback_command": ["cheap"]}}}

    def test_ratified_percentage_boundaries(self):
        self.assertEqual(worker_state(self.config(), usage(89.99), "w", "a", NOW), "normal")
        self.assertEqual(worker_state(self.config(), usage(90), "w", "a", NOW), "caution")
        self.assertEqual(worker_state(self.config(), usage(95), "w", "a", NOW), "checkpoint")
        self.assertEqual(worker_state(self.config(), usage(98), "w", "a", NOW), "hard_stop")

    def test_missing_and_stale_are_conservative(self):
        self.assertEqual(worker_state(self.config(), {}, "w", "a", NOW), "unknown")
        self.assertEqual(worker_state(self.config(), usage(observed="2026-09-22T08:00:00Z"), "w", "a", NOW), "unknown")
        result = dispatch_decision(self.config(), {}, "w", "a", NOW)
        self.assertEqual((result["decision"], result["low_cost_only"]), ("defer", False))

    def test_dispatch_gates_package_classification_without_model_routing(self):
        normal = dispatch_decision(self.config(), usage(89.9), "w", "a", NOW,
                                   package=SUBSTANTIAL)
        caution_small = dispatch_decision(self.config(), usage(90), "w", "a", NOW,
                                          package=SMALL_BOUNDED)
        caution_large = dispatch_decision(self.config(), usage(90), "w", "a", NOW,
                                          package=SUBSTANTIAL)
        self.assertEqual((normal['decision'], normal['command'], normal['effective_model']),
                         ('allow', ['expensive'], 'expensive-model'))
        self.assertEqual((caution_small['decision'], caution_small['command']),
                         ('allow', ['expensive']))
        self.assertEqual((caution_large['decision'], caution_large['command']),
                         ('defer', None))

    def test_fallback_command_is_not_required_by_staged_policy(self):
        config = self.config()
        config['agents']['w'].pop('fallback_command')
        result = dispatch_decision(config, usage(90), 'w', 'a', NOW,
                                   package=SMALL_BOUNDED)
        self.assertEqual(result['decision'], 'allow')
        self.assertEqual(result['command'], ['expensive'])

    def test_green_command_absence_defers_without_claim_decision(self):
        config = self.config()
        config['agents']['w'].pop('command')
        result = dispatch_decision(config, usage(10), 'w', 'a', NOW)
        self.assertEqual(result['decision'], 'defer')
        self.assertIsNone(result['command'])

    def test_hard_stop_never_has_command_for_substantial_work(self):
        result = dispatch_decision(self.config(), usage(98), 'w', 'a', NOW,
                                   package=SUBSTANTIAL)
        self.assertEqual(result['decision'], 'stop')
        self.assertIsNone(result['command'])
        self.assertIsNone(result['effective_model'])

    def test_unknown_can_be_configured_to_stop(self):
        config = self.config(unknown_behavior="stop")
        unknown_inputs = (
            {},
            usage(observed="2026-09-22T08:00:00Z"),
            usage(observed="2026-09-22T10:30:00Z"),
        )
        for usage_data in unknown_inputs:
            with self.subTest(usage=usage_data):
                result = dispatch_decision(config, usage_data, "w", "a", NOW)
                self.assertEqual(result["state"], "unknown")
                self.assertEqual(result["decision"], "stop")
                self.assertIsNone(result["command"])
                self.assertIsNone(result["effective_model"])

    def test_invalid_thresholds(self):
        for policy in (
            {"hard_stop_percent": 101},
            {"caution_percent": 95, "checkpoint_percent": 95},
            {"checkpoint_percent": 99, "hard_stop_percent": 98},
        ):
            with self.assertRaises(UsagePolicyError):
                validate_policy({"usage_policy": policy})

    def test_legacy_threshold_names_are_rejected(self):
        for policy in ({"slowdown_percent": 70}, {"stop_percent": 80}):
            with self.assertRaises(UsagePolicyError):
                validate_policy({"usage_policy": policy})

    def test_nonfinite_policy_numbers_are_rejected(self):
        for name in ('caution_percent', 'checkpoint_percent', 'hard_stop_percent',
                     'stale_after_seconds'):
            with self.assertRaises(UsagePolicyError):
                validate_policy({'usage_policy': {name: float('nan')}})
            with self.assertRaises(UsagePolicyError):
                validate_policy({'usage_policy': {name: float('inf')}})

    def test_fallback_metadata_remains_provider_neutral_but_does_not_grant_eligibility(self):
        result = dispatch_decision(self.config(), usage(98), "w", "a", NOW,
                                   package=SUBSTANTIAL)
        self.assertEqual(result["fallback_model"], "cheap-model")
        self.assertNotIn("api", result)

    def test_separate_accounts_have_separate_budgets(self):
        data = usage(98)
        data["w"]["b"] = {"provider": "provider-x", "model": "expensive-model", "used_percent": 5,
                            "observed_at": "2026-09-22T09:30:00Z"}
        self.assertEqual(worker_state(self.config(), data, "w", "a", NOW), "hard_stop")
        self.assertEqual(worker_state(self.config(), data, "w", "b", NOW), "normal")

    def test_checkpoint_does_not_interrupt_healthy_in_flight_work(self):
        result = dispatch_decision(self.config(), usage(96), "w", "a", NOW,
                                   package=SUBSTANTIAL, in_flight=True)
        self.assertEqual(result["decision"], "checkpoint")
        self.assertEqual(result["command"], ["expensive"])

    def test_hard_stop_exceptions_are_explicit_package_classes(self):
        assurance = dispatch_decision(self.config(), usage(98), "w", "a", NOW,
                                      package=TINY_ASSURANCE)
        emergency = dispatch_decision(
            self.config(), usage(99), "w", "a", NOW,
            package={**SUBSTANTIAL, "capacity_risk": "EMERGENCY_RECOVERY"},
        )
        self.assertEqual(assurance["decision"], "allow")
        self.assertEqual(emergency["decision"], "allow")

    def test_provider_signal_mode_needs_health_auth_live_success_and_no_limit(self):
        config = self.config()
        config["agents"]["w"]["capacity_mode"] = "provider_signal"
        healthy = dispatch_decision(config, provider_signal(), "w", "a", NOW,
                                    package=SUBSTANTIAL)
        self.assertEqual((healthy["state"], healthy["decision"]), ("normal", "allow"))
        for data in (
            provider_signal(service="unhealthy"),
            provider_signal(auth="invalid"),
            provider_signal(live="failed"),
            provider_signal(limit="RATE_LIMIT"),
            provider_signal(limit="EXHAUSTION"),
            provider_signal(limit="THROTTLING"),
            provider_signal(limit="CAPACITY_LAUNCH_FAILURE"),
        ):
            with self.subTest(data=data):
                result = dispatch_decision(config, data, "w", "a", NOW,
                                           package=TINY_ASSURANCE)
                self.assertEqual((result["state"], result["decision"]),
                                 ("hard_stop", "stop"))

    def test_capacity_mode_mismatch_is_constrained(self):
        config = self.config()
        config["agents"]["w"]["capacity_mode"] = "provider_signal"
        result = dispatch_decision(config, usage(10), "w", "a", NOW,
                                   package=SMALL_BOUNDED)
        self.assertEqual((result["state"], result["decision"]),
                         ("unknown", "defer"))

    def test_all_codex_scopes_must_be_fresh_and_most_restrictive_wins(self):
        config = self.config()
        config["agents"]["w"]["capacity_scopes"] = ["short_window", "weekly_window"]
        self.assertEqual(
            worker_state(config, scoped_usage(short=0, weekly=73), "w", "a", NOW),
            "normal",
        )
        self.assertEqual(
            worker_state(config, scoped_usage(short=96, weekly=73), "w", "a", NOW),
            "checkpoint",
        )
        self.assertEqual(
            worker_state(
                config,
                scoped_usage(short=0, weekly=73, short_observed="2026-09-22T08:00:00Z"),
                "w", "a", NOW,
            ),
            "unknown",
        )
        missing = scoped_usage()
        del missing["w"]["a"]["scopes"]["short_window"]
        self.assertEqual(worker_state(config, missing, "w", "a", NOW), "unknown")

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
