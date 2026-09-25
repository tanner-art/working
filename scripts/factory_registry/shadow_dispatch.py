"""Pure capability scheduler and read-only legacy comparison for shadow dispatch.

The module consumes only :class:`DispatchSnapshot`.  It has no registry write
handle, process launcher, GitHub client, queue-file writer, or lease authority.
Provider and model diagnostics are deliberately ignored by eligibility and
ordering.
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections import Counter
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .models import DispatchSnapshot


class ShadowDispatchError(ValueError):
    """Invalid or incomplete input that cannot safely produce a decision."""


class RejectionCode(str, Enum):
    PACKAGE_NOT_READY = "PACKAGE_NOT_READY"
    PACKAGE_LANE_UNASSIGNED = "PACKAGE_LANE_UNASSIGNED"
    PACKAGE_READY_TIME_INVALID = "PACKAGE_READY_TIME_INVALID"
    PACKAGE_NOT_YET_READY = "PACKAGE_NOT_YET_READY"
    DEPENDENCY_BLOCKED = "DEPENDENCY_BLOCKED"
    DEPENDENCY_MISSING = "DEPENDENCY_MISSING"
    PACKAGE_HAS_ACTIVE_LEASE = "PACKAGE_HAS_ACTIVE_LEASE"
    NO_ELIGIBLE_WORKER = "NO_ELIGIBLE_WORKER"
    WORKER_ROLE_INELIGIBLE = "WORKER_ROLE_INELIGIBLE"
    WORKER_NOT_IDLE = "WORKER_NOT_IDLE"
    WORKER_HAS_ACTIVE_LEASE = "WORKER_HAS_ACTIVE_LEASE"
    HEARTBEAT_MISSING = "HEARTBEAT_MISSING"
    HEARTBEAT_STALE = "HEARTBEAT_STALE"
    HEARTBEAT_IN_FUTURE = "HEARTBEAT_IN_FUTURE"
    HEARTBEAT_INVALID = "HEARTBEAT_INVALID"
    USAGE_MISSING = "USAGE_MISSING"
    USAGE_STALE = "USAGE_STALE"
    USAGE_IN_FUTURE = "USAGE_IN_FUTURE"
    USAGE_UNKNOWN = "USAGE_UNKNOWN"
    USAGE_INVALID = "USAGE_INVALID"
    CAPACITY_CONSTRAINED = "CAPACITY_CONSTRAINED"
    CAPACITY_STOPPED = "CAPACITY_STOPPED"
    CAPACITY_CAUTION_PACKAGE = "CAPACITY_CAUTION_PACKAGE"
    CAPACITY_CHECKPOINT_PACKAGE = "CAPACITY_CHECKPOINT_PACKAGE"
    PROVIDER_SIGNAL_UNHEALTHY = "PROVIDER_SIGNAL_UNHEALTHY"
    PROVIDER_LIMIT_SIGNAL = "PROVIDER_LIMIT_SIGNAL"
    LANE_NOT_APPROVED = "LANE_NOT_APPROVED"
    CAPABILITY_MISMATCH = "CAPABILITY_MISMATCH"
    PACKAGE_ALREADY_PROPOSED = "PACKAGE_ALREADY_PROPOSED"
    WORKER_ALREADY_PROPOSED = "WORKER_ALREADY_PROPOSED"
    ACTIVE_PARENT_LIMIT = "ACTIVE_PARENT_LIMIT"
    EXPIRED_LEASE_REQUIRES_RECONCILIATION = "EXPIRED_LEASE_REQUIRES_RECONCILIATION"
    LEASE_ID_DUPLICATE = "LEASE_ID_DUPLICATE"
    LEASE_PACKAGE_DUPLICATE = "LEASE_PACKAGE_DUPLICATE"
    LEASE_WORKER_DUPLICATE = "LEASE_WORKER_DUPLICATE"
    LEASE_PACKAGE_ORPHAN = "LEASE_PACKAGE_ORPHAN"
    LEASE_WORKER_ORPHAN = "LEASE_WORKER_ORPHAN"
    ORCHESTRA_WORKER_MISSING = "ORCHESTRA_WORKER_MISSING"
    ORCHESTRA_USAGE_MISSING = "ORCHESTRA_USAGE_MISSING"
    ORCHESTRA_USAGE_STALE = "ORCHESTRA_USAGE_STALE"
    ORCHESTRA_USAGE_IN_FUTURE = "ORCHESTRA_USAGE_IN_FUTURE"
    ORCHESTRA_USAGE_UNKNOWN = "ORCHESTRA_USAGE_UNKNOWN"
    ORCHESTRA_USAGE_INVALID = "ORCHESTRA_USAGE_INVALID"
    ORCHESTRA_CAPACITY_CONSTRAINED = "ORCHESTRA_CAPACITY_CONSTRAINED"
    ORCHESTRA_CAPACITY_RISK = "ORCHESTRA_CAPACITY_RISK"


class DifferenceClassification(str, Enum):
    INTENDED = "INTENDED"
    LEGACY_DEFECT = "LEGACY_DEFECT"
    UNRESOLVED = "UNRESOLVED"


@dataclass(frozen=True)
class ShadowPolicy:
    heartbeat_fresh_seconds: int = 180
    usage_fresh_seconds: int = 900
    scheduled_sweep_seconds: int = 900
    scheduled_sweep_tolerance_seconds: int = 60
    legacy_observation_tolerance_seconds: int = 60
    worker_caution_percent: float = 90.0
    worker_checkpoint_percent: float = 95.0
    worker_hard_stop_percent: float = 98.0

    def __post_init__(self) -> None:
        if (
            self.heartbeat_fresh_seconds <= 0
            or self.usage_fresh_seconds <= 0
            or self.scheduled_sweep_seconds <= 0
            or self.scheduled_sweep_tolerance_seconds < 0
            or self.legacy_observation_tolerance_seconds < 0
        ):
            raise ShadowDispatchError("freshness windows must be positive")
        if not (
            0 <= self.worker_caution_percent
            < self.worker_checkpoint_percent
            < self.worker_hard_stop_percent
            <= 100
        ):
            raise ShadowDispatchError("worker capacity thresholds must satisfy 0 <= caution < checkpoint < hard stop <= 100")


@dataclass(frozen=True, order=True)
class Reason:
    code: str
    detail: str = ""

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "detail": self.detail}


@dataclass(frozen=True, order=True)
class Assignment:
    package_id: str
    worker_id: str

    def as_dict(self) -> dict[str, str]:
        return {"package_id": self.package_id, "worker_id": self.worker_id}


@dataclass(frozen=True)
class EntityEvaluation:
    id: str
    eligible: bool
    reasons: tuple[Reason, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "eligible": self.eligible,
            "reasons": [reason.as_dict() for reason in self.reasons],
        }


@dataclass(frozen=True)
class PairEvaluation:
    package_id: str
    worker_id: str
    eligible: bool
    reasons: tuple[Reason, ...] = ()
    capability_surplus: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "package_id": self.package_id,
            "worker_id": self.worker_id,
            "eligible": self.eligible,
            "capability_surplus": self.capability_surplus,
            "reasons": [reason.as_dict() for reason in self.reasons],
        }


@dataclass(frozen=True)
class ShadowDecision:
    schema_version: int
    decision_id: str
    registry_revision: int
    decided_at: str
    mode: str
    global_rejections: tuple[Reason, ...]
    worker_evaluations: tuple[EntityEvaluation, ...]
    package_evaluations: tuple[EntityEvaluation, ...]
    pair_evaluations: tuple[PairEvaluation, ...]
    ordered_package_ids: tuple[str, ...]
    proposed_assignments: tuple[Assignment, ...]
    active_parent_count: int
    active_parent_limit: int
    orchestra_reserve_percent: float

    def as_dict(self, *, include_decision_id: bool = True) -> dict[str, Any]:
        result: dict[str, Any] = {
            "schema_version": self.schema_version,
            "registry_revision": self.registry_revision,
            "decided_at": self.decided_at,
            "mode": self.mode,
            "global_rejections": [reason.as_dict() for reason in self.global_rejections],
            "worker_evaluations": [value.as_dict() for value in self.worker_evaluations],
            "package_evaluations": [value.as_dict() for value in self.package_evaluations],
            "pair_evaluations": [value.as_dict() for value in self.pair_evaluations],
            "ordered_package_ids": list(self.ordered_package_ids),
            "proposed_assignments": [value.as_dict() for value in self.proposed_assignments],
            "active_parent_count": self.active_parent_count,
            "active_parent_limit": self.active_parent_limit,
            "orchestra_reserve_percent": self.orchestra_reserve_percent,
        }
        if include_decision_id:
            result["decision_id"] = self.decision_id
        return result

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), separators=(",", ":"), sort_keys=True)


@dataclass(frozen=True)
class LegacyObservation:
    """Read-only description of the legacy runner's observable choice."""

    source: str
    observed_at: str
    assignments: tuple[Assignment, ...]
    complete: bool = True


