import unittest
from dataclasses import replace

from scripts.factory_registry.controlled_restart import (
    ActiveOwnership,
    AttemptOutcome,
    AttemptState,
    ControlledRestartError,
    ControlledRestartProcedure,
    PreservationState,
    RecoveryRequired,
    RecoveryResult,
    RestartPhase,
    RestartSnapshot,
)


NOW = "2026-09-25T12:00:00Z"
LATER = "2026-09-25T12:10:00Z"


PRESERVATION = PreservationState(
    source_sha256="reviewed-evidence-sha256",
    worktree_count=33,
    dirty_worktree_count=8,
    unmerged_branch_count=7,
    unexplained_record_count=0,
    active_stale_lease_count=0,
    clean=True,
)


def ownership(
    lease_id="lease-1",
    package_id="package-1",
    worker_id="worker-a",
    attempt_id="attempt-1",
    expires_at="2026-09-25T12:05:00Z",
):
    return ActiveOwnership(lease_id, package_id, worker_id, attempt_id, expires_at)


class FakeRegistry:
    def __init__(self, log):
        self.log = log
        self.revision = 1
        self.phase = RestartPhase.PAUSED
        self.kill_switch_engaged = True
        self.preservation = PRESERVATION
        self.ownership = []
        self.attempts = {}
        self.workers = {"worker-a": "IDLE", "worker-b": "IDLE"}
        self.packages = {}
        self.unresolved = set()

    def seed_active(self, item):
        self.ownership.append(item)
        if item.attempt_id:
            self.attempts[item.attempt_id] = AttemptState(
                item.attempt_id,
                item.package_id,
                item.worker_id,
                AttemptOutcome.ACTIVE,
                None,
            )
        self.packages[item.package_id] = "ACTIVE"

    def restart_snapshot(self, *, observed_at):
        return RestartSnapshot(
            revision=self.revision,
            observed_at=observed_at,
            phase=self.phase,
            kill_switch_engaged=self.kill_switch_engaged,
            ownership=tuple(self.ownership),
            attempts=tuple(self.attempts.values()),
            worker_availability=dict(self.workers),
            package_states=dict(self.packages),
        )

    def reconcile_preservation(self, *, observed_at):
        self.log.append("registry:preservation")
        return self.preservation

    def enable_live(self, *, expected_revision, expected_phase, changed_at, reason):
        if self.revision != expected_revision or self.phase != expected_phase:
            raise ControlledRestartError("compare-and-swap rejected")
        self.phase = RestartPhase.LIVE
        self.kill_switch_engaged = False
        self._mutate("registry:live")
        return self.restart_snapshot(observed_at=changed_at)

    def engage_kill_switch(self, *, changed_at, reason):
        self.phase = RestartPhase.STOPPING
        self.kill_switch_engaged = True
        self._mutate("registry:kill")
        return self.restart_snapshot(observed_at=changed_at)

    def reconcile_stopped_ownership(self, owned, *, observed_at, reason):
        self.log.append("registry:reconcile-stopped")
        result = self._reconcile(item.lease_id for item in owned)
        self._mutate()
        return result

    def expire_leases(self, *, observed_at):
        self.log.append("registry:expire")
        result = self._reconcile(
            item.lease_id for item in self.ownership if item.expires_at <= observed_at
        )
        self._mutate()
        return result

    def record_worker_disappearance(self, worker_id, *, observed_at):
        self.log.append(f"registry:worker-offline:{worker_id}")
        self.workers[worker_id] = "OFFLINE"
        result = self._reconcile(
            item.lease_id for item in self.ownership if item.worker_id == worker_id
        )
        self._mutate()
        return result

    def requeue_failed_attempt(self, attempt_id, *, observed_at):
        attempt = self.attempts[attempt_id]
        self.packages[attempt.package_id] = "READY"
        self._mutate("registry:requeue")
        return attempt.package_id

    def finalize_paused(self, *, expected_revision, changed_at, reason):
        if self.revision != expected_revision:
            raise ControlledRestartError("compare-and-swap rejected")
        if self.ownership or any(
            item.outcome == AttemptOutcome.ACTIVE and item.ended_at is None
            for item in self.attempts.values()
        ):
            raise ControlledRestartError("cannot pause with active ownership")
        self.phase = RestartPhase.PAUSED
        self.kill_switch_engaged = True
        self._mutate("registry:paused")
        return self.restart_snapshot(observed_at=changed_at)

    def _reconcile(self, lease_ids):
        lease_ids = set(lease_ids)
        released = []
        terminal = []
        blocked = []
        remaining = []
        unresolved = []
        for item in self.ownership:
            if item.lease_id not in lease_ids:
                remaining.append(item)
                continue
            if item.lease_id in self.unresolved:
                remaining.append(item)
                unresolved.append(item.lease_id)
                continue
            released.append(item.lease_id)
            if item.attempt_id:
                attempt = self.attempts[item.attempt_id]
                self.attempts[item.attempt_id] = replace(
                    attempt, outcome=AttemptOutcome.FAILED, ended_at=NOW
                )
                terminal.append(item.attempt_id)
            self.packages[item.package_id] = "BLOCKED"
            blocked.append(item.package_id)
        self.ownership = remaining
        return RecoveryResult(
            tuple(released), tuple(terminal), tuple(blocked), tuple(unresolved)
        )

    def _mutate(self, event=None):
        self.revision += 1
        if event:
            self.log.append(event)


