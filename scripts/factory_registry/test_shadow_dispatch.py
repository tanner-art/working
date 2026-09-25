from __future__ import annotations

import copy
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from scripts.factory_registry.models import DispatchSnapshot
from scripts.factory_registry.shadow_dispatch import (
    Assignment,
    DifferenceClassification,
    LegacyObservation,
    RejectionCode,
    ShadowDispatchError,
    compare_with_legacy,
    decide_shadow,
    run_required_shadow_harness,
    simulate_outcome,
    snapshot_fingerprint,
    write_shadow_harness_evidence,
)


NOW = "2026-09-24T12:00:00Z"


def package(
    package_id: str,
    *,
    priority: int = 100,
    ready_at: str = "2026-09-24T10:00:00Z",
    lane: str | None = "PLATFORM",
    capabilities: tuple[str, ...] = ("registry",),
    status: str = "READY",
    kind: str = "PARENT",
    capacity_size: str = "SUBSTANTIAL",
    capacity_risk: str = "BOUNDED",
) -> dict:
    return {
        "id": package_id,
        "feature_id": "FEATURE-1",
        "title": package_id,
        "category": "ORCHESTRATION",
        "lane": lane,
        "kind": kind,
        "capacity_size": capacity_size,
        "capacity_risk": capacity_risk,
        "required_capabilities": list(capabilities),
        "priority": priority,
        "acceptance_criteria": ["evidence"],
        "status": status,
        "provider_diagnostics": {},
        "ready_at": ready_at,
        "created_at": ready_at,
    }


def worker(
    worker_id: str,
    *,
    capabilities: tuple[str, ...] = ("registry",),
    lanes: tuple[str, ...] = ("PLATFORM",),
    role: str = "WORKER",
    availability: str = "IDLE",
    heartbeat: str = "2026-09-24T11:59:00Z",
    provider: str = "provider-a",
    capacity_scopes: tuple[str, ...] = ("default",),
    capacity_mode: str = "percentage",
) -> dict:
    return {
        "id": worker_id,
        "display_name": worker_id,
        "role": role,
        "availability": availability,
        "capabilities": list(capabilities),
        "approved_lanes": list(lanes),
        "provider_diagnostics": {"provider": provider, "model": "diagnostic-only"},
        "capacity_scopes": list(capacity_scopes),
        "capacity_mode": capacity_mode,
        "last_heartbeat_at": heartbeat,
        "usage_state": "GREEN",
    }


def usage(
    worker_id: str,
    *,
    observed_at: str = "2026-09-24T11:58:00Z",
    consumed: float = 10,
    state: str = "GREEN",
    scope: str = "default",
) -> dict:
    return {
        "id": f"usage-{worker_id}-{scope}-{observed_at}",
        "worker_id": worker_id,
        "observed_at": observed_at,
        "reset_at": "2026-09-25T00:00:00Z",
        "consumed_percent": consumed,
        "state": state,
        "capacity_mode": "percentage",
        "capacity_scope": scope,
        "provider_diagnostics": {"provider": "diagnostic-only"},
    }


def snapshot(
    *,
    packages: tuple[dict, ...] = (),
    workers: tuple[dict, ...] = (),
    dependencies: tuple[dict, ...] = (),
    leases: tuple[dict, ...] = (),
    usages: tuple[dict, ...] | None = None,
    observed_at: str = NOW,
    revision: int = 7,
) -> DispatchSnapshot:
    orchestra = worker("orchestra", role="ORCHESTRA", capabilities=(), lanes=())
    all_workers = workers + (orchestra,)
    all_usages = usages
    if all_usages is None:
        all_usages = tuple(usage(value["id"]) for value in all_workers)
    return DispatchSnapshot(
        revision=revision,
        observed_at=observed_at,
        active_parent_limit=3,
        orchestra_reserve_percent=20,
        features=({"id": "FEATURE-1", "priority": 100, "status": "READY"},),
        work_packages=packages,
        dependencies=dependencies,
        workers=all_workers,
        active_leases=leases,
        usage_observations=all_usages,
    )