@dataclass(frozen=True)
class LegacyDifference:
    id: str
    kind: str
    package_id: str | None
    worker_id: str | None
    classification: DifferenceClassification
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "package_id": self.package_id,
            "worker_id": self.worker_id,
            "classification": self.classification.value,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class LegacyComparison:
    decision_id: str
    legacy_source: str
    legacy_observed_at: str
    matched: bool
    gate_passed: bool
    differences: tuple[LegacyDifference, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "legacy_source": self.legacy_source,
            "legacy_observed_at": self.legacy_observed_at,
            "matched": self.matched,
            "gate_passed": self.gate_passed,
            "differences": [difference.as_dict() for difference in self.differences],
        }


@dataclass(frozen=True)
class OutcomeSimulationEvidence:
    outcome: str
    package_id: str
    worker_id: str
    baseline_revision: int
    simulated_revision: int
    baseline_observed_at: str
    simulated_observed_at: str
    package_status: str
    worker_availability: str
    matching_lease_removed: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome,
            "package_id": self.package_id,
            "worker_id": self.worker_id,
            "baseline_revision": self.baseline_revision,
            "simulated_revision": self.simulated_revision,
            "baseline_observed_at": self.baseline_observed_at,
            "simulated_observed_at": self.simulated_observed_at,
            "package_status": self.package_status,
            "worker_availability": self.worker_availability,
            "matching_lease_removed": self.matching_lease_removed,
        }


@dataclass(frozen=True)
class ShadowHarnessEvidence:
    scheduled_sweeps: tuple[ShadowDecision, ...]
    completion_sweep: ShadowDecision
    failure_sweep: ShadowDecision
    completion_simulation: OutcomeSimulationEvidence
    failure_simulation: OutcomeSimulationEvidence
    comparisons: tuple[LegacyComparison, ...]
    passed: bool
    failures: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "scheduled_sweeps": [value.as_dict() for value in self.scheduled_sweeps],
            "completion_sweep": self.completion_sweep.as_dict(),
            "failure_sweep": self.failure_sweep.as_dict(),
            "completion_simulation": self.completion_simulation.as_dict(),
            "failure_simulation": self.failure_simulation.as_dict(),
            "comparisons": [value.as_dict() for value in self.comparisons],
            "passed": self.passed,
            "failures": list(self.failures),
        }

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), separators=(",", ":"), sort_keys=True)


