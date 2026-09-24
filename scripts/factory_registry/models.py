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
