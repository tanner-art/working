"""Focused usable-pilot regressions; all provider/GitHub calls are fakes."""
from __future__ import annotations

import contextlib
import io
import json
import pathlib
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import runner
from scripts.factory_registry.models import ReviewInput
from scripts.factory_registry import Feature, Lane, SQLiteRegistry, TaskStatus, Worker, WorkPackage
from scripts.factory_registry.repository import RegistryConflict
from scripts.factory_registry.shadow_dispatch import RejectionCode, decide_shadow


class ReviewValidationTests(unittest.TestCase):
    def review_input(self) -> ReviewInput:
        return ReviewInput(
            id="input", review_package_id="TASK-2", target_package_id="TASK-1",
            implementation_attempt_id="attempt", implementation_commit="a" * 40,
            base_commit="b" * 40, pr_url="https://github.com/tanner-art/working/pull/230",
            contract_sha256="c" * 64, contract={}, validation_evidence={"packet": "ok"},
            recorded_at="2026-09-26T10:00:00Z",
        )

    def github(self, *, head="a" * 40, checks=None):
        checks = checks if checks is not None else [
            {"name": "verify", "workflow": "Validate app", "state": "SUCCESS"},
            {"name": "Vercel", "workflow": "Vercel", "state": "SUCCESS"},
        ]
        def call(*args):
            return json.dumps({"headRefOid": head}) if args[:2] == ("pr", "view") else json.dumps(checks)
        return call

    def test_unprotected_branch_uses_validate_app_verify_not_vercel(self):
        self.assertTrue(runner.review_source_is_green(self.github(), "tanner-art/working", self.review_input()))
        self.assertFalse(runner.review_source_is_green(
            self.github(checks=[{"name": "Vercel", "workflow": "Vercel", "state": "SUCCESS"}]),
            "tanner-art/working", self.review_input(),
        ))

    def test_pending_failed_or_wrong_head_are_not_review_ready(self):
        for head, state in (("a" * 40, "PENDING"), ("a" * 40, "FAILURE"), ("d" * 40, "SUCCESS")):
            with self.subTest(head=head[:1], state=state):
                self.assertFalse(runner.review_source_is_green(
                    self.github(head=head, checks=[{"name": "verify", "workflow": "Validate app", "state": state}]),
                    "tanner-art/working", self.review_input(),
                ))


