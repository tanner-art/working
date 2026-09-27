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
from dataclasses import replace
from datetime import datetime, timedelta, timezone


ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.factory_registry.models import Evidence, ReviewInput, ReviewOutcome, TaskStatus  # noqa: E402
from scripts.factory_registry.repository import RegistryConflict  # noqa: E402
from scripts.factory_registry.shadow_dispatch import decide_shadow  # noqa: E402
from scripts.factory_registry.sqlite_registry import SQLiteRegistry  # noqa: E402
from scripts.factory_registry.codex_capacity import (  # noqa: E402
    collect_rate_limits, normalize_buckets, share_buckets,
)
from scripts.factory_registry.claude_telemetry import (  # noqa: E402
    claude_provider_signal, probe_claude_health,
)
try:  # Support both the installed runner script and package imports in tests.
    from scripts.runner.session_queue import (  # noqa: E402
        ordered_assignments, ordered_assignments_for_worker,
    )
except ImportError:  # pragma: no cover - exercised by direct script invocation.
    from session_queue import ordered_assignments, ordered_assignments_for_worker  # type: ignore # noqa: E402


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


def scope_dispatch_snapshot(snapshot, package_ids, parent_limit):
    """Restrict scheduling, not persisted history or dependency evidence."""
    allowed = set(package_ids)
    return replace(snapshot,
        active_parent_limit=min(snapshot.active_parent_limit, parent_limit),
        work_packages=tuple(
            {**item, "status": "ON_DECK"}
            if item.get("id") not in allowed and item.get("status") == "READY"
            else item for item in snapshot.work_packages
        ))


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
        github_issue: int | None = None,
        github_labels=(),
    ) -> int:
        """Return a revision only when the requested Registry pair is dispatchable."""
        if package_id is None and worker_id is None:
            return self.registry.require_live_dispatch()
        if not package_id or not worker_id:
            raise ValueError("package_id and worker_id are required together")
        observed_at = utc_now()
        snapshot = self._run_snapshot(observed_at)
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
        if (package is not None and github_issue is not None
                and self.registry.dispatch_control().get("bounded_run")):
            # In Registry-owned pilot mode, GitHub is a provenance/rendering
            # source, never the mutable work contract or scheduler.
            if package.get("source_system") != "github_issue" or package.get("source_ref") != str(github_issue):
                raise RegistryConflict("GITHUB_SOURCE_MISMATCH", package_id)
        if package is not None and package.get("kind") == "REVIEW":
            self.registry.review_input(package_id)
            implementer = self.registry.review_implementer_worker(package_id)
            if implementer == worker_id:
                raise RegistryConflict(
                    "REVIEW_INDEPENDENCE_REQUIRED",
                    f"{worker_id} implemented the target package",
                )
        decision = decide_shadow(snapshot)
        ordered = ordered_assignments(snapshot, decision.proposed_assignments)
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
        worker_ordered = ordered_assignments_for_worker(
            snapshot, decision.proposed_assignments, worker_id
        )
        if worker_ordered and (
            worker_ordered[0].package_id, worker_ordered[0].worker_id
        ) != assignment:
            raise RegistryConflict("SESSION_QUEUE_PRIORITY", worker_ordered[0].package_id)
        return self.registry.require_live_dispatch(expected_revision=snapshot.revision)

    def proposed_worker(self, package_id: str) -> str | None:
        """Return the authoritative scheduler proposal, never GitHub labels."""
        snapshot = self._run_snapshot(utc_now())
        proposed = [item.worker_id for item in ordered_assignments(
            snapshot, decide_shadow(snapshot).proposed_assignments
        ) if item.package_id == package_id]
        return proposed[0] if len(proposed) == 1 else None

    def _run_snapshot(self, observed_at):
        snapshot = self.registry.dispatch_snapshot(observed_at=observed_at)
        scope = self.registry.dispatch_control().get("bounded_run")
        return scope_dispatch_snapshot(snapshot, scope["package_ids"], scope["parent_limit"]) if scope else snapshot

    def bounded_source_issues(self) -> tuple[int, ...]:
        """Return explicitly registered GitHub issue references for this run."""
        control = self.registry.dispatch_control()
        scope = control.get("bounded_run")
        if not isinstance(scope, dict):
            return ()
        snapshot = self.registry.dispatch_snapshot(observed_at=utc_now())
        by_id = {str(item.get("id")): item for item in snapshot.work_packages}
        references = []
        for package_id in scope["package_ids"]:
            package = by_id.get(package_id)
            if package is None or package.get("source_system") != "github_issue":
                raise RegistryConflict("GITHUB_SOURCE_MISMATCH", package_id)
            reference = package.get("source_ref")
            if not isinstance(reference, str) or not reference.isdigit() or int(reference) <= 0:
                raise RegistryConflict("GITHUB_SOURCE_MISMATCH", package_id)
            references.append(int(reference))
        return tuple(sorted(set(references)))

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

    def claim_with_retry(
        self, package_id: str, *, worker_id: str, task_contract,
        lease_seconds: int, max_attempts: int = 2, github_issue: int | None = None,
        github_labels=(),
    ) -> tuple[str, int]:
        """Re-decide only a bounded number of harmless revision races."""
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        for index in range(max_attempts):
            revision = self.pre_claim(
                package_id, worker_id, task_contract=task_contract,
                github_issue=github_issue, github_labels=github_labels,
            )
            try:
                return self.claim_package(
                    package_id, worker_id=worker_id,
                    expected_revision=revision, lease_seconds=lease_seconds,
                ), revision
            except RegistryConflict as error:
                if error.code != "DISPATCH_REVISION_CHANGED" or index + 1 == max_attempts:
                    raise
        raise AssertionError("bounded claim retry did not return")

    def reserve_attempt(
        self,
        attempt_id: str,
        *,
        package_id: str,
        worker_id: str,
        expected_revision: int,
        lease_id: str | None = None,
    ) -> None:
        baseline = self._reservation_facts(
            attempt_id, package_id, worker_id, lease_id
        )
        revision = expected_revision
        for retry in range(2):
            try:
                self.registry.begin_attempt_runtime(
                    attempt_id, package_id=package_id, worker_id=worker_id,
                    runner_pid=os.getpid(), started_at=utc_now(),
                    expected_revision=revision,
                    operation_id=f"attempt-start:{attempt_id}:{revision}",
                )
                return
            except RegistryConflict as error:
                if error.code != "DISPATCH_NOT_AUTHORIZED" or retry:
                    raise
                # A heartbeat is the only harmless revision race.  Re-read the
                # exact lease, bounded-run envelope, ownership, and dispatch
                # eligibility before the one retry; any replacement or lost
                # authority fails closed.
                current = self._reservation_facts(
                    attempt_id, package_id, worker_id, baseline["lease_id"]
                )
                if ({key: value for key, value in current.items() if key != "revision"}
                        != {key: value for key, value in baseline.items() if key != "revision"}):
                    raise
                revision = int(current["revision"])

    def _reservation_facts(self, attempt_id, package_id, worker_id, lease_id):
        """Read every fact that must survive a pre-launch retry unchanged."""
        observed_at = utc_now()
        control = self.registry.dispatch_control()
        scope = control.get("bounded_run")
        if (control.get("dispatch_mode") != "LIVE"
                or control.get("kill_switch_engaged")
                or (isinstance(scope, dict) and observed_at >= scope.get("deadline", ""))):
            raise RegistryConflict("DISPATCH_NOT_AUTHORIZED")
        snapshot = self.registry.dispatch_snapshot(observed_at=observed_at)
        active = [item for item in snapshot.active_leases
                  if item.get("package_id") == package_id
                  and item.get("worker_id") == worker_id and not item.get("expired")]
        if len(active) != 1 or (lease_id is not None and active[0].get("id") != lease_id):
            raise RegistryConflict("REGISTRY_OWNERSHIP_REQUIRED")
        package = next((item for item in snapshot.work_packages if item.get("id") == package_id), None)
        if package is None or package.get("status") != "ACTIVE" or self.registry.attempt_exists(attempt_id):
            raise RegistryConflict("REGISTRY_OWNERSHIP_REQUIRED")
        # Reconstruct the pre-claim view to prove lane, capability, capacity,
        # path/allowlist and reviewer eligibility still hold without treating
        # this already-acquired lease as a competing assignment.
        worker = next((item for item in snapshot.workers if item.get("id") == worker_id), None)
        if worker is None:
            raise RegistryConflict("REGISTRY_OWNERSHIP_REQUIRED")
        candidate = replace(
            snapshot,
            work_packages=tuple(
                {**item, "status": "READY"} if item.get("id") == package_id else item
                for item in snapshot.work_packages
            ),
            workers=tuple(
                {**item, "availability": "IDLE"} if item.get("id") == worker_id else item
                for item in snapshot.workers
            ),
            active_leases=tuple(item for item in snapshot.active_leases if item.get("id") != active[0].get("id")),
        )
        if isinstance(scope, dict):
            candidate = scope_dispatch_snapshot(
                candidate, scope["package_ids"], scope["parent_limit"]
            )
        eligible = {
            (item.package_id, item.worker_id)
            for item in decide_shadow(candidate).pair_evaluations if item.eligible
        }
        return {
            "revision": int(control["revision"]),
            "lease_id": active[0].get("id"),
            "bounded_run": scope,
            "deadline": scope.get("deadline") if isinstance(scope, dict) else None,
            "eligible": (package_id, worker_id) in eligible,
        }

    def pre_launch(self) -> int:
        return self.registry.require_live_dispatch()

    def integration_base(self) -> str:
        """Read the activated base ref; legacy control remains pinned to main."""
        scope = self.registry.dispatch_control().get("bounded_run")
        return scope["base_ref"] if isinstance(scope, dict) else "main"

    def refresh_configured_capacity(self, config, *, busy_workers=()) -> tuple[dict, ...]:
        """Run independent read-only observations without worker upserts.

        An unavailable source is returned as a content-free error item, rather
        than preventing another configured source from publishing its own real
        observation.  Percentage-collector failures deliberately publish no
        replacement fact: the affected worker remains stale/constrained.
        """
        collectors = config.get("capacity_collectors", {})
        if not isinstance(collectors, dict):
            raise ValueError("capacity_collectors must be an object")
        written = []
        snapshot = self.registry.dispatch_snapshot(observed_at=utc_now())
        workers = {item["id"]: item for item in snapshot.workers}
        busy_workers = set(busy_workers) | {
            lease["worker_id"] for lease in snapshot.active_leases
            if isinstance(lease.get("worker_id"), str)
        }
        for worker_id, item in collectors.items():
            if not isinstance(worker_id, str) or not isinstance(item, dict):
                raise ValueError("capacity collector entries must be objects")
            try:
                sample = collect_rate_limits(
                    item.get("executable", ""), item.get("codex_home", ""),
                    timeout=item.get("timeout_seconds", 10),
                    account_environment=item.get("environment", {}),
                )
                observations = normalize_buckets(worker_id, sample)
                self.registry.record_worker_capacity_observations(
                    worker_id, observations, recorded_at=utc_now()
                )
                written.append({"worker_id": worker_id, "observations": observations})
            except Exception as error:
                # Do not turn a failed read into a fresh capacity observation.
                written.append({"worker_id": worker_id, "observations": (),
                                "error_class": type(error).__name__})
                continue
            # Aliases are declarative only.  Their existing Registry binding,
            # rather than a config claim, is the authority for account identity.
            for alias in item.get("shared_account_aliases", ()):
                if not isinstance(alias, str) or not alias:
                    raise ValueError("shared_account_aliases must contain worker ids")
                try:
                    target = workers.get(alias)
                    binding = (target or {}).get("provider_diagnostics", {}).get("capacity_pool")
                    shared = share_buckets(alias, sample, expected_account_identity_sha256=binding)
                    self.registry.record_worker_capacity_observations(alias, shared, recorded_at=utc_now())
                    written.append({"worker_id": alias, "observations": shared})
                except Exception as error:
                    # An alias mismatch is target-local; no other alias loses
                    # its independently verified observation.
                    written.append({"worker_id": alias, "observations": (),
                                    "error_class": type(error).__name__})
        probe = config.get("claude_health_probe")
        if probe is not None:
            if not isinstance(probe, dict):
                raise ValueError("claude_health_probe must be an object")
            worker_id = probe.get("worker_id", "claude")
            if worker_id not in workers or worker_id in busy_workers:
                return tuple(written)
            cadence = probe.get("cadence_seconds", 60)
            if isinstance(cadence, bool) or not isinstance(cadence, (int, float)) or not 1 <= cadence <= 900:
                raise ValueError("claude_health_probe cadence_seconds must be between one and 900")
            now = datetime.fromisoformat(utc_now().replace("Z", "+00:00"))
            prior = [item for item in snapshot.usage_observations if item.get("worker_id") == worker_id
                     and item.get("capacity_scope") == "provider_signal"]
            if prior:
                latest = max(item["observed_at"] for item in prior)
                try:
                    parsed = datetime.fromisoformat(latest.replace("Z", "+00:00"))
                except (TypeError, ValueError):
                    parsed = None
                if parsed is not None and 0 <= (now - parsed).total_seconds() < cadence:
                    return tuple(written)
            command = probe.get("command")
            if command is None:
                command = config.get("agents", {}).get(worker_id, {}).get("command")
            try:
                result = probe_claude_health(command, timeout=probe.get("timeout_seconds", 20))
            except Exception:
                # The wrapper was not usable.  This is a real failed launch,
                # not a healthy substitute for the expired signal.
                result = {"succeeded": False, "limit_signal": None,
                          "returncode": None, "observed_at": utc_now()}
            observation = claude_provider_signal(worker_id, observed_at=result["observed_at"],
                succeeded=result["succeeded"], limit_signal=result["limit_signal"], returncode=result["returncode"])
            self.registry.record_worker_capacity_observations(worker_id, (observation,), recorded_at=utc_now())
            written.append({"worker_id": worker_id, "observations": (observation,)})
        return tuple(written)

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

    def observe_worker_heartbeat(self, worker_id: str, *, observed_at: str | None = None) -> int:
        """Record runner liveness without invoking worker reconfiguration."""
        return self.registry.record_worker_heartbeat(
            worker_id, observed_at=observed_at or utc_now()
        )

    def succeed(self, attempt_id: str, *, review_inputs: tuple[ReviewInput, ...] = (), ended_at: str | None = None) -> None:
        self.registry.finish_attempt_runtime(
            attempt_id,
            ended_at=ended_at or utc_now(),
            outcome="SUCCEEDED",
            next_status=TaskStatus.VERIFY_REVIEW,
            reason="runner completed and opened review",
            review_inputs=review_inputs,
            operation_id=f"attempt-finish:{attempt_id}",
        )

    def record_review_input(self, review_input: ReviewInput) -> None:
        self.registry.record_review_input(review_input, operation_id=f"review-input:{review_input.id}")

    def implementation_review_inputs(self, *, target_package_id: str, implementation_attempt_id: str, implementation_commit: str, base_commit: str, pr_url: str, contract: dict, validation_evidence: dict, recorded_at: str) -> tuple[ReviewInput, ...]:
        snapshot = self.registry.dispatch_snapshot(observed_at=utc_now())
        review_ids = [package["id"] for package in snapshot.work_packages if package.get("kind") == "REVIEW" and target_package_id in {dependency["dependency_id"] for dependency in snapshot.dependencies if dependency["package_id"] == package.get("id")}]
        digest = queue_contract_digest(contract)
        return tuple(
            ReviewInput(id=f"review-input:{review_id}:{implementation_attempt_id}", review_package_id=review_id, target_package_id=target_package_id, implementation_attempt_id=implementation_attempt_id, implementation_commit=implementation_commit, base_commit=base_commit, pr_url=pr_url, contract_sha256=digest, contract=contract, validation_evidence=validation_evidence, recorded_at=recorded_at)
            for review_id in review_ids
        )

    def review_input(self, review_package_id: str) -> ReviewInput:
        return ReviewInput(**self.registry.review_input(review_package_id))

    def record_review_outcome(self, outcome: ReviewOutcome, evidence: Evidence, *, expected_revision: int) -> int:
        return self.registry.record_review_outcome(outcome, evidence=evidence, expected_revision=expected_revision, operation_id=f"review-outcome:{outcome.id}")

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