def _parse_time(value: Any, *, field_name: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ShadowDispatchError(f"{field_name} must be a timezone-aware timestamp")
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as error:
        raise ShadowDispatchError(f"invalid {field_name}: {value}") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ShadowDispatchError(f"{field_name} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _canonical_time(value: Any, *, field_name: str) -> str:
    return _parse_time(value, field_name=field_name).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _age_seconds(earlier: Any, later: datetime, *, field_name: str) -> float:
    return (later - _parse_time(earlier, field_name=field_name)).total_seconds()


def _reason(code: RejectionCode, detail: str = "") -> Reason:
    return Reason(code.value, detail)


def _latest_usage_by_scope(
    snapshot: DispatchSnapshot,
    worker_id: str,
    expected_scopes: Iterable[str],
) -> dict[str, Mapping[str, Any]]:
    configured_scopes = {str(value) for value in expected_scopes}
    observations = [
        value
        for value in snapshot.usage_observations
        if value.get("worker_id") == worker_id
        and str(value.get("capacity_scope") or "default") in configured_scopes
    ]
    latest: dict[str, Mapping[str, Any]] = {}
    for value in observations:
        scope = str(value.get("capacity_scope") or "default")
        incumbent = latest.get(scope)

        def sort_key(observation: Mapping[str, Any]) -> tuple[int, str, str]:
            try:
                stamp = _canonical_time(
                    observation.get("observed_at"), field_name="usage observed_at"
                )
                return (0, stamp, str(observation.get("id", "")))
            except ShadowDispatchError:
                # Malformed evidence wins the latest selection and therefore
                # fails closed with an explicit USAGE_INVALID reason.
                return (1, str(observation.get("observed_at", "")), str(observation.get("id", "")))

        if incumbent is None or sort_key(value) > sort_key(incumbent):
            latest[scope] = value
    return latest


def _usage_reasons(
    snapshot: DispatchSnapshot,
    worker_id: str,
    observed_at: datetime,
    policy: ShadowPolicy,
    *,
    orchestra: bool,
    expected_scopes: Iterable[str] = ("default",),
    capacity_mode: str = "percentage",
) -> tuple[Reason, ...]:
    prefix = "ORCHESTRA_" if orchestra else ""
    scopes = sorted({str(value) for value in expected_scopes})
    latest = _latest_usage_by_scope(snapshot, worker_id, scopes)
    reasons: list[Reason] = []
    for scope in scopes:
        usage = latest.get(scope)
        if usage is None:
            reasons.append(_reason(RejectionCode[f"{prefix}USAGE_MISSING"], f"scope={scope}"))
            continue
        try:
            age = _age_seconds(
                usage.get("observed_at"), observed_at, field_name="usage observed_at"
            )
        except ShadowDispatchError as error:
            code = (
                RejectionCode.ORCHESTRA_USAGE_INVALID if orchestra else RejectionCode.USAGE_INVALID
            )
            reasons.append(_reason(code, f"scope={scope} {error}"))
            continue
        if age < 0:
            code = (
                RejectionCode.ORCHESTRA_USAGE_IN_FUTURE
                if orchestra else RejectionCode.USAGE_IN_FUTURE
            )
            reasons.append(_reason(code, f"scope={scope} future={abs(age):.6f}s"))
            continue
        if age > policy.usage_fresh_seconds:
            code = RejectionCode.ORCHESTRA_USAGE_STALE if orchestra else RejectionCode.USAGE_STALE
            reasons.append(_reason(code, f"scope={scope} age={age:.6f}s"))
            continue
        observation_mode = str(usage.get("capacity_mode", "percentage")).lower()
        if observation_mode != capacity_mode:
            code = (
                RejectionCode.ORCHESTRA_USAGE_INVALID if orchestra else RejectionCode.USAGE_INVALID
            )
            reasons.append(
                _reason(code, f"scope={scope} capacity_mode={observation_mode} expected={capacity_mode}")
            )
            continue
        if capacity_mode == "provider_signal":
            if orchestra:
                reasons.append(
                    _reason(RejectionCode.ORCHESTRA_USAGE_INVALID, f"scope={scope} provider signal has no reserve percentage")
                )
                continue
            limit_signal = str(usage.get("limit_signal", "UNKNOWN")).upper()
            if limit_signal != "NONE":
                reasons.append(
                    _reason(RejectionCode.PROVIDER_LIMIT_SIGNAL, f"scope={scope} signal={limit_signal}")
                )
            if not (
                usage.get("service_state") == "healthy"
                and usage.get("authentication_state") == "valid"
                and usage.get("live_invocation_state") == "succeeded"
            ):
                reasons.append(
                    _reason(RejectionCode.PROVIDER_SIGNAL_UNHEALTHY, f"scope={scope}")
                )
            continue
        state = str(usage.get("state", "UNKNOWN")).upper()
        consumed = usage.get("consumed_percent")
        if isinstance(consumed, bool) or not isinstance(consumed, (int, float)):
            code = (
                RejectionCode.ORCHESTRA_USAGE_INVALID if orchestra else RejectionCode.USAGE_INVALID
            )
            reasons.append(_reason(code, f"scope={scope} consumed_percent missing or non-numeric"))
            continue
        if not 0 <= float(consumed) <= 100:
            code = (
                RejectionCode.ORCHESTRA_USAGE_INVALID if orchestra else RejectionCode.USAGE_INVALID
            )
            reasons.append(_reason(code, f"scope={scope} consumed_percent={consumed}"))
            continue
        if orchestra:
            remaining = 100.0 - float(consumed)
            if state not in ("GREEN", "NORMAL", "CAUTION", "CHECKPOINT", "HARD_STOP"):
                reasons.append(_reason(RejectionCode.ORCHESTRA_USAGE_UNKNOWN, f"scope={scope} state={state}"))
            if remaining < snapshot.orchestra_reserve_percent:
                reasons.append(
                    _reason(
                        RejectionCode.ORCHESTRA_CAPACITY_RISK,
                        f"scope={scope} remaining={remaining:.6f}% "
                        f"reserve={snapshot.orchestra_reserve_percent:.6f}%",
                    )
                )
        elif state in ("UNKNOWN", "INVALID"):
            reasons.append(_reason(RejectionCode.USAGE_UNKNOWN, f"scope={scope} state={state}"))
    return tuple(sorted(set(reasons)))


def _worker_reasons(
    snapshot: DispatchSnapshot,
    worker: Mapping[str, Any],
    observed_at: datetime,
    policy: ShadowPolicy,
    actively_leased_workers: set[str],
) -> tuple[Reason, ...]:
    reasons: list[Reason] = []
    if worker.get("role") != "WORKER":
        reasons.append(_reason(RejectionCode.WORKER_ROLE_INELIGIBLE, str(worker.get("role"))))
    if worker.get("availability") != "IDLE":
        reasons.append(_reason(RejectionCode.WORKER_NOT_IDLE, str(worker.get("availability"))))
    if str(worker.get("id")) in actively_leased_workers:
        reasons.append(_reason(RejectionCode.WORKER_HAS_ACTIVE_LEASE))
    heartbeat = worker.get("last_heartbeat_at")
    if not heartbeat:
        reasons.append(_reason(RejectionCode.HEARTBEAT_MISSING))
    else:
        try:
            age = _age_seconds(heartbeat, observed_at, field_name="worker heartbeat")
            if age < 0:
                reasons.append(_reason(RejectionCode.HEARTBEAT_IN_FUTURE, f"{abs(age):.6f}s"))
            elif age > policy.heartbeat_fresh_seconds:
                reasons.append(_reason(RejectionCode.HEARTBEAT_STALE, f"age={age:.6f}s"))
        except ShadowDispatchError as error:
            reasons.append(_reason(RejectionCode.HEARTBEAT_INVALID, str(error)))
    reasons.extend(
        _usage_reasons(
            snapshot,
            str(worker.get("id")),
            observed_at,
            policy,
            orchestra=False,
            expected_scopes=worker.get("capacity_scopes") or ("default",),
            capacity_mode=str(worker.get("capacity_mode", "percentage")).lower(),
        )
    )
    return tuple(sorted(set(reasons)))


def _package_reasons(
    package: Mapping[str, Any],
    package_by_id: Mapping[str, Mapping[str, Any]],
    dependencies: Mapping[str, tuple[str, ...]],
    actively_leased_packages: set[str],
    observed_at: datetime,
) -> tuple[Reason, ...]:
    reasons: list[Reason] = []
    if package.get("status") != "READY":
        reasons.append(_reason(RejectionCode.PACKAGE_NOT_READY, str(package.get("status"))))
    if not package.get("lane"):
        reasons.append(_reason(RejectionCode.PACKAGE_LANE_UNASSIGNED))
    package_id = str(package.get("id"))
    if package_id in actively_leased_packages:
        reasons.append(_reason(RejectionCode.PACKAGE_HAS_ACTIVE_LEASE))
    try:
        ready_at = _parse_time(
            package.get("ready_at") or package.get("created_at"), field_name="package ready_at"
        )
        if ready_at > observed_at:
            reasons.append(
                _reason(
                    RejectionCode.PACKAGE_NOT_YET_READY,
                    ready_at.isoformat(timespec="microseconds").replace("+00:00", "Z"),
                )
            )
    except ShadowDispatchError as error:
        reasons.append(_reason(RejectionCode.PACKAGE_READY_TIME_INVALID, str(error)))
    for dependency_id in dependencies.get(package_id, ()):
        dependency = package_by_id.get(dependency_id)
        if dependency is None:
            reasons.append(_reason(RejectionCode.DEPENDENCY_MISSING, dependency_id))
        elif dependency.get("status") != "DONE":
            reasons.append(
                _reason(
                    RejectionCode.DEPENDENCY_BLOCKED,
                    f"{dependency_id}:{dependency.get('status')}",
                )
            )
    return tuple(sorted(set(reasons)))


def _pair_reasons(
    snapshot: DispatchSnapshot,
    package: Mapping[str, Any],
    worker: Mapping[str, Any],
    package_evaluation: EntityEvaluation,
    worker_evaluation: EntityEvaluation,
    policy: ShadowPolicy,
) -> tuple[Reason, ...]:
    reasons: list[Reason] = []
    if not package_evaluation.eligible:
        reasons.extend(package_evaluation.reasons)
    if not worker_evaluation.eligible:
        reasons.extend(worker_evaluation.reasons)
    lane = package.get("lane")
    approved_lanes = {str(value) for value in worker.get("approved_lanes", ())}
    if lane and lane not in approved_lanes:
        reasons.append(_reason(RejectionCode.LANE_NOT_APPROVED, str(lane)))
    required = {str(value) for value in package.get("required_capabilities", ())}
    capabilities = {str(value) for value in worker.get("capabilities", ())}
    missing = sorted(required - capabilities)
    if missing:
        reasons.append(_reason(RejectionCode.CAPABILITY_MISMATCH, ",".join(missing)))
    if not reasons:
        reasons.extend(_capacity_package_reasons(snapshot, package, worker, policy))
    return tuple(sorted(set(reasons)))


def _capacity_stage(
    snapshot: DispatchSnapshot,
    worker: Mapping[str, Any],
    policy: ShadowPolicy,
) -> str:
    if str(worker.get("capacity_mode", "percentage")).lower() == "provider_signal":
        return "NORMAL"
    scopes = worker.get("capacity_scopes") or ("default",)
    latest = _latest_usage_by_scope(snapshot, str(worker.get("id")), scopes)
    highest = "NORMAL"
    rank = {"NORMAL": 0, "CAUTION": 1, "CHECKPOINT": 2, "HARD_STOP": 3}
    for scope in scopes:
        consumed = float(latest[str(scope)]["consumed_percent"])
        stage = (
            "HARD_STOP" if consumed >= policy.worker_hard_stop_percent
            else "CHECKPOINT" if consumed >= policy.worker_checkpoint_percent
            else "CAUTION" if consumed >= policy.worker_caution_percent
            else "NORMAL"
        )
        if rank[stage] > rank[highest]:
            highest = stage
    return highest


def _capacity_package_reasons(
    snapshot: DispatchSnapshot,
    package: Mapping[str, Any],
    worker: Mapping[str, Any],
    policy: ShadowPolicy,
) -> tuple[Reason, ...]:
    stage = _capacity_stage(snapshot, worker, policy)
    size = str(package.get("capacity_size", "SUBSTANTIAL")).upper()
    risk = str(package.get("capacity_risk", "UNCERTAIN")).upper()
    lane = str(package.get("lane", "")).upper()
    kind = str(package.get("kind", "PARENT")).upper()
    if size not in ("VERY_SMALL", "SMALL", "SUBSTANTIAL") or risk not in (
        "BOUNDED", "UNCERTAIN", "EMERGENCY_RECOVERY"
    ):
        return (_reason(RejectionCode.USAGE_INVALID, "invalid package capacity classification"),)
    if stage in ("CAUTION", "CHECKPOINT") and kind == "PARENT" and (
        size == "SUBSTANTIAL" or risk == "UNCERTAIN"
    ):
        code = (
            RejectionCode.CAPACITY_CHECKPOINT_PACKAGE
            if stage == "CHECKPOINT"
            else RejectionCode.CAPACITY_CAUTION_PACKAGE
        )
        return (_reason(code, f"size={size} risk={risk}"),)
    if stage == "HARD_STOP" and not (
        risk == "EMERGENCY_RECOVERY"
        or (size == "VERY_SMALL" and risk == "BOUNDED" and lane == "ASSURANCE")
    ):
        return (_reason(RejectionCode.CAPACITY_STOPPED, f"size={size} risk={risk}"),)
    return ()


def _capability_surplus(package: Mapping[str, Any], worker: Mapping[str, Any]) -> int:
    required = {str(value) for value in package.get("required_capabilities", ())}
    capabilities = {str(value) for value in worker.get("capabilities", ())}
    return len(capabilities - required)


def _package_order_key(package: Mapping[str, Any]) -> tuple[Any, ...]:
    ready_at = package.get("ready_at") or package.get("created_at")
    try:
        canonical = _canonical_time(ready_at, field_name="package ready_at")
    except ShadowDispatchError:
        canonical = "9999-12-31T23:59:59.999999Z"
    return (-int(package.get("priority", 0)), canonical, str(package.get("id")))


def _decision_id(decision: ShadowDecision) -> str:
    raw = json.dumps(
        decision.as_dict(include_decision_id=False), separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def decide_shadow(
    snapshot: DispatchSnapshot,
    *,
    policy: ShadowPolicy | None = None,
) -> ShadowDecision:
    """Return a deterministic, non-authoritative assignment proposal."""
    policy = policy or ShadowPolicy()
    decided_at = _canonical_time(snapshot.observed_at, field_name="snapshot observed_at")
    observed_at = _parse_time(decided_at, field_name="snapshot observed_at")
    workers = tuple(sorted(snapshot.workers, key=lambda value: str(value.get("id"))))
    packages = tuple(sorted(snapshot.work_packages, key=lambda value: str(value.get("id"))))
    package_by_id = {str(value.get("id")): value for value in packages}
    worker_by_id = {str(value.get("id")): value for value in workers}
    dependencies: dict[str, list[str]] = {}
    for dependency in snapshot.dependencies:
        dependencies.setdefault(str(dependency.get("package_id")), []).append(
            str(dependency.get("dependency_id"))
        )
    normalized_dependencies = {
        key: tuple(sorted(values)) for key, values in sorted(dependencies.items())
    }

    global_rejections: list[Reason] = []
    if any(bool(lease.get("expired")) for lease in snapshot.active_leases):
        global_rejections.append(_reason(RejectionCode.EXPIRED_LEASE_REQUIRES_RECONCILIATION))
    active_leases = tuple(lease for lease in snapshot.active_leases if not lease.get("expired"))
    lease_ids = Counter(str(value.get("id")) for value in active_leases)
    lease_packages = Counter(str(value.get("package_id")) for value in active_leases)
    lease_workers = Counter(str(value.get("worker_id")) for value in active_leases)
    for lease_id, count in sorted(lease_ids.items()):
        if count > 1:
            global_rejections.append(
                _reason(RejectionCode.LEASE_ID_DUPLICATE, f"{lease_id}:count={count}")
            )
    for package_id, count in sorted(lease_packages.items()):
        if count > 1:
            global_rejections.append(
                _reason(RejectionCode.LEASE_PACKAGE_DUPLICATE, f"{package_id}:count={count}")
            )
        if package_id not in package_by_id:
            global_rejections.append(_reason(RejectionCode.LEASE_PACKAGE_ORPHAN, package_id))
    for worker_id, count in sorted(lease_workers.items()):
        if count > 1:
            global_rejections.append(
                _reason(RejectionCode.LEASE_WORKER_DUPLICATE, f"{worker_id}:count={count}")
            )
        if worker_id not in worker_by_id:
            global_rejections.append(_reason(RejectionCode.LEASE_WORKER_ORPHAN, worker_id))
    orchestra_workers = [worker for worker in workers if worker.get("role") == "ORCHESTRA"]
    if not orchestra_workers:
        global_rejections.append(_reason(RejectionCode.ORCHESTRA_WORKER_MISSING))
    else:
        for worker in orchestra_workers:
            global_rejections.extend(
                _usage_reasons(
                    snapshot,
                    str(worker.get("id")),
                    observed_at,
                    policy,
                    orchestra=True,
                    expected_scopes=worker.get("capacity_scopes") or ("default",),
                )
            )
    global_rejections = sorted(set(global_rejections))

    actively_leased_packages = {str(lease.get("package_id")) for lease in active_leases}
    actively_leased_workers = {str(lease.get("worker_id")) for lease in active_leases}
    active_parent_count = sum(
        1
        for lease in active_leases
        if package_by_id.get(str(lease.get("package_id")), {}).get("kind", "PARENT")
        == "PARENT"
    )

    worker_evaluations = tuple(
        EntityEvaluation(
            str(worker.get("id")),
            not (
                reasons := _worker_reasons(
                    snapshot, worker, observed_at, policy, actively_leased_workers
                )
            ),
            reasons,
        )
        for worker in workers
    )
    worker_evaluation_by_id = {value.id: value for value in worker_evaluations}
    package_evaluations_base = tuple(
        EntityEvaluation(
            str(package.get("id")),
            not (
                reasons := _package_reasons(
                    package,
                    package_by_id,
                    normalized_dependencies,
                    actively_leased_packages,
                    observed_at,
                )
            ),
            reasons,
        )
        for package in packages
    )
    package_evaluation_by_id = {value.id: value for value in package_evaluations_base}

    pair_evaluations = tuple(
        PairEvaluation(
            str(package.get("id")),
            str(worker.get("id")),
            not (
                reasons := _pair_reasons(
                    snapshot,
                    package,
                    worker,
                    package_evaluation_by_id[str(package.get("id"))],
                    worker_evaluation_by_id[str(worker.get("id"))],
                    policy,
                )
            ),
            reasons,
            _capability_surplus(package, worker) if not reasons else None,
        )
        for package in packages
        for worker in workers
    )
    eligible_pairs = {(value.package_id, value.worker_id) for value in pair_evaluations if value.eligible}

    package_evaluations: list[EntityEvaluation] = []
    for evaluation in package_evaluations_base:
        reasons = list(evaluation.reasons)
        if evaluation.eligible and not any(
            package_id == evaluation.id for package_id, _worker_id in eligible_pairs
        ):
            reasons.append(_reason(RejectionCode.NO_ELIGIBLE_WORKER))
        package_evaluations.append(
            EntityEvaluation(evaluation.id, not reasons, tuple(sorted(set(reasons))))
        )

    eligible_pair_records = sorted(
        (value for value in pair_evaluations if value.eligible),
        key=lambda value: (
            -int(package_by_id[value.package_id].get("priority", 0)),
            value.capability_surplus,
            _package_order_key(package_by_id[value.package_id])[1],
            value.package_id,
            value.worker_id,
        ),
    )
    ordered_package_ids: list[str] = []
    for pair in eligible_pair_records:
        if pair.package_id not in ordered_package_ids:
            ordered_package_ids.append(pair.package_id)
    assignments: list[Assignment] = []
    assigned_workers: set[str] = set()
    assigned_packages: set[str] = set()
    dynamic_pair_reasons: dict[tuple[str, str], list[Reason]] = {}
    parent_count = active_parent_count
    if not global_rejections:
        for pair in eligible_pair_records:
            package_id = pair.package_id
            worker_id = pair.worker_id
            package = package_by_id[package_id]
            dynamic = dynamic_pair_reasons.setdefault((package_id, worker_id), [])
            if package_id in assigned_packages:
                dynamic.append(_reason(RejectionCode.PACKAGE_ALREADY_PROPOSED))
                continue
            if worker_id in assigned_workers:
                dynamic.append(_reason(RejectionCode.WORKER_ALREADY_PROPOSED))
                continue
            if package.get("kind") == "PARENT" and parent_count >= snapshot.active_parent_limit:
                dynamic.append(_reason(RejectionCode.ACTIVE_PARENT_LIMIT))
                continue
            assignments.append(Assignment(package_id, worker_id))
            assigned_packages.add(package_id)
            assigned_workers.add(worker_id)
            if package.get("kind") == "PARENT":
                parent_count += 1

    # Pair records include assignment-time rejection reasons as a separate deterministic pass.
    final_pairs: list[PairEvaluation] = []
    assignment_set = {(value.package_id, value.worker_id) for value in assignments}
    for evaluation in pair_evaluations:
        reasons = list(evaluation.reasons)
        if evaluation.eligible and (evaluation.package_id, evaluation.worker_id) not in assignment_set:
            reasons.extend(dynamic_pair_reasons.get((evaluation.package_id, evaluation.worker_id), ()))
        final_pairs.append(
            PairEvaluation(
                evaluation.package_id,
                evaluation.worker_id,
                not reasons,
                tuple(sorted(set(reasons))),
                evaluation.capability_surplus,
            )
        )

    decision = ShadowDecision(
        schema_version=1,
        decision_id="",
        registry_revision=snapshot.revision,
        decided_at=decided_at,
        mode="SHADOW",
        global_rejections=tuple(global_rejections),
        worker_evaluations=worker_evaluations,
        package_evaluations=tuple(package_evaluations),
        pair_evaluations=tuple(final_pairs),
        ordered_package_ids=tuple(ordered_package_ids),
        proposed_assignments=tuple(assignments),
        active_parent_count=active_parent_count,
        active_parent_limit=snapshot.active_parent_limit,
        orchestra_reserve_percent=snapshot.orchestra_reserve_percent,
    )
    return replace(decision, decision_id=_decision_id(decision))


def compare_with_legacy(
    decision: ShadowDecision,
    legacy: LegacyObservation,
    *,
    classifications: Mapping[str, DifferenceClassification | str] | None = None,
    observation_tolerance_seconds: int = 60,
) -> LegacyComparison:
    """Compare proposals without reading from or writing to the legacy runner."""
    if observation_tolerance_seconds < 0:
        raise ShadowDispatchError("legacy observation tolerance cannot be negative")
    classifications = classifications or {}
    shadow_set = {(value.package_id, value.worker_id) for value in decision.proposed_assignments}
    legacy_set = {(value.package_id, value.worker_id) for value in legacy.assignments}
    shadow_order = tuple((value.package_id, value.worker_id) for value in decision.proposed_assignments)
    legacy_order = tuple((value.package_id, value.worker_id) for value in legacy.assignments)
    raw: list[tuple[str, str | None, str | None, str]] = []
    legacy_observed_at = str(legacy.observed_at)
    try:
        legacy_time = _parse_time(legacy.observed_at, field_name="legacy observed_at")
        legacy_observed_at = legacy_time.isoformat(timespec="microseconds").replace("+00:00", "Z")
        decision_time = _parse_time(decision.decided_at, field_name="decision decided_at")
        offset = (legacy_time - decision_time).total_seconds()
        if offset < -observation_tolerance_seconds:
            raw.append(
                (
                    "LEGACY_OBSERVATION_STALE",
                    None,
                    None,
                    f"offset={offset:.6f}s tolerance={observation_tolerance_seconds}s",
                )
            )
        elif offset > observation_tolerance_seconds:
            raw.append(
                (
                    "LEGACY_OBSERVATION_IN_FUTURE",
                    None,
                    None,
                    f"offset={offset:.6f}s tolerance={observation_tolerance_seconds}s",
                )
            )
    except ShadowDispatchError as error:
        raw.append(("LEGACY_OBSERVATION_TIME_INVALID", None, None, str(error)))
    if not legacy.complete:
        raw.append(
            (
                "LEGACY_OBSERVATION_INCOMPLETE",
                None,
                None,
                "legacy observable assignment set was incomplete",
            )
        )
    if len(legacy_set) != len(legacy.assignments):
        raw.append(
            (
                "LEGACY_DUPLICATE_ASSIGNMENT",
                None,
                None,
                "legacy observation contains duplicate assignments",
            )
        )
    for package_id, worker_id in sorted(shadow_set - legacy_set):
        raw.append(("SHADOW_ONLY", package_id, worker_id, "shadow proposed; legacy did not"))
    for package_id, worker_id in sorted(legacy_set - shadow_set):
        raw.append(("LEGACY_ONLY", package_id, worker_id, "legacy proposed; shadow did not"))
    if shadow_set == legacy_set and shadow_order != legacy_order:
        raw.append(
            (
                "ASSIGNMENT_ORDER",
                None,
                None,
                "shadow and legacy chose the same assignments in a different order",
            )
        )
    differences: list[LegacyDifference] = []
    non_overridable_time_failures = {
        "LEGACY_OBSERVATION_STALE",
        "LEGACY_OBSERVATION_IN_FUTURE",
        "LEGACY_OBSERVATION_TIME_INVALID",
    }
    for kind, package_id, worker_id, detail in raw:
        difference_id = ":".join((kind, package_id or "-", worker_id or "-"))
        raw_classification = (
            DifferenceClassification.UNRESOLVED
            if kind in non_overridable_time_failures
            else classifications.get(difference_id, DifferenceClassification.UNRESOLVED)
        )
        try:
            classification = (
                raw_classification
                if isinstance(raw_classification, DifferenceClassification)
                else DifferenceClassification(str(raw_classification))
            )
        except ValueError:
            classification = DifferenceClassification.UNRESOLVED
        differences.append(
            LegacyDifference(
                difference_id,
                kind,
                package_id,
                worker_id,
                classification,
                detail,
            )
        )
    return LegacyComparison(
        decision.decision_id,
        legacy.source,
        legacy_observed_at,
        not differences,
        all(value.classification != DifferenceClassification.UNRESOLVED for value in differences),
        tuple(differences),
    )


def simulate_outcome(
    snapshot: DispatchSnapshot,
    *,
    package_id: str,
    worker_id: str,
    outcome: str,
    observed_at: str,
) -> DispatchSnapshot:
    """Return an in-memory post-outcome snapshot; never mutate registry state."""
    outcome = outcome.upper()
    if outcome not in {"COMPLETED", "FAILED"}:
        raise ShadowDispatchError("outcome must be COMPLETED or FAILED")
    matching_packages = [value for value in snapshot.work_packages if value.get("id") == package_id]
    matching_workers = [value for value in snapshot.workers if value.get("id") == worker_id]
    if len(matching_packages) != 1:
        raise ShadowDispatchError(f"unknown package {package_id}")
    if len(matching_workers) != 1:
        raise ShadowDispatchError(f"unknown worker {worker_id}")
    if matching_packages[0].get("status") != "ACTIVE":
        raise ShadowDispatchError(f"simulation package {package_id} must be ACTIVE")
    if matching_workers[0].get("availability") != "BUSY":
        raise ShadowDispatchError(f"simulation worker {worker_id} must be BUSY")
    matching_leases = [
        value
        for value in snapshot.active_leases
        if not value.get("expired")
        and value.get("package_id") == package_id
        and value.get("worker_id") == worker_id
    ]
    conflicting_leases = [
        value
        for value in snapshot.active_leases
        if not value.get("expired")
        and (
            value.get("package_id") == package_id or value.get("worker_id") == worker_id
        )
        and value not in matching_leases
    ]
    if len(matching_leases) != 1 or conflicting_leases:
        raise ShadowDispatchError(
            "simulation baseline requires exactly one matching non-expired lease"
        )
    canonical_observed_at = _canonical_time(observed_at, field_name="simulation observed_at")
    if _parse_time(canonical_observed_at, field_name="simulation observed_at") <= _parse_time(
        snapshot.observed_at, field_name="simulation baseline observed_at"
    ):
        raise ShadowDispatchError("simulation observed_at must follow the baseline")
    matching_lease_id = matching_leases[0].get("id")
    packages: list[Mapping[str, Any]] = []
    for original in snapshot.work_packages:
        value = copy.deepcopy(dict(original))
        if value.get("id") == package_id:
            value["status"] = "DONE" if outcome == "COMPLETED" else "BLOCKED"
            value["failure_code"] = None if outcome == "COMPLETED" else "CI_FAILURE"
            value["failure_detail"] = None if outcome == "COMPLETED" else "simulated failure"
            value["updated_at"] = canonical_observed_at
        packages.append(value)
    workers: list[Mapping[str, Any]] = []
    for original in snapshot.workers:
        value = copy.deepcopy(dict(original))
        if value.get("id") == worker_id:
            value["availability"] = "IDLE"
            value["last_heartbeat_at"] = canonical_observed_at
            value["updated_at"] = canonical_observed_at
        workers.append(value)
    leases = tuple(
        copy.deepcopy(dict(value))
        for value in snapshot.active_leases
        if value.get("id") != matching_lease_id
    )
    return DispatchSnapshot(
        revision=snapshot.revision + 1,
        observed_at=canonical_observed_at,
        active_parent_limit=snapshot.active_parent_limit,
        orchestra_reserve_percent=snapshot.orchestra_reserve_percent,
        features=tuple(copy.deepcopy(value) for value in snapshot.features),
        work_packages=tuple(packages),
        dependencies=tuple(copy.deepcopy(value) for value in snapshot.dependencies),
        workers=tuple(workers),
        active_leases=leases,
        usage_observations=tuple(copy.deepcopy(value) for value in snapshot.usage_observations),
    )


def _validate_outcome_simulation(
    baseline: DispatchSnapshot,
    simulated: DispatchSnapshot,
    *,
    assignment: Assignment,
    outcome: str,
    observed_at: str,
) -> OutcomeSimulationEvidence:
    expected_status = "DONE" if outcome == "COMPLETED" else "BLOCKED"
    canonical_observed_at = _canonical_time(observed_at, field_name="simulation observed_at")
    packages = [
        value for value in simulated.work_packages if value.get("id") == assignment.package_id
    ]
    workers = [value for value in simulated.workers if value.get("id") == assignment.worker_id]
    lease_removed = not any(
        value.get("package_id") == assignment.package_id
        or value.get("worker_id") == assignment.worker_id
        for value in simulated.active_leases
    )
    if len(packages) != 1 or packages[0].get("status") != expected_status:
        raise ShadowDispatchError(f"{outcome} simulation did not reach {expected_status}")
    if len(workers) != 1 or workers[0].get("availability") != "IDLE":
        raise ShadowDispatchError(f"{outcome} simulation did not release the worker")
    if not lease_removed:
        raise ShadowDispatchError(f"{outcome} simulation did not remove the matching lease")
    if simulated.revision != baseline.revision + 1:
        raise ShadowDispatchError(f"{outcome} simulation revision is not baseline + 1")
    if simulated.observed_at != canonical_observed_at:
        raise ShadowDispatchError(f"{outcome} simulation timestamp mismatch")
    if outcome == "FAILED" and packages[0].get("failure_code") != "CI_FAILURE":
        raise ShadowDispatchError("FAILED simulation lacks normalized failure evidence")
    if outcome == "COMPLETED" and packages[0].get("failure_code") is not None:
        raise ShadowDispatchError("COMPLETED simulation retained failure evidence")
    return OutcomeSimulationEvidence(
        outcome=outcome,
        package_id=assignment.package_id,
        worker_id=assignment.worker_id,
        baseline_revision=baseline.revision,
        simulated_revision=simulated.revision,
        baseline_observed_at=_canonical_time(
            baseline.observed_at, field_name="simulation baseline observed_at"
        ),
        simulated_observed_at=simulated.observed_at,
        package_status=str(packages[0].get("status")),
        worker_availability=str(workers[0].get("availability")),
        matching_lease_removed=lease_removed,
    )


def run_required_shadow_harness(
    scheduled: Sequence[tuple[DispatchSnapshot, LegacyObservation]],
    simulation_baseline: DispatchSnapshot,
    simulation_assignment: Assignment,
    completion_legacy: LegacyObservation,
    failure_legacy: LegacyObservation,
    *,
    completion_observed_at: str,
    failure_observed_at: str,
    classifications: Mapping[str, DifferenceClassification | str] | None = None,
    policy: ShadowPolicy | None = None,
) -> ShadowHarnessEvidence:
    """Run the required three sweeps and two outcome simulations in memory."""
    if len(scheduled) != 3:
        raise ShadowDispatchError("exactly three scheduled sweeps are required")
    policy = policy or ShadowPolicy()
    scheduled_times = [
        _parse_time(value[0].observed_at, field_name="scheduled snapshot observed_at")
        for value in scheduled
    ]
    minimum_interval = policy.scheduled_sweep_seconds - policy.scheduled_sweep_tolerance_seconds
    maximum_interval = policy.scheduled_sweep_seconds + policy.scheduled_sweep_tolerance_seconds
    for earlier, later in zip(scheduled_times, scheduled_times[1:]):
        interval = (later - earlier).total_seconds()
        if not minimum_interval <= interval <= maximum_interval:
            raise ShadowDispatchError(
                "scheduled sweep interval outside configured tolerance: "
                f"{interval:.6f}s"
            )
    source_snapshots = tuple(value[0] for value in scheduled) + (simulation_baseline,)
    before_fingerprints = tuple(snapshot_fingerprint(value) for value in source_snapshots)
    scheduled_decisions = tuple(decide_shadow(value[0], policy=policy) for value in scheduled)
    completion_snapshot = simulate_outcome(
        simulation_baseline,
        package_id=simulation_assignment.package_id,
        worker_id=simulation_assignment.worker_id,
        outcome="COMPLETED",
        observed_at=completion_observed_at,
    )
    failure_snapshot = simulate_outcome(
        simulation_baseline,
        package_id=simulation_assignment.package_id,
        worker_id=simulation_assignment.worker_id,
        outcome="FAILED",
        observed_at=failure_observed_at,
    )
    completion_simulation = _validate_outcome_simulation(
        simulation_baseline,
        completion_snapshot,
        assignment=simulation_assignment,
        outcome="COMPLETED",
        observed_at=completion_observed_at,
    )
    failure_simulation = _validate_outcome_simulation(
        simulation_baseline,
        failure_snapshot,
        assignment=simulation_assignment,
        outcome="FAILED",
        observed_at=failure_observed_at,
    )
    completion_decision = decide_shadow(completion_snapshot, policy=policy)
    failure_decision = decide_shadow(failure_snapshot, policy=policy)
    all_decisions = scheduled_decisions + (completion_decision, failure_decision)
    all_legacy = tuple(value[1] for value in scheduled) + (completion_legacy, failure_legacy)
    comparisons = tuple(
        compare_with_legacy(
            decision,
            legacy,
            classifications=classifications,
            observation_tolerance_seconds=policy.legacy_observation_tolerance_seconds,
        )
        for decision, legacy in zip(all_decisions, all_legacy)
    )
    failures: list[str] = []
    for index, comparison in enumerate(comparisons):
        if not comparison.gate_passed:
            failures.append(f"comparison[{index}] has unresolved differences")
    for index, decision in enumerate(all_decisions):
        if decision.global_rejections:
            failures.append(f"decision[{index}] has global rejections")
    after_fingerprints = tuple(snapshot_fingerprint(value) for value in source_snapshots)
    if before_fingerprints != after_fingerprints:
        failures.append("shadow evaluation mutated an input snapshot")
    return ShadowHarnessEvidence(
        scheduled_decisions,
        completion_decision,
        failure_decision,
        completion_simulation,
        failure_simulation,
        comparisons,
        not failures,
        tuple(failures),
    )


def write_shadow_harness_evidence(
    evidence: ShadowHarnessEvidence,
    destination: str | Path,
) -> Path:
    """Persist one immutable evidence artifact without touching registry state."""
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        handle.write(evidence.to_json())
        handle.write("\n")
    return path


def snapshot_fingerprint(snapshot: DispatchSnapshot) -> str:
    """Stable test/audit fingerprint proving shadow evaluation did not mutate input."""
    payload = {
        "revision": snapshot.revision,
        "observed_at": snapshot.observed_at,
        "active_parent_limit": snapshot.active_parent_limit,
        "orchestra_reserve_percent": snapshot.orchestra_reserve_percent,
        "features": snapshot.features,
        "work_packages": snapshot.work_packages,
        "dependencies": snapshot.dependencies,
        "workers": snapshot.workers,
        "active_leases": snapshot.active_leases,
        "usage_observations": snapshot.usage_observations,
    }
    return hashlib.sha256(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()