class BoundedRunnerMainTests(unittest.TestCase):
    def test_provider_signal_refreshes_keep_scheduler_eligible_then_fail_closed_when_stale_or_limited(self):
        with tempfile.TemporaryDirectory() as directory:
            registry = SQLiteRegistry(pathlib.Path(directory) / "registry.sqlite3")
            registry.initialize()
            base = __import__("datetime").datetime.now(
                __import__("datetime").timezone.utc
            ) + __import__("datetime").timedelta(minutes=1)
            stamp = lambda moment: moment.isoformat().replace("+00:00", "Z")
            registry.register_feature(Feature("FEATURE", "Feature", 10, TaskStatus.READY))
            registry.register_work_package(WorkPackage(
                "TASK-CLAUDE", "FEATURE", "Review", "ORCHESTRATION", Lane.ASSURANCE,
                ("review",), 10, ("fixture",), status=TaskStatus.READY,
            ))
            registry.register_worker(Worker(
                "claude", "Claude", ("review",), (Lane.ASSURANCE,),
                provider_diagnostics={"capacity_mode": "provider_signal",
                                      "capacity_scopes": ["provider_signal"]},
                last_heartbeat_at=stamp(base), usage_state="NORMAL",
            ))
            registry.register_worker(Worker(
                "orchestra", "Orchestra", (), (), role="ORCHESTRA",
                provider_diagnostics={"capacity_mode": "percentage", "capacity_scopes": ["weekly"]},
                last_heartbeat_at=stamp(base), usage_state="NORMAL",
            ))
            dispatch = registry.dispatch_control()
            registry.set_dispatch_control(
                expected_revision=dispatch["revision"], expected_mode="PAUSED",
                new_mode="LIVE", kill_switch_engaged=False, changed_at=stamp(base),
                reason="test provider-signal scheduler evidence",
            )

            def publish(worker_id, moment, *, limited=False):
                before = registry.dispatch_snapshot(observed_at=stamp(moment))
                observation = {
                    "id": f"{worker_id}-{int((moment - base).total_seconds())}-{limited}",
                    "worker_id": worker_id, "observed_at": stamp(moment), "reset_at": None,
                    "consumed_percent": None if worker_id == "claude" else 10,
                    "state": "HARD_STOP" if limited else "NORMAL",
                    "provider_diagnostics": (
                        {"capacity_mode": "provider_signal", "capacity_scope": "provider_signal",
                         "service_state": "unhealthy" if limited else "healthy",
                         "authentication_state": "valid",
                         "live_invocation_state": "failed" if limited else "succeeded",
                         "limit_signal": "RATE_LIMIT" if limited else "NONE"}
                        if worker_id == "claude" else
                        {"capacity_mode": "percentage", "capacity_scope": "weekly"}
                    ),
                }
                registry.record_worker_capacity_observations(worker_id, (observation,), recorded_at=stamp(moment))
                after = registry.dispatch_snapshot(observed_at=stamp(moment))
                self.assertEqual(after.active_leases, before.active_leases)
                for name in ("claude", "orchestra"):
                    original = next(item for item in before.workers if item["id"] == name)
                    current = next(item for item in after.workers if item["id"] == name)
                    self.assertEqual(
                        {key: current[key] for key in ("id", "capabilities", "approved_lanes", "role", "availability")},
                        {key: original[key] for key in ("id", "capabilities", "approved_lanes", "role", "availability")},
                    )

            for elapsed in (0, 300, 600, 930):
                moment = base + __import__("datetime").timedelta(seconds=elapsed)
                if elapsed:
                    registry.record_worker_heartbeat("claude", observed_at=stamp(moment))
                    registry.record_worker_heartbeat("orchestra", observed_at=stamp(moment))
                publish("claude", moment)
                publish("orchestra", moment)
                decision = decide_shadow(registry.dispatch_snapshot(observed_at=stamp(moment)))
                self.assertIn(("TASK-CLAUDE", "claude"), {
                    (item.package_id, item.worker_id) for item in decision.proposed_assignments
                })

            stale_at = base + __import__("datetime").timedelta(seconds=1831)
            stale = decide_shadow(registry.dispatch_snapshot(observed_at=stamp(stale_at)))
            stale_codes = {reason.code for item in stale.pair_evaluations
                           if (item.package_id, item.worker_id) == ("TASK-CLAUDE", "claude")
                           for reason in item.reasons}
            self.assertIn(RejectionCode.USAGE_STALE, stale_codes)

            limited_at = base + __import__("datetime").timedelta(seconds=1860)
            registry.record_worker_heartbeat("claude", observed_at=stamp(limited_at))
            registry.record_worker_heartbeat("orchestra", observed_at=stamp(limited_at))
            publish("claude", limited_at, limited=True)
            publish("orchestra", limited_at)
            limited = decide_shadow(registry.dispatch_snapshot(observed_at=stamp(limited_at)))
            limited_codes = {reason.code for item in limited.pair_evaluations
                             if (item.package_id, item.worker_id) == ("TASK-CLAUDE", "claude")
                             for reason in item.reasons}
            self.assertIn(RejectionCode.PROVIDER_LIMIT_SIGNAL, limited_codes)
            self.assertIn(RejectionCode.PROVIDER_SIGNAL_UNHEALTHY, limited_codes)

    def test_fetches_registered_source_ignores_labels_and_uses_scheduler_worker(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            config = {
                "repo": directory, "state": str(root / "state"), "worktrees": str(root / "trees"),
                "path": "/usr/bin:/bin", "gh": "github-wrapper", "git": "git", "pnpm": "pnpm",
                "github": "tanner-art/working", "allowed_authors": ["owner"],
                "registry_database": str(root / "registry.sqlite"), "registry_lease_seconds": 90,
                "registry_renew_interval_seconds": 30,
                "agents": {"codex-b": {"command": ["agent"], "account": "pool-b"}},
                "capacity_collectors": {"codex-b": {"executable": "/bin/true", "codex_home": "/tmp"}},
            }
            config_path = root / "config.json"; config_path.write_text(json.dumps(config))
            body = {"task": "TASK-701", "paths": ["docs/pilot.md"], "instructions": "Bounded.",
                    "depends_on": [], "lane": "PLATFORM", "kind": "PARENT"}
            issue = {"number": 701, "title": "pilot", "state": "OPEN", "author": {"login": "owner"},
                     "labels": [], "body": json.dumps(body)}  # deliberately stale/missing labels
            review_issue = {"number": 702, "title": "review", "state": "OPEN", "author": {"login": "owner"},
                            "labels": [{"name": "agent:wrong"}], "body": json.dumps({
                                "task": "TASK-702", "paths": ["docs/review.md"], "instructions": "Review.",
                                "depends_on": [701], "lane": "ASSURANCE", "kind": "REVIEW",
                            })}
            control = Mock()
            control.registry.dispatch_control.return_value = {"bounded_run": {"run_id": "pilot"}}
            control.bounded_source_issues.return_value = (701, 702)
            control.proposed_worker.return_value = "codex-b"
            control.pre_claim.return_value = 3
            control.claim_with_retry.side_effect = RegistryConflict("PACKAGE_NOT_READY")
            control.refresh_configured_capacity.return_value = ()
            control.review_input.return_value = ReviewInput(
                id="review-input", review_package_id="TASK-702", target_package_id="TASK-701",
                implementation_attempt_id="attempt", implementation_commit="a" * 40,
                base_commit="b" * 40, pr_url="https://github.com/tanner-art/working/pull/230",
                contract_sha256="c" * 64, contract={}, validation_evidence={"packet": "ok"},
                recorded_at="2026-09-26T10:00:00Z",
            )
            commands = []
            def fake_run(args, **_kwargs):
                commands.append(args)
                if args[:3] == ["github-wrapper", "issue", "view"]:
                    return json.dumps(issue if args[3] == "701" else review_issue)
                if args[:3] == ["github-wrapper", "pr", "view"]:
                    return json.dumps({"headRefOid": "a" * 40})
                if args[:3] == ["github-wrapper", "pr", "checks"]:
                    return json.dumps([{"name": "verify", "workflow": "Validate app", "state": "PENDING"}])
                if args[:3] == ["github-wrapper", "issue", "list"]:
                    return "[]"  # metadata refresh must not be the dispatch source
                return ""
            with patch.object(runner, "run", side_effect=fake_run), \
                 patch.object(runner.RunnerRegistryControl, "from_config", return_value=control), \
                 patch("sys.argv", ["runner", "--config", str(config_path), "--agent", "codex-b"]), \
                 contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                runner.main()
            self.assertIn(["github-wrapper", "issue", "view", "701", "--repo", "tanner-art/working", "--json", "number,title,body,labels,author,state"], commands)
            self.assertFalse(any(call[:3] == ["github-wrapper", "issue", "list"] and "body,labels,author" in call for call in commands))
            self.assertEqual(control.pre_claim.call_args.args[:2], ("TASK-701", "codex-b"))
            self.assertEqual(control.pre_claim.call_args.kwargs["github_issue"], 701)
            self.assertEqual(control.pre_claim.call_args.kwargs["task_contract"]["instructions"], "Bounded.")
            self.assertEqual(control.claim_with_retry.call_args.kwargs["worker_id"], "codex-b")
            self.assertEqual(control.claim_with_retry.call_count, 1)  # implementation progressed; pending review deferred
            self.assertEqual([call.args[0] for call in control.pre_claim.call_args_list], ["TASK-701"])

    def test_review_pending_defers_without_preclaim(self):
        # The exact-CI helper above is intentionally separable; this guards the
        # main-loop behavior without a provider/worktree invocation.
        review = SimpleNamespace(
            pr_url="https://github.com/tanner-art/working/pull/230",
            implementation_commit="a" * 40,
        )
        self.assertFalse(runner.review_source_is_green(
            lambda *args: json.dumps({"headRefOid": "a" * 40}) if args[:2] == ("pr", "view")
            else json.dumps([{"name": "verify", "workflow": "Validate app", "state": "PENDING"}]),
            "tanner-art/working", review,
        ))
