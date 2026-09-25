"""Opt-in Registry gate for the controlled runner path.

Legacy GitHub polling remains unchanged when ``registry_database`` is absent.
When configured, every claim and provider launch fails closed through the
authoritative Registry and attempt/process provenance is persisted there.
"""

from __future__ import annotations

import os
import pathlib
import sys
from datetime import datetime, timedelta, timezone


ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.factory_registry.models import TaskStatus  # noqa: E402
from scripts.factory_registry.repository import RegistryConflict  # noqa: E402
from scripts.factory_registry.shadow_dispatch import decide_shadow  # noqa: E402
from scripts.factory_registry.sqlite_registry import SQLiteRegistry  # noqa: E402


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


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

    def pre_claim(self, package_id: str | None = None, worker_id: str | None = None) -> int:
        """Return a revision only when the requested Registry pair is dispatchable."""
        if package_id is None and worker_id is None:
            return self.registry.require_live_dispatch()
        if not package_id or not worker_id:
            raise ValueError("package_id and worker_id are required together")
        observed_at = utc_now()
        snapshot = self.registry.dispatch_snapshot(observed_at=observed_at)
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
        )
        return lease.id

    def reserve_attempt(
        self,
        attempt_id: str,
        *,
        package_id: str,
        worker_id: str,
        expected_revision: int,
    ) -> None:
        self.registry.begin_attempt_runtime(
            attempt_id,
            package_id=package_id,
            worker_id=worker_id,
            runner_pid=os.getpid(),
            started_at=utc_now(),
            expected_revision=expected_revision,
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

    def succeed(self, attempt_id: str) -> None:
        self.registry.finish_attempt_runtime(
            attempt_id,
            ended_at=utc_now(),
            outcome="SUCCEEDED",
            next_status=TaskStatus.VERIFY_REVIEW,
            reason="runner completed and opened review",
        )

    def fail(self, attempt_id: str, detail: str) -> None:
        self.registry.finish_attempt_runtime(
            attempt_id,
            ended_at=utc_now(),
            outcome="FAILED",
            next_status=TaskStatus.BLOCKED,
            reason="runner attempt failed",
            failure_detail=detail,
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
        )

    def engage_stop(self, reason: str) -> int:
        return self.registry.engage_dispatch_kill_switch(
            changed_at=utc_now(), reason=reason
        )

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
        )