class FakeSupervisor:
    def __init__(self, log):
        self.log = log
        self.fail_enable = False
        self.fail_disable = False
        self.fail_termination = set()

    def prepare(self):
        self.log.append("supervisor:prepare")

    def enable_claims(self, *, registry_revision):
        self.log.append(f"supervisor:enable:{registry_revision}")
        if self.fail_enable:
            raise RuntimeError("start failed")

    def disable_claims(self):
        self.log.append("supervisor:disable")
        if self.fail_disable:
            raise RuntimeError("stop failed")

    def terminate_attempt(self, attempt_id):
        self.log.append(f"supervisor:terminate:{attempt_id}")
        if attempt_id in self.fail_termination:
            raise RuntimeError("termination failed")


class ControlledRestartTests(unittest.TestCase):
    def setUp(self):
        self.log = []
        self.registry = FakeRegistry(self.log)
        self.supervisor = FakeSupervisor(self.log)
        self.procedure = ControlledRestartProcedure(self.registry, self.supervisor)

    def test_enable_is_preservation_gated_and_revision_pinned(self):
        result = self.procedure.enable_live(
            observed_at=NOW,
            expected_preservation=PRESERVATION,
            reason="owner-approved bounded canary",
        )

        self.assertEqual(RestartPhase.LIVE, result.phase)
        self.assertEqual(
            [
                "registry:preservation",
                "supervisor:prepare",
                "registry:live",
                f"supervisor:enable:{result.registry_revision}",
            ],
            self.log,
        )
        self.assertFalse(self.registry.kill_switch_engaged)

    def test_enable_rejects_changed_preservation_before_runtime_prepare(self):
        self.registry.preservation = replace(PRESERVATION, dirty_worktree_count=9)

        with self.assertRaisesRegex(
            ControlledRestartError, "preservation evidence changed"
        ):
            self.procedure.enable_live(
                observed_at=NOW,
                expected_preservation=PRESERVATION,
                reason="canary",
            )

        self.assertEqual(["registry:preservation"], self.log)
        self.assertEqual(RestartPhase.PAUSED, self.registry.phase)

    def test_enable_rejects_an_active_attempt_without_a_lease(self):
        self.registry.attempts["orphan-attempt"] = AttemptState(
            "orphan-attempt", "package-1", "worker-a", AttemptOutcome.ACTIVE, None
        )

        with self.assertRaises(RecoveryRequired) as raised:
            self.procedure.enable_live(
                observed_at=NOW,
                expected_preservation=PRESERVATION,
                reason="canary",
            )

        self.assertEqual(("attempt:orphan-attempt",), raised.exception.ownership_ids)
        self.assertNotIn("supervisor:prepare", self.log)

    def test_enable_failure_rolls_back_to_paused(self):
        self.supervisor.fail_enable = True

        with self.assertRaisesRegex(ControlledRestartError, "rolled back to paused"):
            self.procedure.enable_live(
                observed_at=NOW,
                expected_preservation=PRESERVATION,
                reason="canary",
            )

        self.assertEqual(RestartPhase.PAUSED, self.registry.phase)
        self.assertTrue(self.registry.kill_switch_engaged)
        self.assertLess(self.log.index("registry:kill"), self.log.index("supervisor:disable"))

    def test_enable_and_automatic_stop_failure_remain_explicitly_stopping(self):
        self.supervisor.fail_enable = True
        self.supervisor.fail_disable = True

        with self.assertRaisesRegex(RecoveryRequired, "automatic startup rollback"):
            self.procedure.enable_live(
                observed_at=NOW,
                expected_preservation=PRESERVATION,
                reason="canary",
            )

        self.assertEqual(RestartPhase.STOPPING, self.registry.phase)
        self.assertTrue(self.registry.kill_switch_engaged)
        self.assertNotIn("registry:paused", self.log)

    def test_immediate_stop_kills_first_then_reconciles_and_pauses(self):
        self.registry.phase = RestartPhase.LIVE
        self.registry.kill_switch_engaged = False
        self.registry.seed_active(ownership())

        result = self.procedure.immediate_stop(observed_at=NOW, reason="operator stop")

        self.assertEqual(RestartPhase.PAUSED, result.phase)
        self.assertEqual((), tuple(self.registry.ownership))
        self.assertEqual(AttemptOutcome.FAILED, self.registry.attempts["attempt-1"].outcome)
        self.assertEqual("BLOCKED", self.registry.packages["package-1"])
        self.assertLess(self.log.index("registry:kill"), self.log.index("supervisor:disable"))
        self.assertLess(
            self.log.index("supervisor:terminate:attempt-1"),
            self.log.index("registry:reconcile-stopped"),
        )
        self.assertEqual("registry:paused", self.log[-1])

    def test_termination_failure_leaves_kill_engaged_and_ownership_explicit(self):
        self.registry.phase = RestartPhase.LIVE
        self.registry.kill_switch_engaged = False
        self.registry.seed_active(ownership())
        self.supervisor.fail_termination.add("attempt-1")

        with self.assertRaises(RecoveryRequired) as raised:
            self.procedure.immediate_stop(observed_at=NOW, reason="operator stop")

        self.assertEqual(("lease-1",), raised.exception.ownership_ids)
        self.assertEqual(RestartPhase.STOPPING, self.registry.phase)
        self.assertTrue(self.registry.kill_switch_engaged)
        self.assertEqual(["lease-1"], [item.lease_id for item in self.registry.ownership])
        self.assertNotIn("registry:paused", self.log)

    def test_lease_expiry_stops_runtime_reconciles_and_pauses(self):
        self.registry.phase = RestartPhase.LIVE
        self.registry.kill_switch_engaged = False
        self.registry.seed_active(ownership(expires_at="2026-09-25T11:59:59Z"))

        result = self.procedure.handle_lease_expiry(observed_at=NOW)

        self.assertEqual(RestartPhase.PAUSED, result.phase)
        self.assertEqual(("lease-1",), result.recovery.released_lease_ids)
        self.assertLess(self.log.index("registry:kill"), self.log.index("supervisor:disable"))
        self.assertLess(
            self.log.index("supervisor:terminate:attempt-1"), self.log.index("registry:expire")
        )

    def test_unresolved_lease_expiry_fails_closed(self):
        self.registry.phase = RestartPhase.LIVE
        self.registry.kill_switch_engaged = False
        self.registry.seed_active(ownership(expires_at="2026-09-25T11:59:59Z"))
        self.registry.unresolved.add("lease-1")

        with self.assertRaises(RecoveryRequired) as raised:
            self.procedure.handle_lease_expiry(observed_at=NOW)

        self.assertEqual(("lease-1",), raised.exception.ownership_ids)
        self.assertTrue(self.registry.kill_switch_engaged)
        self.assertEqual(RestartPhase.STOPPING, self.registry.phase)

    def test_failed_attempt_requeue_preserves_terminal_history(self):
        self.registry.attempts["attempt-1"] = AttemptState(
            "attempt-1", "package-1", "worker-a", AttemptOutcome.FAILED, NOW
        )
        self.registry.packages["package-1"] = "BLOCKED"

        result = self.procedure.recover_failed_attempt("attempt-1", observed_at=LATER)

        self.assertEqual(RestartPhase.PAUSED, result.phase)
        self.assertEqual("READY", self.registry.packages["package-1"])
        self.assertEqual(AttemptOutcome.FAILED, self.registry.attempts["attempt-1"].outcome)
        self.assertEqual(NOW, self.registry.attempts["attempt-1"].ended_at)

    def test_failed_attempt_with_lease_cannot_be_requeued(self):
        item = ownership(expires_at="2026-09-25T12:20:00Z")
        self.registry.seed_active(item)
        self.registry.attempts["attempt-1"] = replace(
            self.registry.attempts["attempt-1"],
            outcome=AttemptOutcome.FAILED,
            ended_at=NOW,
        )

        with self.assertRaises(RecoveryRequired) as raised:
            self.procedure.recover_failed_attempt("attempt-1", observed_at=LATER)

        self.assertEqual(("lease-1",), raised.exception.ownership_ids)
        self.assertEqual("ACTIVE", self.registry.packages["package-1"])

    def test_worker_disappearance_stops_globally_and_records_offline(self):
        self.registry.phase = RestartPhase.LIVE
        self.registry.kill_switch_engaged = False
        self.registry.seed_active(ownership())
        self.registry.seed_active(
            ownership(
                lease_id="lease-2",
                package_id="package-2",
                worker_id="worker-b",
                attempt_id="attempt-2",
            )
        )

        result = self.procedure.handle_worker_disappearance("worker-a", observed_at=NOW)

        self.assertEqual(RestartPhase.PAUSED, result.phase)
        self.assertEqual("OFFLINE", self.registry.workers["worker-a"])
        self.assertEqual((), tuple(self.registry.ownership))
        self.assertEqual(
            {"lease-1", "lease-2"}, set(result.recovery.released_lease_ids)
        )
        self.assertLess(self.log.index("registry:kill"), self.log.index("supervisor:disable"))
        self.assertLess(
            self.log.index("supervisor:terminate:attempt-1"),
            self.log.index("registry:worker-offline:worker-a"),
        )
        self.assertEqual(1, self.log.count("supervisor:terminate:attempt-1"))
        self.assertEqual(1, self.log.count("supervisor:terminate:attempt-2"))

    def test_rollback_uses_same_kill_first_stop_path(self):
        self.registry.phase = RestartPhase.LIVE
        self.registry.kill_switch_engaged = False

        result = self.procedure.rollback_to_paused(
            observed_at=NOW,
            reason="canary validation failed",
            expected_preservation=PRESERVATION,
        )

        self.assertEqual(RestartPhase.PAUSED, result.phase)
        self.assertEqual("registry:kill", self.log[0])
        self.assertEqual("supervisor:disable", self.log[1])
        self.assertEqual("registry:preservation", self.log[-1])
        self.assertEqual("preservation_reconciled", result.actions[-1])


if __name__ == "__main__":
    unittest.main()
