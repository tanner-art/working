"""Opt-in Registry gate for the controlled runner path.

Legacy GitHub polling remains unchanged when ``registry_database`` is absent.
When configured, every claim and provider launch fails closed through the
authoritative Registry and attempt/process provenance is persisted there.
"""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import signal
import sys
import time
from datetime import datetime, timedelta, timezone


ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.factory_registry.models import (  # noqa: E402
    Evidence,
    ReviewOutcome,
    ReviewOutcomeState,
    TaskStatus,
)
from scripts.factory_registry.repository import RegistryConflict  # noqa: E402
from scripts.factory_registry.shadow_dispatch import decide_shadow  # noqa: E402
from scripts.factory_registry.sqlite_registry import SQLiteRegistry  # noqa: E402


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def queue_contract_digest(value) -> str:
    """Hash the normalized queue body without persisting its instructions."""
    if not isinstance(value, dict):
        raise ValueError("queue contract must be an object")
    encoded = json.dumps(
        value, separators=(",", ":"), sort_keys=True, ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def terminate_recorded_process_group(pgid: int, timeout: float = 10) -> None:
    """Synchronously stop a recorded process group owned by another runner."""
    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            os.killpg(pgid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.05)
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            os.killpg(pgid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.05)
    raise RuntimeError(f"process group {pgid} survived SIGKILL")


class RunnerRegistryControl:
    def __init__(self, database: pathlib.Path) -> None:
        self.database = pathlib.Path(database)
        if not self.database.is_absolute():
            raise ValueError("registry_database must be an absolute path")
        self.registry = SQLiteRegistry(self.database)

    @classmethod
    def from_config(cls, config):
        database = config.get("registry_database")
        if database is None:
            return None
        if not isinstance(database, str) or not database:
            raise ValueError("registry_database must be a non-empty absolute path")
        return cls(pathlib.Path(database))

    def pre_claim(
        self,
        package_id: str | None = None,
        worker_id: str | None = None,
        *,
        task_contract=None,
    ) -> int:
        """Return a revision only when the requested Registry pair is dispatchable."""
        if package_id is None and worker_id is None:
            return self.registry.require_live_dispatch()
        if not package_id or not worker_id:
            raise ValueError("package_id and worker_id are required together")
        observed_at = utc_now()
        snapshot = self.registry.dispatch_snapshot(observed_at=observed_at)
        package = next(
            (
                value for value in getattr(snapshot, "work_packages", ())
                if value.get("id") == package_id
            ),
            None,
        )
        if task_contract is not None:
            expected = (
                package.get("provider_diagnostics", {}).get("queue_contract_sha256")
                if package is not None else None
            )
            actual = queue_contract_digest(task_contract)
            if not isinstance(expected, str) or expected != actual:
                raise RegistryConflict("QUEUE_CONTRACT_MISMATCH", package_id)
        if package is not None and package.get("kind") == "REVIEW":
            implementer = self.registry.review_implementer_worker(package_id)
            if implementer == worker_id:
                raise RegistryConflict(
                    "REVIEW_INDEPENDENCE_REQUIRED",
                    f"{worker_id} implemented the target package",
                )
        decision = decide_shadow(snapshot)
        assignment = (package_id, worker_id)
        eligible = {
            (item.package_id, item.worker_id) for item in decision.proposed_assignments
        }
        if assignment not in eligible:
            matching = next(
                (
                    item for item in decision.pair_evaluations
                    if (item.package_id, item.worker_id) == assignment
                ),
                None,
            )
            reasons = (
                ",".join(reason.code for reason in matching.reasons)
                if matching is not None else "PAIR_NOT_FOUND"
            )
            raise RegistryConflict("DISPATCH_PAIR_INELIGIBLE", reasons)
        return self.registry.require_live_dispatch(expected_revision=snapshot.revision)

    def claim_package(
        self,
        package_id: str,
        *,
        worker_id: str,
        expected_revision: int,
        lease_seconds: int,
    ) -> str:
        if isinstance(lease_seconds, bool) or not isinstance(lease_seconds, int) or lease_seconds <= 0:
            raise ValueError("registry lease duration must be a positive integer")
        acquired = datetime.now(timezone.utc)
        lease = self.registry.acquire_lease(
            package_id,
            worker_id,
            acquired_at=acquired.isoformat(),
            expires_at=(acquired + timedelta(seconds=lease_seconds)).isoformat(),
            expected_dispatch_revision=expected_revision,
            operation_id=f"claim:{package_id}:{worker_id}:{expected_revision}",
        )
        return lease.id

    def reserve_attempt(
        self,
        attempt_id: str,
        *,
        package_id: str,
        worker_id: str,
        expected_revision: int,
        task_contract=None,
    ) -> None:
        diagnostics = {}
        if task_contract is not None:
            diagnostics = {
                "task_contract": task_contract,
                "task_contract_sha256": queue_contract_digest(task_contract),
            }
        self.registry.begin_attempt_runtime(
            attempt_id,
            package_id=package_id,
            worker_id=worker_id,
            runner_pid=os.getpid(),
            started_at=utc_now(),
            expected_revision=expected_revision,
            provider_diagnostics=diagnostics,
            operation_id=f"attempt-start:{attempt_id}",
        )

    def record_delivery(
        self,
        attempt_id: str,
        *,
        package_id: str,
        branch: str,
        base_commit: str,
        implementation_commit: str,
        pr_url: str,
    ) -> None:
        recorded_at = utc_now()
        self.registry.record_attempt_delivery(
            attempt_id,
            branch=branch,
            base_commit=base_commit,
            implementation_commit=implementation_commit,
            pr_url=pr_url,
            validation_evidence=Evidence(
                id=f"validation:{attempt_id}",
                package_id=package_id,
                kind="validation",
                uri=None,
                summary="Runner validation passed for the delivered implementation commit.",
                recorded_at=recorded_at,
                metadata={
                    "attempt_id": attempt_id,
                    "base_commit": base_commit,
                    "implementation_commit": implementation_commit,
                    "checks": ["pnpm check", "git diff --check"],
                },
            ),
            operation_id=f"attempt-delivery:{attempt_id}",
        )

    def prepare_review_input(
        self, review_package_id: str, *, reviewer_worker_id: str, review_attempt_id: str
    ):
        return self.registry.prepare_review_input(
            review_package_id,
            reviewer_worker_id=reviewer_worker_id,
            review_attempt_id=review_attempt_id,
            requested_at=utc_now(),
            operation_id=f"prepare-review-input:{review_attempt_id}",
        )

    def pre_launch(self) -> int:
        return self.registry.require_live_dispatch()

    def record_process(self, attempt_id: str, *, pid: int, pgid: int) -> None:
        self.registry.record_attempt_process(
            attempt_id,
            agent_pid=pid,
            agent_pgid=pgid,
            recorded_at=utc_now(),
        )

    def renew_runtime(
        self,
        attempt_id: str,
        lease_id: str,
        *,
        lease_seconds: int,
    ) -> None:
        if isinstance(lease_seconds, bool) or not isinstance(lease_seconds, int) or lease_seconds <= 1:
            raise ValueError("registry lease duration must exceed one second")
        now = datetime.now(timezone.utc)
        self.registry.renew_attempt_runtime(
            attempt_id,
            lease_id,
            now=now.isoformat(),
            expires_at=(now + timedelta(seconds=lease_seconds)).isoformat(),
        )

    def succeed(self, attempt_id: str) -> None:
        self.registry.finish_attempt_runtime(
            attempt_id,
            ended_at=utc_now(),
            outcome="SUCCEEDED",
            next_status=TaskStatus.VERIFY_REVIEW,
            reason="runner completed and opened review",
            operation_id=f"attempt-finish:{attempt_id}",
        )

    def complete_review(self, attempt_id: str, review_input, verdict) -> None:
        decided_at = utc_now()
        self.registry.finish_attempt_runtime(
            attempt_id,
            ended_at=decided_at,
            outcome="SUCCEEDED",
            next_status=TaskStatus.VERIFY_REVIEW,
            reason="reviewer returned a valid structured verdict",
            operation_id=f"attempt-finish:{attempt_id}",
        )
        evidence_id = f"review-verdict:{attempt_id}"
        evidence = Evidence(
            id=evidence_id,
            package_id=review_input.review_package_id,
            kind="review",
            uri=None,
            summary=f"Structured review verdict: {verdict.decision}",
            recorded_at=decided_at,
            metadata={
                "schema_version": 1,
                "attempt_id": attempt_id,
                "decision": verdict.decision,
                "review_input_evidence_id": verdict.review_input_evidence_id,
                "reviewed_commit": verdict.reviewed_commit,
            },
        )
        self.registry.record_review_outcome(
            ReviewOutcome(
                id=f"review-outcome:{attempt_id}",
                review_package_id=review_input.review_package_id,
                target_package_id=review_input.target_package_id,
                implementer_worker_id=review_input.implementer_worker_id,
                reviewer_worker_id=review_input.reviewer_worker_id,
                requested_at=review_input.requested_at,
                decided_at=decided_at,
                state=ReviewOutcomeState(verdict.decision),
                findings=verdict.findings,
                changes_requested=verdict.changes_requested,
                approval_evidence_ids=(evidence_id,),
            ),
            evidence=evidence,
            expected_revision=self.registry.dispatch_control()["revision"],
            operation_id=f"review-outcome:{attempt_id}",
        )

    def fail(self, attempt_id: str, detail: str) -> None:
        ended_at = utc_now()
        try:
            self.registry.finish_attempt_runtime(
                attempt_id,
                ended_at=ended_at,
                outcome="FAILED",
                next_status=TaskStatus.BLOCKED,
                reason="runner attempt failed",
                failure_detail=detail,
                operation_id=f"attempt-finish:{attempt_id}",
            )
        except RegistryConflict as error:
            if error.code not in {
                "LEASE_NOT_ACTIVE", "PACKAGE_NOT_ACTIVE",
            }:
                raise
            recovered = self.registry.recover_attempt_runtime(
                attempt_id,
                ended_at=ended_at,
                reason="runner fail-closed runtime recovery",
                failure_detail=detail,
            )
            if not recovered:
                raise

    def block(self, attempt_id: str, detail: str) -> None:
        self.registry.finish_attempt_runtime(
            attempt_id,
            ended_at=utc_now(),
            outcome="BLOCKED",
            next_status=TaskStatus.BLOCKED,
            reason="reviewer could not inspect the assigned target",
            failure_detail=detail,
            operation_id=f"attempt-finish:{attempt_id}",
        )

    def fail_if_active(self, attempt_id: str, detail: str) -> bool:
        """Close stale ownership once; an already terminal attempt is a safe no-op."""
        try:
            self.fail(attempt_id, detail)
            return True
        except RegistryConflict as error:
            if "ATTEMPT_RUNTIME_NOT_ACTIVE" not in str(error):
                raise
            return False

    def abort_claim(self, lease_id: str, detail: str) -> None:
        self.registry.release_lease(
            lease_id,
            released_at=utc_now(),
            reason=detail,
            next_status=TaskStatus.BLOCKED,
            operation_id=f"lease-abort:{lease_id}",
        )

    def engage_stop(self, reason: str) -> int:
        return self.registry.engage_dispatch_kill_switch(
            changed_at=utc_now(), reason=reason
        )

    def _reconcile_runtimes(self, runtimes, *, terminate) -> dict[str, tuple[str, ...]]:
        resolved = []
        unresolved = []
        for runtime in sorted(runtimes, key=lambda item: item["attempt_id"]):
            attempt_id = runtime["attempt_id"]
            try:
                pgid = runtime.get("agent_pgid")
                if pgid is not None:
                    terminate(int(pgid))
                self.registry.recover_attempt_runtime(
                    attempt_id,
                    ended_at=utc_now(),
                    reason="global controlled stop",
                    failure_detail="runtime stopped during fail-closed reconciliation",
                )
                resolved.append(attempt_id)
            except Exception as error:
                unresolved.append(attempt_id)
                self.registry.record_runtime_recovery_failure(
                    attempt_id,
                    observed_at=utc_now(),
                    detail=f"{type(error).__name__}: {error}",
                )
        for lease in self.registry.active_unbound_leases():
            lease_id = lease["lease_id"]
            ownership_id = f"lease:{lease_id}"
            try:
                self.registry.recover_stopped_lease(
                    lease_id,
                    ended_at=utc_now(),
                    reason="global controlled stop",
                    failure_detail="lease-only ownership stopped during fail-closed reconciliation",
                )
                resolved.append(ownership_id)
            except Exception as error:
                unresolved.append(ownership_id)
                self.registry.record_lease_recovery_failure(
                    lease_id,
                    observed_at=utc_now(),
                    detail=f"{type(error).__name__}: {error}",
                )
        return {
            "resolved": tuple(resolved),
            "unresolved": tuple(unresolved),
        }

    def reconcile_stopping_runtimes(
        self, *, terminate=terminate_recorded_process_group
    ) -> dict[str, tuple[str, ...]]:
        control = self.registry.dispatch_control()
        if control["dispatch_mode"] != "STOPPING" or not control["kill_switch_engaged"]:
            raise RegistryConflict("DISPATCH_NOT_STOPPING")
        return self._reconcile_runtimes(
            self.registry.active_attempt_runtimes(), terminate=terminate
        )

    def handle_worker_disappearance(
        self,
        worker_id: str,
        *,
        terminate=terminate_recorded_process_group,
    ) -> dict[str, tuple[str, ...]]:
        runtimes = self.registry.stop_for_worker_disappearance(
            worker_id,
            observed_at=utc_now(),
            reason=f"worker disappeared: {worker_id}",
        )
        result = self._reconcile_runtimes(runtimes, terminate=terminate)
        if result["unresolved"]:
            raise RegistryConflict(
                "RUNTIME_RECONCILIATION_REQUIRED",
                ",".join(result["unresolved"]),
            )
        if self.registry.active_attempt_runtimes() or self.registry.active_unbound_leases():
            raise RegistryConflict("RUNTIME_RECONCILIATION_REQUIRED", "post-read not empty")
        self.finalize_paused(reason=f"worker disappearance reconciled: {worker_id}")
        return result

    def finalize_paused(self, *, reason: str) -> int:
        control = self.registry.dispatch_control()
        if control["dispatch_mode"] != "STOPPING" or not control["kill_switch_engaged"]:
            raise RegistryConflict("DISPATCH_NOT_STOPPING")
        return self.registry.set_dispatch_control(
            expected_revision=control["revision"],
            expected_mode="STOPPING",
            new_mode="PAUSED",
            kill_switch_engaged=True,
            changed_at=utc_now(),
            reason=reason,
            operation_id=f"return-paused:{control['revision']}:{reason}",
        )
