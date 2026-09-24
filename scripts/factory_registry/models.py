"""Stable data contracts for the Factory control plane.

Provider and model names are diagnostic metadata. They do not grant a worker a
lane or make a task eligible for that worker.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping


class StringEnum(str, Enum):
    """Python 3.9-compatible string enum."""

    def __str__(self) -> str:
        return self.value


class Lane(StringEnum):
    FEATURE = "FEATURE"
    PLATFORM = "PLATFORM"
    ASSURANCE = "ASSURANCE"


class TaskStatus(StringEnum):
    ON_DECK = "ON_DECK"
    READY = "READY"
    ACTIVE = "ACTIVE"
    VERIFY_REVIEW = "VERIFY_REVIEW"
    BLOCKED = "BLOCKED"
    DONE = "DONE"


class PackageKind(StringEnum):
    PARENT = "PARENT"
    TEST = "TEST"
    REVIEW = "REVIEW"
    EVALUATION = "EVALUATION"


class PackageCapacitySize(StringEnum):
    VERY_SMALL = "VERY_SMALL"
    SMALL = "SMALL"
    SUBSTANTIAL = "SUBSTANTIAL"


class PackageCapacityRisk(StringEnum):
    BOUNDED = "BOUNDED"
    UNCERTAIN = "UNCERTAIN"
    EMERGENCY_RECOVERY = "EMERGENCY_RECOVERY"


class FailureCode(StringEnum):
    UNDERUTILIZED_SESSION = "UNDERUTILIZED_SESSION"
    WEEKLY_CAPACITY_UNUSED = "WEEKLY_CAPACITY_UNUSED"
    BACKLOG_STARVATION = "BACKLOG_STARVATION"
    HEARTBEAT_MISSED = "HEARTBEAT_MISSED"
    RATE_LIMIT = "RATE_LIMIT"
    CONTEXT_EXHAUSTED = "CONTEXT_EXHAUSTED"
    SCOPE_DRIFT = "SCOPE_DRIFT"
    CI_FAILURE = "CI_FAILURE"
    REVIEW_FAILURE = "REVIEW_FAILURE"
    DEPENDENCY_BLOCKED = "DEPENDENCY_BLOCKED"
    MERGE_CONFLICT = "MERGE_CONFLICT"
    AUTH_FAILURE = "AUTH_FAILURE"
    TASK_TOO_LARGE = "TASK_TOO_LARGE"
    ORCHESTRA_CAPACITY_RISK = "ORCHESTRA_CAPACITY_RISK"


class UsageSource(StringEnum):
    """Structured origins accepted by the provider-neutral usage ledger."""

    CLI_JSON = "CLI_JSON"
    CLI_STREAM_JSON = "CLI_STREAM_JSON"
    TRANSCRIPT = "TRANSCRIPT"


class UsageObservationClass(StringEnum):
    """Whether an invocation is production work or an explicit health probe."""

    AUTONOMOUS = "AUTONOMOUS"
    DIAGNOSTIC = "DIAGNOSTIC"
    LEGACY_UNCLASSIFIED = "LEGACY_UNCLASSIFIED"


@dataclass(frozen=True)
class Feature:
    id: str
    title: str
    priority: int
    status: TaskStatus = TaskStatus.ON_DECK
    description: str = ""


@dataclass(frozen=True)
class WorkPackage:
    id: str
    feature_id: str
    title: str
    category: str
    lane: Lane | None
    required_capabilities: tuple[str, ...]
    priority: int
    acceptance_criteria: tuple[str, ...]
    status: TaskStatus = TaskStatus.ON_DECK
    kind: PackageKind = PackageKind.PARENT
    capacity_size: PackageCapacitySize = PackageCapacitySize.SUBSTANTIAL
    capacity_risk: PackageCapacityRisk = PackageCapacityRisk.UNCERTAIN
    dependency_ids: tuple[str, ...] = ()
    provider_diagnostics: Mapping[str, Any] = field(default_factory=dict)
    branch: str | None = None
    pr_url: str | None = None
    started_at: str | None = None
    last_heartbeat_at: str | None = None
    runtime_seconds: float = 0.0
    usage_consumption: Mapping[str, Any] = field(default_factory=dict)
    failure_code: FailureCode | None = None
    failure_detail: str | None = None


@dataclass(frozen=True)
class Worker:
    id: str
    display_name: str
    capabilities: tuple[str, ...]
    approved_lanes: tuple[Lane, ...]
    role: str = "WORKER"
    availability: str = "IDLE"
    provider_diagnostics: Mapping[str, Any] = field(default_factory=dict)
    last_heartbeat_at: str | None = None
    usage_state: str = "UNKNOWN"


@dataclass(frozen=True)
class Lease:
    id: str
    package_id: str
    worker_id: str
    acquired_at: str
    expires_at: str
    released_at: str | None = None
    release_reason: str | None = None


@dataclass(frozen=True)
class Evidence:
    id: str
    package_id: str
    kind: str
    uri: str | None
    summary: str
    recorded_at: str
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Attempt:
    id: str
    package_id: str
    worker_id: str | None
    started_at: str
    lease_id: str | None = None
    provider_diagnostics: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class UsageLedgerEntry:
    """One invocation or explicit probe, aggregated across observed sources.

    ``invocation_id`` is the cross-source deduplication identity. A runner
    should generate it before launch and pass it to every ingestion path. When
    that is not possible, provider session identity is the conservative
    fallback used by the Claude parser.
    """

    id: str
    provider: str
    worker_id: str
    account_id: str
    invocation_id: str
    session_id: str
    observed_at: str
    outcome: str
    source_type: UsageSource
    source_identity: str
    observation_class: UsageObservationClass = UsageObservationClass.AUTONOMOUS
    package_id: str | None = None
    attempt_id: str | None = None
    model_diagnostic: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_input_tokens: int | None = None
    cache_creation_input_tokens: int | None = None
    duration_ms: float | None = None
    task_completed: bool = False
    review_completed: bool = False
    limit_signal: str | None = None
    limit_reset_at: str | None = None
    limit_raw_error: str | None = None
    calibration_metadata: Mapping[str, Any] = field(default_factory=dict)
    source_metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class UsageLedgerWrite:
    """Outcome of idempotent usage ingestion."""

    entry_id: str
    inserted: bool
    source_added: bool


@dataclass(frozen=True)
class DispatchSnapshot:
    """Consistent read model consumed by schedulers and dashboard projections."""

    revision: int
    observed_at: str
    active_parent_limit: int
    orchestra_reserve_percent: float
    features: tuple[Mapping[str, Any], ...]
    work_packages: tuple[Mapping[str, Any], ...]
    dependencies: tuple[Mapping[str, Any], ...]
    workers: tuple[Mapping[str, Any], ...]
    active_leases: tuple[Mapping[str, Any], ...]
    usage_observations: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True)
class ControlCenterReadSnapshot:
    """One backend-neutral, consistent Registry read for UI projection.

    These are authoritative Registry records, not dashboard-shaped state. The
    Control Center projector is responsible for sanitizing and translating the
    records without acquiring write authority or opening a second store.
    """

    revision: int
    observed_at: str
    active_parent_limit: int
    orchestra_reserve_percent: float
    features: tuple[Mapping[str, Any], ...]
    work_packages: tuple[Mapping[str, Any], ...]
    dependencies: tuple[Mapping[str, Any], ...]
    workers: tuple[Mapping[str, Any], ...]
    leases: tuple[Mapping[str, Any], ...]
    attempts: tuple[Mapping[str, Any], ...]
    evidence: tuple[Mapping[str, Any], ...]
    usage_observations: tuple[Mapping[str, Any], ...]
    usage_invocations: tuple[Mapping[str, Any], ...]
    usage_sources: tuple[Mapping[str, Any], ...]
    failures: tuple[Mapping[str, Any], ...]
    events: tuple[Mapping[str, Any], ...]
    preservation_imports: tuple[Mapping[str, Any], ...]
    preserved_artifacts: tuple[Mapping[str, Any], ...]
