"""Provider-neutral controlled restart procedure.

This module defines sequencing and safety invariants only.  It has no concrete
service, process, queue, or database adapter, so importing it cannot enable
dispatch.  A live adapter must persist control mode and ownership through the
authoritative Registry port and must treat the kill switch as the first gate
before every claim and launch.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping, Protocol, Sequence


class RestartPhase(str, Enum):
    PAUSED = "PAUSED"
    LIVE = "LIVE"
    STOPPING = "STOPPING"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"


class AttemptOutcome(str, Enum):
    ACTIVE = "ACTIVE"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True)
class PreservationState:
    source_sha256: str
    worktree_count: int
    dirty_worktree_count: int
    unmerged_branch_count: int
    unexplained_record_count: int
    active_stale_lease_count: int
    clean: bool


@dataclass(frozen=True)
class ActiveOwnership:
    lease_id: str
    package_id: str
    worker_id: str
    attempt_id: str | None
    expires_at: str


@dataclass(frozen=True)
class AttemptState:
    id: str
    package_id: str
    worker_id: str | None
    outcome: AttemptOutcome
    ended_at: str | None


@dataclass(frozen=True)
class RestartSnapshot:
    """One Registry revision used by the restart procedure."""

    revision: int
    observed_at: str
    phase: RestartPhase
    kill_switch_engaged: bool
    ownership: tuple[ActiveOwnership, ...]
    attempts: tuple[AttemptState, ...]
    worker_availability: Mapping[str, str]
    package_states: Mapping[str, str]


@dataclass(frozen=True)
class RecoveryResult:
    """Registry-side atomic recovery result.

    ``unresolved_ownership`` must name every lease that could not be made
    terminal.  Returning an empty result while leaving ownership active is
    caught by the procedure's required post-read.
    """

    released_lease_ids: tuple[str, ...] = ()
    terminal_attempt_ids: tuple[str, ...] = ()
    blocked_package_ids: tuple[str, ...] = ()
    unresolved_ownership: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProcedureResult:
    phase: RestartPhase
    registry_revision: int
    actions: tuple[str, ...]
    recovery: RecoveryResult | None = None


class ControlledRestartError(RuntimeError):
    """A restart gate or atomic control transition failed."""


class RecoveryRequired(ControlledRestartError):
    """The kill switch is engaged but ownership still needs reconciliation."""

    def __init__(self, ownership_ids: Sequence[str], detail: str) -> None:
        self.ownership_ids = tuple(sorted(set(ownership_ids)))
        super().__init__(f"{detail}: {','.join(self.ownership_ids) or 'unknown ownership'}")


class RestartRegistry(Protocol):
    """Authoritative Registry operations required by the procedure.

    Implementations must make each mutating method atomic and append an audit
    event in the same transaction as its state change.
    """

    def restart_snapshot(self, *, observed_at: str) -> RestartSnapshot: ...

    def reconcile_preservation(self, *, observed_at: str) -> PreservationState: ...

    def enable_live(
        self,
        *,
        expected_revision: int,
        expected_phase: RestartPhase,
        changed_at: str,
        reason: str,
    ) -> RestartSnapshot: ...

    def engage_kill_switch(self, *, changed_at: str, reason: str) -> RestartSnapshot: ...

    def reconcile_stopped_ownership(
        self,
        ownership: Sequence[ActiveOwnership],
        *,
        observed_at: str,
        reason: str,
    ) -> RecoveryResult: ...

    def expire_leases(self, *, observed_at: str) -> RecoveryResult: ...

    def record_worker_disappearance(
        self,
        worker_id: str,
        *,
        observed_at: str,
    ) -> RecoveryResult: ...

    def requeue_failed_attempt(self, attempt_id: str, *, observed_at: str) -> str: ...

    def finalize_paused(
        self,
        *,
        expected_revision: int,
        changed_at: str,
        reason: str,
    ) -> RestartSnapshot: ...


class RestartSupervisor(Protocol):
    """Narrow runtime boundary; it never owns scheduling state."""

    def prepare(self) -> None: ...

    def enable_claims(self, *, registry_revision: int) -> None: ...

    def disable_claims(self) -> None: ...

    def terminate_attempt(self, attempt_id: str) -> None: ...


def _assert_same_preservation(actual: PreservationState, expected: PreservationState) -> None:
    if not actual.clean:
        raise ControlledRestartError("preservation reconciliation is not clean")
    if actual != expected:
        raise ControlledRestartError("preservation evidence changed since owner review")
    if actual.unexplained_record_count or actual.active_stale_lease_count:
        raise ControlledRestartError("preservation has unexplained records or stale ownership")


def _active_attempt_ids(snapshot: RestartSnapshot) -> tuple[str, ...]:
    return tuple(
        attempt.id
        for attempt in snapshot.attempts
        if attempt.outcome == AttemptOutcome.ACTIVE and attempt.ended_at is None
    )


def _ownership_identifiers(snapshot: RestartSnapshot) -> tuple[str, ...]:
    identifiers = [item.lease_id for item in snapshot.ownership]
    leased_attempts = {
        item.attempt_id for item in snapshot.ownership if item.attempt_id is not None
    }
    identifiers.extend(
        f"attempt:{attempt_id}"
        for attempt_id in _active_attempt_ids(snapshot)
        if attempt_id not in leased_attempts
    )
    return tuple(identifiers)


def _merge_recovery(*results: RecoveryResult) -> RecoveryResult:
    return RecoveryResult(
        released_lease_ids=tuple(
            sorted({value for item in results for value in item.released_lease_ids})
        ),
        terminal_attempt_ids=tuple(
            sorted({value for item in results for value in item.terminal_attempt_ids})
        ),
        blocked_package_ids=tuple(
            sorted({value for item in results for value in item.blocked_package_ids})
        ),
        unresolved_ownership=tuple(
            sorted({value for item in results for value in item.unresolved_ownership})
        ),
    )


class ControlledRestartProcedure:
    """Execute the approved ordering against injected control-plane ports."""

    def __init__(self, registry: RestartRegistry, supervisor: RestartSupervisor) -> None:
        self._registry = registry
        self._supervisor = supervisor

    def enable_live(
        self,
        *,
        observed_at: str,
        expected_preservation: PreservationState,
        reason: str,
    ) -> ProcedureResult:
        """Enable claims only after a clean, revision-pinned paused preflight."""
        snapshot = self._registry.restart_snapshot(observed_at=observed_at)
        if snapshot.phase != RestartPhase.PAUSED or not snapshot.kill_switch_engaged:
            raise ControlledRestartError("live enable requires PAUSED with the kill switch engaged")
        if snapshot.ownership or _active_attempt_ids(snapshot):
            raise RecoveryRequired(
                _ownership_identifiers(snapshot),
                "live enable found active ownership",
            )
        actual_preservation = self._registry.reconcile_preservation(observed_at=observed_at)
        _assert_same_preservation(actual_preservation, expected_preservation)
        self._supervisor.prepare()
        live = self._registry.enable_live(
            expected_revision=snapshot.revision,
            expected_phase=RestartPhase.PAUSED,
            changed_at=observed_at,
            reason=reason,
        )
        if live.phase != RestartPhase.LIVE or live.kill_switch_engaged:
            raise ControlledRestartError("Registry did not commit the live control state")
        try:
            self._supervisor.enable_claims(registry_revision=live.revision)
        except Exception as error:
            # Claims cannot remain authorized when the runtime failed to start.
            stopped = self._registry.engage_kill_switch(
                changed_at=observed_at, reason="live supervisor failed to start"
            )
            try:
                self._supervisor.disable_claims()
            except Exception as stop_error:
                raise RecoveryRequired(
                    _ownership_identifiers(stopped),
                    "kill switch engaged but automatic startup rollback failed",
                ) from stop_error
            self._finalize_if_drained(observed_at, "automatic rollback after enable failure")
            raise ControlledRestartError("live supervisor failed; Registry rolled back to paused") from error
        return ProcedureResult(
            live.phase,
            live.revision,
            ("preservation_reconciled", "registry_live_committed", "claims_enabled"),
        )

    def immediate_stop(self, *, observed_at: str, reason: str) -> ProcedureResult:
        """Engage the Registry kill switch before touching runtime processes."""
        stopped = self._registry.engage_kill_switch(changed_at=observed_at, reason=reason)
        actions = ["registry_kill_switch_engaged"]
        try:
            self._supervisor.disable_claims()
            actions.append("claims_disabled")
        except Exception as error:
            raise RecoveryRequired(
                _ownership_identifiers(stopped),
                "kill switch engaged but claim-loop stop failed",
            ) from error
        return self._drain_and_pause(stopped, observed_at, reason, actions)

    def handle_lease_expiry(self, *, observed_at: str) -> ProcedureResult:
        """Stop expired attempts, reconcile ownership, and fail closed."""
        before = self._registry.restart_snapshot(observed_at=observed_at)
        expired_before = tuple(
            item for item in before.ownership if item.expires_at <= observed_at
        )
        if not expired_before:
            return ProcedureResult(
                before.phase,
                before.revision,
                ("no_expired_leases",),
                RecoveryResult(),
            )

        self._registry.engage_kill_switch(
            changed_at=observed_at, reason="lease expiry detected"
        )
        try:
            self._supervisor.disable_claims()
        except Exception as error:
            raise RecoveryRequired(
                [item.lease_id for item in expired_before],
                "kill switch engaged but claim-loop stop failed during lease expiry",
            ) from error

        self._terminate_owned_attempts(expired_before)
        recovery = self._registry.expire_leases(observed_at=observed_at)
        after = self._registry.restart_snapshot(observed_at=observed_at)
        expired = [item.lease_id for item in after.ownership if item.expires_at <= observed_at]
        unresolved = tuple(sorted(set((*recovery.unresolved_ownership, *expired))))
        if unresolved:
            self._registry.engage_kill_switch(
                changed_at=observed_at, reason="lease expiry left unresolved ownership"
            )
            raise RecoveryRequired(unresolved, "lease expiry reconciliation failed")
        # The expiry may coexist with other healthy ownership. Controlled
        # restart drains that ownership too; it never silently abandons it.
        drained = self._drain_and_pause(
            after,
            observed_at,
            "lease expiry controlled stop",
            [
                "registry_kill_switch_engaged",
                "claims_disabled",
                "expired_attempts_terminated",
                "expired_leases_reconciled",
            ],
        )
        return ProcedureResult(
            drained.phase,
            drained.registry_revision,
            drained.actions,
            _merge_recovery(recovery, drained.recovery or RecoveryResult()),
        )

    def recover_failed_attempt(self, attempt_id: str, *, observed_at: str) -> ProcedureResult:
        """Requeue only a terminal failed attempt with no surviving ownership."""
        before = self._registry.restart_snapshot(observed_at=observed_at)
        if before.phase != RestartPhase.PAUSED or not before.kill_switch_engaged:
            raise ControlledRestartError("failed-attempt recovery requires PAUSED")
        attempt = next((item for item in before.attempts if item.id == attempt_id), None)
        if attempt is None or attempt.outcome != AttemptOutcome.FAILED or attempt.ended_at is None:
            raise ControlledRestartError("retry requires a terminal failed attempt")
        if any(item.attempt_id == attempt_id for item in before.ownership):
            raise RecoveryRequired(
                [item.lease_id for item in before.ownership if item.attempt_id == attempt_id],
                "failed attempt still owns a lease",
            )
        package_id = self._registry.requeue_failed_attempt(attempt_id, observed_at=observed_at)
        after = self._registry.restart_snapshot(observed_at=observed_at)
        current = next((item for item in after.attempts if item.id == attempt_id), None)
        if (
            package_id != attempt.package_id
            or current is None
            or current.outcome != AttemptOutcome.FAILED
            or current.ended_at is None
            or after.package_states.get(package_id) != "READY"
            or any(item.package_id == package_id for item in after.ownership)
        ):
            raise RecoveryRequired((), "failed-attempt retry did not preserve terminal history")
        return ProcedureResult(
            after.phase,
            after.revision,
            ("failed_attempt_preserved", "package_requeued"),
        )

    def handle_worker_disappearance(
        self,
        worker_id: str,
        *,
        observed_at: str,
    ) -> ProcedureResult:
        """Stop globally, record the missing worker, and reconcile all ownership."""
        stopped = self._registry.engage_kill_switch(
            changed_at=observed_at, reason=f"worker disappeared: {worker_id}"
        )
        try:
            self._supervisor.disable_claims()
        except Exception as error:
            raise RecoveryRequired(
                _ownership_identifiers(stopped),
                "kill switch engaged but claim-loop stop failed after worker disappearance",
            ) from error

        # Stop runtimes before making their Registry attempts terminal.  The
        # Registry remains authoritative for the durable recovery record.
        missing_worker_ownership = tuple(
            item for item in stopped.ownership if item.worker_id == worker_id
        )
        missing_attempts = self._terminate_owned_attempts(missing_worker_ownership)
        worker_result = self._registry.record_worker_disappearance(
            worker_id, observed_at=observed_at
        )
        actions = ["registry_kill_switch_engaged", "claims_disabled", "worker_constrained"]
        if missing_attempts:
            actions.append("missing_worker_attempts_terminated")
        remaining = self._registry.restart_snapshot(observed_at=observed_at)
        result = self._drain_and_pause(remaining, observed_at, "worker disappeared", actions)
        after = self._registry.restart_snapshot(observed_at=observed_at)
        if after.worker_availability.get(worker_id) not in {"OFFLINE", "CONSTRAINED"}:
            raise RecoveryRequired((), "missing worker was not constrained")
        combined = _merge_recovery(worker_result, result.recovery or RecoveryResult())
        return ProcedureResult(result.phase, result.registry_revision, result.actions, combined)

    def rollback_to_paused(
        self,
        *,
        observed_at: str,
        reason: str,
        expected_preservation: PreservationState,
    ) -> ProcedureResult:
        result = self.immediate_stop(observed_at=observed_at, reason=f"rollback: {reason}")
        actual = self._registry.reconcile_preservation(observed_at=observed_at)
        _assert_same_preservation(actual, expected_preservation)
        return ProcedureResult(
            result.phase,
            result.registry_revision,
            (*result.actions, "preservation_reconciled"),
            result.recovery,
        )

    def _drain_and_pause(
        self,
        stopped: RestartSnapshot,
        observed_at: str,
        reason: str,
        actions: list[str],
    ) -> ProcedureResult:
        attempt_ids = self._terminate_owned_attempts(stopped.ownership)
        if attempt_ids:
            actions.append("active_attempts_terminated")
        recovery = self._registry.reconcile_stopped_ownership(
            stopped.ownership, observed_at=observed_at, reason=reason
        )
        actions.append("registry_ownership_reconciled")
        if recovery.unresolved_ownership:
            raise RecoveryRequired(
                recovery.unresolved_ownership,
                "Registry reported unresolved stopped ownership",
            )
        final = self._finalize_if_drained(observed_at, reason)
        actions.append("registry_paused")
        return ProcedureResult(final.phase, final.revision, tuple(actions), recovery)

    def _terminate_owned_attempts(
        self, ownership: Sequence[ActiveOwnership]
    ) -> tuple[str, ...]:
        attempt_ids = tuple(
            dict.fromkeys(item.attempt_id for item in ownership if item.attempt_id is not None)
        )
        termination_failures = []
        for attempt_id in attempt_ids:
            try:
                self._supervisor.terminate_attempt(attempt_id)
            except Exception:
                termination_failures.append(attempt_id)
        if termination_failures:
            raise RecoveryRequired(
                [
                    item.lease_id
                    for item in ownership
                    if item.attempt_id in termination_failures
                ],
                "kill switch engaged but attempt termination failed",
            )
        return attempt_ids

    def _finalize_if_drained(self, observed_at: str, reason: str) -> RestartSnapshot:
        before = self._registry.restart_snapshot(observed_at=observed_at)
        active_attempts = _active_attempt_ids(before)
        if before.ownership or active_attempts:
            raise RecoveryRequired(
                _ownership_identifiers(before),
                "cannot finalize PAUSED while ownership remains active",
            )
        final = self._registry.finalize_paused(
            expected_revision=before.revision,
            changed_at=observed_at,
            reason=reason,
        )
        if final.phase != RestartPhase.PAUSED or not final.kill_switch_engaged:
            raise ControlledRestartError("Registry did not commit PAUSED with kill switch engaged")
        if final.ownership or _active_attempt_ids(final):
            raise RecoveryRequired(
                _ownership_identifiers(final),
                "Registry finalized PAUSED with active ownership",
            )
        return final