def active_simulation_baseline() -> DispatchSnapshot:
    timestamp = "2026-09-24T12:30:00Z"
    working = worker("worker", availability="BUSY", heartbeat=timestamp)
    orchestra = worker(
        "orchestra", role="ORCHESTRA", capabilities=(), lanes=(), heartbeat=timestamp
    )
    return DispatchSnapshot(
        revision=20,
        observed_at=timestamp,
        active_parent_limit=3,
        orchestra_reserve_percent=20,
        features=(),
        work_packages=(
            package("active", status="ACTIVE"),
            package("dependent"),
        ),
        dependencies=({"package_id": "dependent", "dependency_id": "active"},),
        workers=(working, orchestra),
        active_leases=(
            {
                "id": "lease-active",
                "package_id": "active",
                "worker_id": "worker",
                "expired": False,
            },
        ),
        usage_observations=(
            usage("worker", observed_at=timestamp),
            usage("orchestra", observed_at=timestamp),
        ),
    )


def reason_codes(evaluation) -> set[str]:
    return {value.code for value in evaluation.reasons}


class ShadowDispatchTest(unittest.TestCase):
    def test_dependency_then_priority_best_fit_oldest_and_stable_ids(self) -> None:
        packages = (
            package("blocked", priority=1000),
            package(
                "surplus-old",
                priority=500,
                ready_at="2026-09-24T09:00:00Z",
                capabilities=("registry", "extra2"),
            ),
            package("exact-new", priority=500, ready_at="2026-09-24T10:00:00Z", capabilities=("api",)),
            package("exact-old-a", priority=400, ready_at="2026-09-24T08:00:00Z"),
            package("exact-old-b", priority=400, ready_at="2026-09-24T08:00:00Z"),
            package("dependency", status="ACTIVE"),
        )
        workers = (
            worker("worker-a", capabilities=("registry", "extra", "extra2")),
            worker("worker-b", capabilities=("api",)),
            worker("worker-c", capabilities=("registry",)),
        )
        value = snapshot(
            packages=packages,
            workers=workers,
            dependencies=({"package_id": "blocked", "dependency_id": "dependency"},),
        )
        decision = decide_shadow(value)
        # Priority is first. At equal priority, exact-fit surplus 0 beats surplus 1,
        # before oldest-ready and stable IDs are considered.
        self.assertEqual(
            decision.ordered_package_ids,
            ("exact-new", "surplus-old", "exact-old-a", "exact-old-b"),
        )
        self.assertEqual(
            decision.proposed_assignments,
            (
                Assignment("exact-new", "worker-b"),
                Assignment("surplus-old", "worker-a"),
                Assignment("exact-old-a", "worker-c"),
            ),
        )
        blocked = next(value for value in decision.package_evaluations if value.id == "blocked")
        self.assertIn(RejectionCode.DEPENDENCY_BLOCKED.value, reason_codes(blocked))

    def test_capability_and_lane_are_pair_gates_with_explicit_reasons(self) -> None:
        value = snapshot(
            packages=(package("task", lane="FEATURE", capabilities=("canvas",)),),
            workers=(worker("platform", capabilities=("registry",), lanes=("PLATFORM",)),),
        )
        decision = decide_shadow(value)
        pair = next(
            value
            for value in decision.pair_evaluations
            if value.package_id == "task" and value.worker_id == "platform"
        )
        self.assertEqual(
            reason_codes(pair),
            {RejectionCode.LANE_NOT_APPROVED.value, RejectionCode.CAPABILITY_MISMATCH.value},
        )
        self.assertFalse(decision.proposed_assignments)

    def test_role_availability_heartbeat_and_usage_fail_closed(self) -> None:
        workers = (
            worker("busy", availability="BUSY"),
            worker("stale-heartbeat", heartbeat="2026-09-24T11:00:00Z"),
            worker("missing-usage"),
            worker("stale-usage"),
        )
        usages = (
            usage("busy"),
            usage("stale-heartbeat"),
            usage("stale-usage", observed_at="2026-09-24T11:00:00Z"),
            usage("orchestra"),
        )
        decision = decide_shadow(snapshot(packages=(package("task"),), workers=workers, usages=usages))
        by_id = {value.id: reason_codes(value) for value in decision.worker_evaluations}
        self.assertIn(RejectionCode.WORKER_NOT_IDLE.value, by_id["busy"])
        self.assertIn(RejectionCode.HEARTBEAT_STALE.value, by_id["stale-heartbeat"])
        self.assertIn(RejectionCode.USAGE_MISSING.value, by_id["missing-usage"])
        self.assertIn(RejectionCode.USAGE_STALE.value, by_id["stale-usage"])
        self.assertFalse(decision.proposed_assignments)

    def test_staged_capacity_uses_explicit_package_size_and_risk(self) -> None:
        packages = (
            package("substantial", priority=400),
            package("uncertain", priority=300, capacity_size="SMALL", capacity_risk="UNCERTAIN"),
            package("small", priority=200, capacity_size="SMALL"),
        )
        caution = snapshot(
            packages=packages,
            workers=(worker("worker"),),
            usages=(usage("worker", consumed=90, state="CAUTION"), usage("orchestra")),
        )
        decision = decide_shadow(caution)
        self.assertEqual(decision.proposed_assignments, (Assignment("small", "worker"),))
        pairs = {(value.package_id, value.worker_id): reason_codes(value)
                 for value in decision.pair_evaluations}
        self.assertIn(RejectionCode.CAPACITY_CAUTION_PACKAGE.value,
                      pairs[("substantial", "worker")])
        self.assertIn(RejectionCode.CAPACITY_CAUTION_PACKAGE.value,
                      pairs[("uncertain", "worker")])

    def test_hard_stop_allows_only_emergency_or_tiny_bounded_assurance(self) -> None:
        packages = (
            package("ordinary", priority=300, capacity_size="SMALL"),
            package("emergency", priority=200, capacity_risk="EMERGENCY_RECOVERY"),
            package("assurance", priority=100, lane="ASSURANCE", kind="REVIEW",
                    capacity_size="VERY_SMALL"),
        )
        value = snapshot(
            packages=packages,
            workers=(worker("worker", lanes=("PLATFORM", "ASSURANCE")),),
            usages=(usage("worker", consumed=98, state="HARD_STOP"), usage("orchestra")),
        )
        decision = decide_shadow(value)
        self.assertEqual(decision.proposed_assignments, (Assignment("emergency", "worker"),))
        ordinary = next(value for value in decision.pair_evaluations
                        if value.package_id == "ordinary" and value.worker_id == "worker")
        self.assertIn(RejectionCode.CAPACITY_STOPPED.value, reason_codes(ordinary))

    def test_healthy_provider_signal_is_eligible_without_percentage(self) -> None:
        signal = {
            "id": "signal-worker", "worker_id": "worker", "capacity_scope": "provider_signal",
            "capacity_mode": "provider_signal", "observed_at": "2026-09-24T11:58:00Z",
            "state": "NORMAL", "service_state": "healthy",
            "authentication_state": "valid", "live_invocation_state": "succeeded",
            "limit_signal": "NONE", "provider_diagnostics": {},
        }
        value = snapshot(
            packages=(package("task"),),
            workers=(worker("worker", capacity_scopes=("provider_signal",),
                            capacity_mode="provider_signal"),),
            usages=(signal, usage("orchestra")),
        )
        self.assertEqual(decide_shadow(value).proposed_assignments,
                         (Assignment("task", "worker"),))
        limited = copy.deepcopy(value)
        limited.usage_observations[0]["limit_signal"] = "RATE_LIMIT"
        limited.usage_observations[0]["state"] = "HARD_STOP"
        decision = decide_shadow(limited)
        worker_eval = next(item for item in decision.worker_evaluations if item.id == "worker")
        self.assertIn(RejectionCode.PROVIDER_LIMIT_SIGNAL.value, reason_codes(worker_eval))

    def test_nonexpired_lease_rejects_worker_even_when_marked_idle(self) -> None:
        value = snapshot(
            packages=(package("active", status="ACTIVE"), package("next")),
            workers=(worker("worker", availability="IDLE"),),
            leases=(
                {
                    "id": "lease",
                    "package_id": "active",
                    "worker_id": "worker",
                    "expired": False,
                },
            ),
        )
        decision = decide_shadow(value)
        evaluation = next(item for item in decision.worker_evaluations if item.id == "worker")
        self.assertIn(RejectionCode.WORKER_HAS_ACTIVE_LEASE.value, reason_codes(evaluation))
        self.assertFalse(decision.proposed_assignments)

    def test_all_expected_capacity_scopes_must_be_fresh_and_reserve_is_strict(self) -> None:
        orchestra = worker(
            "orchestra",
            role="ORCHESTRA",
            capabilities=(),
            lanes=(),
            capacity_scopes=("five-hour", "weekly"),
        )
        value = DispatchSnapshot(
            revision=1,
            observed_at=NOW,
            active_parent_limit=3,
            orchestra_reserve_percent=20,
            features=(),
            work_packages=(package("task"),),
            dependencies=(),
            workers=(worker("worker"), orchestra),
            active_leases=(),
            usage_observations=(
                usage("worker"),
                usage("orchestra", scope="five-hour", consumed=81),
            ),
        )
        decision = decide_shadow(value)
        self.assertEqual(
            {value.code for value in decision.global_rejections},
            {
                RejectionCode.ORCHESTRA_CAPACITY_RISK.value,
                RejectionCode.ORCHESTRA_USAGE_MISSING.value,
            },
        )
        self.assertFalse(decision.proposed_assignments)

    def test_unconfigured_retired_and_fresh_capacity_scopes_are_ignored(self) -> None:
        value = snapshot(
            packages=(package("task"),),
            workers=(worker("worker", capacity_scopes=("weekly",)),),
            usages=(
                usage("worker", scope="weekly"),
                usage("worker", scope="retired", observed_at="2026-09-20T00:00:00Z"),
                usage("worker", scope="unexpected-fresh", consumed=99),
                usage("orchestra"),
            ),
        )
        decision = decide_shadow(value)
        self.assertEqual(decision.proposed_assignments, (Assignment("task", "worker"),))
        evaluation = next(item for item in decision.worker_evaluations if item.id == "worker")
        self.assertTrue(evaluation.eligible)

    def test_only_nonexpired_parent_leases_count_against_cap(self) -> None:
        packages = tuple(package(f"active-{index}", status="ACTIVE") for index in range(4)) + (
            package("next"),
        )
        leases = tuple(
            {
                "id": f"lease-{index}",
                "package_id": f"active-{index}",
                "worker_id": f"leased-{index}",
                "expired": index == 3,
            }
            for index in range(4)
        )
        workers = (worker("candidate"),) + tuple(
            worker(f"leased-{index}", availability="BUSY") for index in range(4)
        )
        decision = decide_shadow(snapshot(packages=packages, workers=workers, leases=leases))
        self.assertEqual(decision.active_parent_count, 3)
        self.assertIn(
            RejectionCode.EXPIRED_LEASE_REQUIRES_RECONCILIATION.value,
            {value.code for value in decision.global_rejections},
        )
        self.assertFalse(decision.proposed_assignments)

        no_expired = replace(
            snapshot(
                packages=packages[:3] + (package("next"), package("review", kind="REVIEW")),
                workers=workers,
                leases=leases[:3],
            ),
            active_leases=leases[:3],
        )
        capped = decide_shadow(no_expired)
        self.assertEqual(capped.active_parent_count, 3)
        self.assertEqual(capped.proposed_assignments, (Assignment("review", "candidate"),))
        candidate = next(
            value
            for value in capped.pair_evaluations
            if value.package_id == "next" and value.worker_id == "candidate"
        )
        self.assertIn(RejectionCode.ACTIVE_PARENT_LIMIT.value, reason_codes(candidate))

    def test_orphan_and_duplicate_active_leases_fail_closed_and_count_conservatively(self) -> None:
        leases = (
            {"id": "duplicate", "package_id": "orphan-1", "worker_id": "ghost-1", "expired": False},
            {"id": "duplicate", "package_id": "orphan-2", "worker_id": "ghost-2", "expired": False},
            {"id": "lease-3", "package_id": "orphan-2", "worker_id": "ghost-2", "expired": False},
        )
        decision = decide_shadow(
            snapshot(packages=(package("next"),), workers=(worker("candidate"),), leases=leases)
        )
        codes = {value.code for value in decision.global_rejections}
        self.assertEqual(decision.active_parent_count, 3)
        self.assertIn(RejectionCode.LEASE_ID_DUPLICATE.value, codes)
        self.assertIn(RejectionCode.LEASE_PACKAGE_ORPHAN.value, codes)
        self.assertIn(RejectionCode.LEASE_PACKAGE_DUPLICATE.value, codes)
        self.assertIn(RejectionCode.LEASE_WORKER_ORPHAN.value, codes)
        self.assertIn(RejectionCode.LEASE_WORKER_DUPLICATE.value, codes)
        self.assertFalse(decision.proposed_assignments)

    def test_invalid_timestamps_are_explicit_rejections(self) -> None:
        bad_package = package("task", ready_at="not-a-time")
        bad_worker = worker("worker", heartbeat="not-a-time")
        value = snapshot(
            packages=(bad_package,),
            workers=(bad_worker,),
            usages=(
                usage("worker", observed_at="not-a-time"),
                usage("orchestra"),
            ),
        )
        decision = decide_shadow(value)
        package_evaluation = next(
            item for item in decision.package_evaluations if item.id == "task"
        )
        worker_evaluation = next(
            item for item in decision.worker_evaluations if item.id == "worker"
        )
        self.assertIn(
            RejectionCode.PACKAGE_READY_TIME_INVALID.value,
            reason_codes(package_evaluation),
        )
        self.assertIn(RejectionCode.HEARTBEAT_INVALID.value, reason_codes(worker_evaluation))
        self.assertIn(RejectionCode.USAGE_INVALID.value, reason_codes(worker_evaluation))

    def test_ready_package_in_the_future_is_rejected(self) -> None:
        value = snapshot(
            packages=(package("future", ready_at="2026-09-24T12:00:01Z"),),
            workers=(worker("worker"),),
        )
        decision = decide_shadow(value)
        evaluation = next(item for item in decision.package_evaluations if item.id == "future")
        self.assertIn(RejectionCode.PACKAGE_NOT_YET_READY.value, reason_codes(evaluation))
        self.assertFalse(decision.proposed_assignments)

    def test_provider_and_model_diagnostics_cannot_change_decision(self) -> None:
        base = snapshot(packages=(package("task"),), workers=(worker("worker"),))
        altered = copy.deepcopy(base)
        altered.workers[0]["provider_diagnostics"] = {
            "provider": "different",
            "model": "much-more-expensive",
            "preferred": True,
        }
        altered.work_packages[0]["provider_diagnostics"] = {"provider": "another"}
        altered.usage_observations[0]["provider_diagnostics"] = {"provider": "changed"}
        self.assertEqual(decide_shadow(base).to_json(), decide_shadow(altered).to_json())

    def test_decision_is_byte_deterministic_and_input_is_not_mutated(self) -> None:
        value = snapshot(
            packages=(package("b"), package("a")),
            workers=(worker("worker-b"), worker("worker-a")),
        )
        before = snapshot_fingerprint(value)
        first = decide_shadow(value)
        second = decide_shadow(value)
        self.assertEqual(first.to_json(), second.to_json())
        self.assertEqual(first.decision_id, second.decision_id)
        self.assertEqual(before, snapshot_fingerprint(value))
        self.assertEqual(json.loads(first.to_json())["mode"], "SHADOW")

    def test_legacy_differences_default_unresolved_and_fail_gate(self) -> None:
        decision = decide_shadow(
            snapshot(packages=(package("task"),), workers=(worker("worker"),))
        )
        legacy = LegacyObservation("runner", NOW, (), complete=True)
        comparison = compare_with_legacy(decision, legacy)
        self.assertFalse(comparison.gate_passed)
        self.assertEqual(
            comparison.differences[0].classification,
            DifferenceClassification.UNRESOLVED,
        )
        approved = compare_with_legacy(
            decision,
            legacy,
            classifications={
                "SHADOW_ONLY:task:worker": DifferenceClassification.INTENDED,
            },
        )
        self.assertTrue(approved.gate_passed)

    def test_legacy_comparison_detects_assignment_order_and_duplicates(self) -> None:
        decision = decide_shadow(
            snapshot(
                packages=(package("a"), package("b")),
                workers=(worker("a-worker"), worker("b-worker")),
            )
        )
        reversed_legacy = LegacyObservation(
            "runner", NOW, tuple(reversed(decision.proposed_assignments))
        )
        comparison = compare_with_legacy(decision, reversed_legacy)
        self.assertEqual(comparison.differences[0].kind, "ASSIGNMENT_ORDER")
        self.assertFalse(comparison.gate_passed)

        duplicated = LegacyObservation(
            "runner",
            NOW,
            decision.proposed_assignments + (decision.proposed_assignments[0],),
        )
        duplicate_comparison = compare_with_legacy(decision, duplicated)
        self.assertIn(
            "LEGACY_DUPLICATE_ASSIGNMENT",
            {value.kind for value in duplicate_comparison.differences},
        )

    def test_legacy_observation_must_be_time_aligned(self) -> None:
        decision = decide_shadow(
            snapshot(packages=(package("task"),), workers=(worker("worker"),))
        )
        cases = (
            ("2026-09-24T11:58:59Z", "LEGACY_OBSERVATION_STALE"),
            ("2026-09-24T12:01:01Z", "LEGACY_OBSERVATION_IN_FUTURE"),
            ("not-a-time", "LEGACY_OBSERVATION_TIME_INVALID"),
        )
        for observed_at, expected_kind in cases:
            with self.subTest(observed_at=observed_at):
                comparison = compare_with_legacy(
                    decision,
                    LegacyObservation(
                        "runner", observed_at, decision.proposed_assignments
                    ),
                    classifications={
                        f"{expected_kind}:-:-": DifferenceClassification.INTENDED,
                    },
                )
                self.assertFalse(comparison.gate_passed)
                self.assertIn(expected_kind, {value.kind for value in comparison.differences})
                aligned_failure = next(
                    value for value in comparison.differences if value.kind == expected_kind
                )
                self.assertEqual(
                    aligned_failure.classification,
                    DifferenceClassification.UNRESOLVED,
                )

    def test_completion_and_failure_simulations_are_in_memory(self) -> None:
        active_package = package("active", status="ACTIVE")
        dependent = package("dependent")
        active_worker = worker("worker", availability="BUSY")
        lease = {"id": "lease", "package_id": "active", "worker_id": "worker", "expired": False}
        value = snapshot(
            packages=(active_package, dependent),
            workers=(active_worker,),
            dependencies=({"package_id": "dependent", "dependency_id": "active"},),
            leases=(lease,),
        )
        before = snapshot_fingerprint(value)
        completed = simulate_outcome(
            value,
            package_id="active",
            worker_id="worker",
            outcome="COMPLETED",
            observed_at="2026-09-24T12:01:00Z",
        )
        failed = simulate_outcome(
            value,
            package_id="active",
            worker_id="worker",
            outcome="FAILED",
            observed_at="2026-09-24T12:01:00Z",
        )
        self.assertEqual(before, snapshot_fingerprint(value))
        self.assertEqual(completed.work_packages[0]["status"], "DONE")
        self.assertEqual(failed.work_packages[0]["status"], "BLOCKED")
        self.assertFalse(completed.active_leases)
        self.assertFalse(failed.active_leases)

    def test_required_harness_runs_three_sweeps_completion_and_failure(self) -> None:
        scheduled = []
        for index, timestamp in enumerate(
            (
                "2026-09-24T12:00:00Z",
                "2026-09-24T12:15:00Z",
                "2026-09-24T12:30:00Z",
            )
        ):
            working = worker("worker", heartbeat=timestamp)
            orchestra = worker(
                "orchestra", role="ORCHESTRA", capabilities=(), lanes=(), heartbeat=timestamp
            )
            value = DispatchSnapshot(
                revision=10 + index,
                observed_at=timestamp,
                active_parent_limit=3,
                orchestra_reserve_percent=20,
                features=(),
                work_packages=(package("task"),),
                dependencies=(),
                workers=(working, orchestra),
                active_leases=(),
                usage_observations=(
                    usage("worker", observed_at=timestamp),
                    usage("orchestra", observed_at=timestamp),
                ),
            )
            scheduled.append(
                (value, LegacyObservation("runner", timestamp, (Assignment("task", "worker"),)))
            )
        baseline = active_simulation_baseline()
        evidence = run_required_shadow_harness(
            scheduled,
            baseline,
            Assignment("active", "worker"),
            LegacyObservation(
                "runner",
                "2026-09-24T12:31:00Z",
                (Assignment("dependent", "worker"),),
            ),
            LegacyObservation("runner", "2026-09-24T12:31:00Z", ()),
            completion_observed_at="2026-09-24T12:31:00Z",
            failure_observed_at="2026-09-24T12:31:00Z",
        )
        self.assertTrue(evidence.passed)
        self.assertEqual(len(evidence.scheduled_sweeps), 3)
        self.assertEqual(len(evidence.comparisons), 5)
        self.assertTrue(evidence.completion_simulation.matching_lease_removed)
        self.assertEqual(evidence.completion_simulation.package_status, "DONE")
        self.assertEqual(evidence.failure_simulation.package_status, "BLOCKED")
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "shadow-evidence.json"
            self.assertEqual(write_shadow_harness_evidence(evidence, destination), destination)
            persisted = json.loads(destination.read_text())
            self.assertTrue(persisted["passed"])
            with self.assertRaises(FileExistsError):
                write_shadow_harness_evidence(evidence, destination)

    def test_harness_requires_exact_sweep_count(self) -> None:
        value = snapshot(packages=(package("task"),), workers=(worker("worker"),))
        observed = LegacyObservation("runner", NOW, (Assignment("task", "worker"),))
        with self.assertRaisesRegex(ShadowDispatchError, "exactly three"):
            run_required_shadow_harness(
                ((value, observed),),
                active_simulation_baseline(),
                Assignment("active", "worker"),
                observed,
                observed,
                completion_observed_at="2026-09-24T12:31:00Z",
                failure_observed_at="2026-09-24T12:31:00Z",
            )

    def test_harness_rejects_unchanged_ready_simulation_baseline(self) -> None:
        scheduled = []
        for timestamp in (
            "2026-09-24T12:00:00Z",
            "2026-09-24T12:15:00Z",
            "2026-09-24T12:30:00Z",
        ):
            value = replace(
                snapshot(packages=(package("task"),), workers=(worker("worker"),)),
                observed_at=timestamp,
            )
            scheduled.append(
                (value, LegacyObservation("runner", timestamp, (Assignment("task", "worker"),)))
            )
        ready_baseline = scheduled[-1][0]
        with self.assertRaisesRegex(ShadowDispatchError, "must be ACTIVE"):
            run_required_shadow_harness(
                scheduled,
                ready_baseline,
                Assignment("task", "worker"),
                LegacyObservation("runner", "2026-09-24T12:31:00Z", ()),
                LegacyObservation("runner", "2026-09-24T12:31:00Z", ()),
                completion_observed_at="2026-09-24T12:31:00Z",
                failure_observed_at="2026-09-24T12:31:00Z",
            )

    def test_harness_fails_when_a_sweep_has_a_global_rejection(self) -> None:
        value = snapshot(
            packages=(package("task"),),
            workers=(worker("worker"),),
            usages=(usage("worker"),),
        )
        observed = LegacyObservation("runner", NOW, ())
        second = replace(value, observed_at="2026-09-24T12:15:00Z")
        third = replace(value, observed_at="2026-09-24T12:30:00Z")
        baseline = active_simulation_baseline()
        evidence = run_required_shadow_harness(
            ((value, observed), (second, observed), (third, observed)),
            baseline,
            Assignment("active", "worker"),
            LegacyObservation(
                "runner",
                "2026-09-24T12:31:00Z",
                (Assignment("dependent", "worker"),),
            ),
            LegacyObservation("runner", "2026-09-24T12:31:00Z", ()),
            completion_observed_at="2026-09-24T12:31:00Z",
            failure_observed_at="2026-09-24T12:31:00Z",
        )
        self.assertFalse(evidence.passed)
        self.assertTrue(any("global rejections" in failure for failure in evidence.failures))


if __name__ == "__main__":
    unittest.main()
