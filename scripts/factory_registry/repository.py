"""Backend-neutral API boundary for the Factory registry."""

from __future__ import annotations

from typing import Any, Mapping, Protocol, Sequence

from .models import (
    Attempt,
    ControlCenterReadSnapshot,
    DispatchSnapshot,
    Evidence,
    Feature,
    Lease,
    ReviewOutcome,
    TaskStatus,
    UsageLedgerEntry,
    UsageLedgerWrite,
    Worker,
    WorkPackage,
)


class RegistryError(RuntimeError):
    """Base class for registry failures exposed across storage adapters."""


class RegistryConflict(RegistryError):
    """The requested transition violates a registry invariant."""

    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)


class RegistryNotFound(RegistryError):
    """A requested registry entity does not exist."""


class Registry(Protocol):
    """Storage contract used by dispatch, telemetry, and dashboard projections.

    Implementations may use SQLite, Postgres, Supabase, or another transactional
    backend. Callers must not depend on backend-specific SQL or filesystem paths.
    """

    def initialize(self) -> None: ...

    def dispatch_control(self) -> Mapping[str, Any]: ...

    def require_live_dispatch(self, *, expected_revision: int | None = None) -> int: ...

    def register_feature(self, feature: Feature) -> None: ...

    def register_work_package(self, package: WorkPackage) -> None: ...

    def register_worker(self, worker: Worker) -> None: ...

    def acquire_lease(
        self,
        package_id: str,
        worker_id: str,
        *,
        acquired_at: str,
        expires_at: str,
        expected_dispatch_revision: int | None = None,
    ) -> Lease: ...

    def renew_lease(self, lease_id: str, *, now: str, expires_at: str) -> Lease: ...

    def renew_attempt_runtime(
        self,
        attempt_id: str,
        lease_id: str,
        *,
        now: str,
        expires_at: str,
    ) -> Lease: ...

    def active_attempt_runtimes(self) -> Sequence[Mapping[str, Any]]: ...

    def active_unbound_leases(self) -> Sequence[Mapping[str, Any]]: ...

    def recover_attempt_runtime(
        self,
        attempt_id: str,
        *,
        ended_at: str,
        reason: str,
        failure_detail: str,
    ) -> bool: ...

    def recover_stopped_lease(
        self,
        lease_id: str,
        *,
        ended_at: str,
        reason: str,
        failure_detail: str,
    ) -> bool: ...

    def expire_leases(self, *, observed_at: str) -> int: ...

    def release_lease(
        self,
        lease_id: str,
        *,
        released_at: str,
        reason: str,
        next_status: TaskStatus,
    ) -> None: ...

    def transition_work_package(
        self,
        package_id: str,
        *,
        expected_status: TaskStatus,
        new_status: TaskStatus,
        changed_at: str,
    ) -> None: ...

    def append_event(
        self,
        event_type: str,
        *,
        recorded_at: str,
        package_id: str | None = None,
        worker_id: str | None = None,
        attempt_id: str | None = None,
        detail: Mapping[str, Any] | None = None,
    ) -> str: ...

    def record_evidence(self, evidence: Evidence) -> None: ...

    def record_review_outcome(self, outcome: ReviewOutcome) -> None: ...

    def register_attempt(self, attempt: Attempt) -> None: ...

    def record_usage(self, entry: UsageLedgerEntry) -> UsageLedgerWrite: ...

    def usage_entries(
        self,
        *,
        worker_id: str | None = None,
        since: str | None = None,
        through: str | None = None,
    ) -> Sequence[Mapping[str, Any]]: ...

    def usage_analytics(
        self,
        worker_id: str,
        *,
        observed_at: str,
    ) -> Mapping[str, Any]: ...

    def import_preservation_snapshot(
        self,
        snapshot: Mapping[str, Any],
        *,
        source_uri: str,
        source_sha256: str,
        imported_at: str,
    ) -> bool: ...

    def feature_queue(self) -> Sequence[Mapping[str, Any]]: ...

    def dispatch_snapshot(self, *, observed_at: str) -> DispatchSnapshot: ...

    def control_center_snapshot(self, *, observed_at: str) -> ControlCenterReadSnapshot: ...
