"""Read-only live observation adapter for Factory shadow dispatch.

The adapter reads the installed runner's sanitized heartbeat, usage, and queue
files and projects those observations onto an existing ``DispatchSnapshot``.
It never receives a registry writer, queue writer, service controller, process
launcher, GitHub client, or lease authority.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .models import DispatchSnapshot
from .shadow_dispatch import (
    LegacyComparison,
    LegacyObservation,
    ShadowDecision,
    ShadowPolicy,
    Assignment,
    compare_with_legacy,
    decide_shadow,
    snapshot_fingerprint,
)


CAPACITY_SCOPES = frozenset(("short_window", "weekly_window", "billing_budget"))
CAPACITY_CLASSES = frozenset(("FULL_CAPABILITY_REQUIRED", "ECONOMY_ELIGIBLE"))
IDLE_HEARTBEAT_STATES = frozenset(("idle", "polling"))
BUSY_HEARTBEAT_STATES = frozenset(("starting", "agent", "validation", "review"))


class LiveObservationError(ValueError):
    """A live input was unsafe, malformed, or internally inconsistent."""


@dataclass(frozen=True)
class ProposedObservationPolicy:
    """Unratified policy values used only by shadow observation."""

    heartbeat_fresh_seconds: int = 180
    usage_fresh_seconds: int = 900
    sweep_seconds: int = 900
    sweep_tolerance_seconds: int = 60
    comparison_tolerance_seconds: int = 60
    slowdown_percent: float = 70.0
    stop_percent: float = 80.0

    def __post_init__(self) -> None:
        if (
            self.heartbeat_fresh_seconds <= 0
            or self.usage_fresh_seconds <= 0
            or self.sweep_seconds <= 0
            or self.sweep_tolerance_seconds < 0
            or self.comparison_tolerance_seconds < 0
            or not 0 <= self.slowdown_percent < self.stop_percent <= 100
        ):
            raise LiveObservationError("invalid proposed observation policy")

    def shadow_policy(self) -> ShadowPolicy:
        return ShadowPolicy(
            heartbeat_fresh_seconds=self.heartbeat_fresh_seconds,
            usage_fresh_seconds=self.usage_fresh_seconds,
            scheduled_sweep_seconds=self.sweep_seconds,
            scheduled_sweep_tolerance_seconds=self.sweep_tolerance_seconds,
            legacy_observation_tolerance_seconds=self.comparison_tolerance_seconds,
            worker_stop_percent=self.stop_percent,
            allowed_usage_states=("GREEN",),
        )


@dataclass(frozen=True)
class WorkerObservationBinding:
    runner_worker_id: str
    registry_worker_id: str
    capacity_scopes: tuple[str, ...] = ("short_window", "weekly_window")
    usage_account_by_scope: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if not self.runner_worker_id or not self.registry_worker_id:
            raise LiveObservationError("worker bindings require runner and registry IDs")
        scopes = tuple(str(value) for value in self.capacity_scopes)
        if not scopes or len(scopes) != len(set(scopes)) or not set(scopes) <= CAPACITY_SCOPES:
            raise LiveObservationError("capacity scopes must be unique approved proposal scopes")
        mapped_scopes = [str(value[0]) for value in self.usage_account_by_scope]
        mapped_accounts = [str(value[1]) for value in self.usage_account_by_scope]
        if (
            len(mapped_scopes) != len(set(mapped_scopes))
            or len(mapped_accounts) != len(set(mapped_accounts))
            or not set(mapped_scopes) <= set(scopes)
            or any(not value for value in mapped_accounts)
        ):
            raise LiveObservationError(
                "usage mappings must be one-to-one and target configured capacity scopes"
            )


@dataclass(frozen=True)
class PreservationExpectation:
    sha256: str
    worktree_count: int
    dirty_worktree_count: int
    unmerged_branch_count: int
    unexplained_record_count: int = 0
    active_lease_count: int = 0
    active_legacy_record_count: int = 0

    def __post_init__(self) -> None:
        if len(self.sha256) != 64 or any(value not in "0123456789abcdef" for value in self.sha256):
            raise LiveObservationError("preservation SHA-256 must be lowercase hexadecimal")
        counts = (
            self.worktree_count,
            self.dirty_worktree_count,
            self.unmerged_branch_count,
            self.unexplained_record_count,
            self.active_lease_count,
            self.active_legacy_record_count,
        )
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in counts
        ):
            raise LiveObservationError("preservation counts must be non-negative integers")


@dataclass(frozen=True)
class ObservationPlan:
    workers: tuple[WorkerObservationBinding, ...]
    preservation: PreservationExpectation
    policy: ProposedObservationPolicy = field(default_factory=ProposedObservationPolicy)

    def __post_init__(self) -> None:
        runner_ids = [value.runner_worker_id for value in self.workers]
        registry_ids = [value.registry_worker_id for value in self.workers]
        if len(runner_ids) != len(set(runner_ids)) or len(registry_ids) != len(set(registry_ids)):
            raise LiveObservationError("worker bindings must be one-to-one")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ObservationPlan":
        if not isinstance(value, Mapping):
            raise LiveObservationError("observation plan must be an object")
        raw_workers = value.get("workers")
        raw_preservation = value.get("preservation")
        raw_policy = value.get("policy", {})
        if not isinstance(raw_workers, list) or not isinstance(raw_preservation, Mapping):
            raise LiveObservationError("plan requires workers and preservation")
        if not isinstance(raw_policy, Mapping):
            raise LiveObservationError("policy must be an object")
        workers = []
        for raw in raw_workers:
            if not isinstance(raw, Mapping):
                raise LiveObservationError("worker binding must be an object")
            usage_map = raw.get("usage_account_by_scope", {})
            if not isinstance(usage_map, Mapping):
                raise LiveObservationError("usage_account_by_scope must be an object")
            workers.append(
                WorkerObservationBinding(
                    runner_worker_id=str(raw.get("runner_worker_id", "")),
                    registry_worker_id=str(raw.get("registry_worker_id", "")),
                    capacity_scopes=tuple(
                        raw.get("capacity_scopes", ("short_window", "weekly_window"))
                    ),
                    usage_account_by_scope=tuple(
                        sorted((str(scope), str(account)) for scope, account in usage_map.items())
                    ),
                )
            )
        try:
            preservation = PreservationExpectation(
                sha256=str(raw_preservation["sha256"]),
                worktree_count=int(raw_preservation["worktree_count"]),
                dirty_worktree_count=int(raw_preservation["dirty_worktree_count"]),
                unmerged_branch_count=int(raw_preservation["unmerged_branch_count"]),
                unexplained_record_count=int(
                    raw_preservation.get("unexplained_record_count", 0)
                ),
                active_lease_count=int(raw_preservation.get("active_lease_count", 0)),
                active_legacy_record_count=int(
                    raw_preservation.get("active_legacy_record_count", 0)
                ),
            )
            policy = ProposedObservationPolicy(**dict(raw_policy))
        except (KeyError, TypeError, ValueError) as error:
            raise LiveObservationError("invalid preservation expectation or policy") from error
        return cls(tuple(workers), preservation, policy)


@dataclass(frozen=True)
class CapturedSource:
    label: str
    path: Path = field(repr=False, compare=False)
    before_sha256: str
    semantic_sha256: str
    volatile: bool
    # Only the preservation snapshot is retained because reconciliation needs
    # its parsed provenance. Runner config, queue, usage, and heartbeat bytes
    # are intentionally discarded after normalization; they may contain
    # commands, environment values, or provider-specific identifiers.
    raw: bytes | None = field(default=None, repr=False, compare=False)


@dataclass(frozen=True)
class SourceProof:
    label: str
    before_sha256: str
    after_sha256: str
    volatile: bool
    content_unchanged: bool
    semantic_unchanged: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "before_sha256": self.before_sha256,
            "after_sha256": self.after_sha256,
            "volatile": self.volatile,
            "content_unchanged": self.content_unchanged,
            "semantic_unchanged": self.semantic_unchanged,
        }


@dataclass(frozen=True)
class PreservationReconciliation:
    source_sha256: str
    worktree_count: int
    dirty_worktree_count: int
    unmerged_branch_count: int
    unexplained_record_count: int
    active_lease_count: int
    active_legacy_record_count: int
    passed: bool
    failures: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_sha256": self.source_sha256,
            "worktree_count": self.worktree_count,
            "dirty_worktree_count": self.dirty_worktree_count,
            "unmerged_branch_count": self.unmerged_branch_count,
            "unexplained_record_count": self.unexplained_record_count,
            "active_lease_count": self.active_lease_count,
            "active_legacy_record_count": self.active_legacy_record_count,
            "passed": self.passed,
            "failures": list(self.failures),
        }


@dataclass(frozen=True)
class LiveObservation:
    observed_at: str
    worker_updates: tuple[Mapping[str, Any], ...]
    usage_observations: tuple[Mapping[str, Any], ...]
    legacy_observation: LegacyObservation
    queue_status_counts: Mapping[str, int]
    warnings: tuple[str, ...]
    sources: tuple[CapturedSource, ...] = field(repr=False)


@dataclass(frozen=True)
class LiveSweepEvidence:
    schema_version: int
    observed_at: str
    base_snapshot_sha256: str
    projected_snapshot_sha256: str
    source_proofs: tuple[SourceProof, ...]
    preservation: PreservationReconciliation
    warnings: tuple[str, ...]
    queue_status_counts: Mapping[str, int]
    decision: ShadowDecision
    legacy_comparison: LegacyComparison
    passed: bool
    failures: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "observed_at": self.observed_at,
            "base_snapshot_sha256": self.base_snapshot_sha256,
            "projected_snapshot_sha256": self.projected_snapshot_sha256,
            "source_proofs": [value.as_dict() for value in self.source_proofs],
            "preservation": self.preservation.as_dict(),
            "warnings": list(self.warnings),
            "queue_status_counts": dict(sorted(self.queue_status_counts.items())),
            "decision": self.decision.as_dict(),
            "legacy_comparison": self.legacy_comparison.as_dict(),
            "passed": self.passed,
            "failures": list(self.failures),
        }

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), separators=(",", ":"), sort_keys=True)


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_time(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise LiveObservationError(f"{field} must be an ISO-8601 timestamp")
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as error:
        raise LiveObservationError(f"invalid {field}") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise LiveObservationError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _unix_time(value: Any, *, field: str) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise LiveObservationError(f"{field} must be a finite Unix timestamp")
    try:
        return datetime.fromtimestamp(value, timezone.utc).isoformat(
            timespec="microseconds"
        ).replace("+00:00", "Z")
    except (OverflowError, OSError, ValueError) as error:
        raise LiveObservationError(f"invalid {field}") from error


def _json_object(raw: bytes, *, label: str) -> Mapping[str, Any]:
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise LiveObservationError(f"{label} is not valid JSON") from error
    if not isinstance(value, Mapping):
        raise LiveObservationError(f"{label} must be a JSON object")
    return value


def _heartbeat_semantic(raw: bytes) -> str:
    try:
        value = _json_object(raw, label="heartbeat")
    except LiveObservationError:
        return _sha256(b"INVALID\0" + raw)
    semantic = {
        "worker": value.get("worker"),
        "task": value.get("task"),
        "status": value.get("status"),
    }
    return _sha256(json.dumps(semantic, separators=(",", ":"), sort_keys=True).encode())


def _capture_source(
    path: Path,
    label: str,
    *,
    volatile: bool,
    retain_raw: bool = False,
) -> tuple[bytes, CapturedSource]:
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise LiveObservationError(f"{label} unavailable: {error.__class__.__name__}") from error
    semantic = _heartbeat_semantic(raw) if volatile else _sha256(raw)
    return raw, CapturedSource(
        label,
        path,
        _sha256(raw),
        semantic,
        volatile,
        raw if retain_raw else None,
    )


def _missing_heartbeat_update(binding: WorkerObservationBinding) -> Mapping[str, Any]:
    return {
        "runner_worker_id": binding.runner_worker_id,
        "registry_worker_id": binding.registry_worker_id,
        "availability": "CONSTRAINED",
        "last_heartbeat_at": None,
        "heartbeat_status": "missing_or_invalid",
        "task_id": None,
    }


def _heartbeat_update(
    raw: bytes, binding: WorkerObservationBinding
) -> tuple[Mapping[str, Any], Assignment | None, tuple[str, ...]]:
    value = _json_object(raw, label=f"heartbeat:{binding.runner_worker_id}")
    source_worker = value.get("worker")
    if source_worker != binding.runner_worker_id:
        raise LiveObservationError(
            f"heartbeat worker mismatch for {binding.runner_worker_id}"
        )
    status = value.get("status")
    if not isinstance(status, str) or not status:
        raise LiveObservationError(f"heartbeat status missing for {binding.runner_worker_id}")
    normalized_status = status.lower()
    if normalized_status in IDLE_HEARTBEAT_STATES:
        availability = "IDLE"
    elif normalized_status in BUSY_HEARTBEAT_STATES:
        availability = "BUSY"
    else:
        availability = "CONSTRAINED"
    heartbeat_at = _unix_time(value.get("time"), field="heartbeat time")
    task = value.get("task")
    warnings = []
    assignment = None
    if availability == "BUSY":
        if isinstance(task, str) and task:
            assignment = Assignment(task, binding.registry_worker_id)
        else:
            warnings.append(f"ACTIVE_HEARTBEAT_WITHOUT_TASK:{binding.runner_worker_id}")
    return (
        {
            "runner_worker_id": binding.runner_worker_id,
            "registry_worker_id": binding.registry_worker_id,
            "availability": availability,
            "last_heartbeat_at": heartbeat_at,
            "heartbeat_status": normalized_status,
            "task_id": task if isinstance(task, str) and task else None,
        },
        assignment,
        tuple(warnings),
    )


def _usage_root(value: Mapping[str, Any]) -> Mapping[str, Any]:
    workers = value.get("workers", value)
    if not isinstance(workers, Mapping):
        raise LiveObservationError("usage workers must be an object")
    return workers


def _usage_state(percent: float, policy: ProposedObservationPolicy) -> str:
    if percent >= policy.stop_percent:
        return "STOP"
    if percent >= policy.slowdown_percent:
        return "SLOW"
    return "GREEN"


def _normalized_usage(
    root: Mapping[str, Any],
    binding: WorkerObservationBinding,
    policy: ProposedObservationPolicy,
) -> tuple[tuple[Mapping[str, Any], ...], tuple[str, ...]]:
    worker_records = root.get(binding.runner_worker_id, {})
    if not isinstance(worker_records, Mapping):
        worker_records = {}
    mapped_accounts = {account for _scope, account in binding.usage_account_by_scope}
    unmapped_count = sum(
        1 for value in worker_records if str(value) not in mapped_accounts
    )
    warnings = (
        [f"UNMAPPED_USAGE_SOURCES:{binding.runner_worker_id}:count={unmapped_count}"]
        if unmapped_count
        else []
    )
    observations = []
    for scope, account in binding.usage_account_by_scope:
        record = worker_records.get(account)
        if not isinstance(record, Mapping):
            warnings.append(
                f"USAGE_SOURCE_MISSING:{binding.runner_worker_id}:scope={scope}"
            )
            continue
        percent = record.get("used_percent")
        if (
            isinstance(percent, bool)
            or not isinstance(percent, (int, float))
            or not math.isfinite(float(percent))
            or not 0 <= float(percent) <= 100
        ):
            warnings.append(
                f"USAGE_SOURCE_INVALID:{binding.runner_worker_id}:scope={scope}"
            )
            continue
        try:
            observed_at = _canonical_time(record.get("observed_at"), field="usage observed_at")
        except LiveObservationError:
            warnings.append(
                f"USAGE_SOURCE_INVALID:{binding.runner_worker_id}:scope={scope}"
            )
            continue
        normalized = {
            "id": "live-usage:"
            + hashlib.sha256(
                f"{binding.registry_worker_id}\0{scope}\0{observed_at}".encode()
            ).hexdigest()[:24],
            "worker_id": binding.registry_worker_id,
            "capacity_scope": scope,
            "state": _usage_state(float(percent), policy),
            "consumed_percent": float(percent),
            "observed_at": observed_at,
        }
        reset_at = record.get("reset_at")
        if reset_at is not None:
            try:
                normalized["reset_at"] = _canonical_time(reset_at, field="usage reset_at")
            except LiveObservationError:
                warnings.append(
                    f"USAGE_RESET_INVALID:{binding.runner_worker_id}:scope={scope}"
                )
        observations.append(normalized)
    return tuple(observations), tuple(warnings)


def capture_live_observation(
    config_path: Path,
    preservation_path: Path,
    plan: ObservationPlan,
    *,
    observed_at: str | None = None,
    clock: Callable[[], datetime] | None = None,
) -> LiveObservation:
    """Capture whitelisted local state without retaining commands, env, or credentials."""
    if observed_at is not None and clock is not None:
        raise LiveObservationError("use either an explicit observed_at or a clock, not both")
    config_raw, config_source = _capture_source(config_path, "runner_config", volatile=False)
    config = _json_object(config_raw, label="runner config")
    state_value = config.get("state")
    if not isinstance(state_value, str) or not Path(state_value).is_absolute():
        raise LiveObservationError("runner config state must be an absolute path")
    state = Path(state_value)
    agents = config.get("agents")
    if not isinstance(agents, Mapping):
        raise LiveObservationError("runner config agents must be an object")
    configured_workers = set(str(value) for value in agents)
    requested_workers = {value.runner_worker_id for value in plan.workers}
    if not requested_workers <= configured_workers:
        raise LiveObservationError("observation plan references an unconfigured runner worker")
    usage_value = config.get("usage_file", str(state / "usage.json"))
    if not isinstance(usage_value, str):
        raise LiveObservationError("usage_file must be a path")
    usage_path = Path(usage_value)
    if not usage_path.is_absolute():
        repo_value = config.get("repo")
        if not isinstance(repo_value, str) or not Path(repo_value).is_absolute():
            raise LiveObservationError("relative usage_file requires an absolute repo path")
        usage_path = Path(repo_value) / usage_path

    queue_raw, queue_source = _capture_source(state / "queue.json", "queue", volatile=False)
    try:
        usage_raw, usage_source = _capture_source(usage_path, "usage", volatile=False)
    except LiveObservationError:
        usage_raw = b"{}"
        usage_source = CapturedSource(
            "usage", usage_path, "MISSING", "MISSING", False
        )
        usage = {}
        usage_warning = "USAGE_SOURCE_MISSING_OR_INVALID"
    else:
        try:
            usage = _usage_root(_json_object(usage_raw, label="usage"))
            usage_warning = None
        except LiveObservationError:
            usage = {}
            usage_warning = "USAGE_SOURCE_MISSING_OR_INVALID"
    preservation_raw, preservation_source = _capture_source(
        preservation_path, "preservation", volatile=False, retain_raw=True
    )
    queue = _json_object(queue_raw, label="queue")
    entries = queue.get("entries")
    if not isinstance(entries, list):
        raise LiveObservationError("queue entries must be a list")
    queue_status_counts: dict[str, int] = {}
    ready_entries = 0
    for entry in entries:
        if not isinstance(entry, Mapping) or not isinstance(entry.get("status"), str):
            raise LiveObservationError("queue contains a malformed entry")
        status = str(entry["status"])
        queue_status_counts[status] = queue_status_counts.get(status, 0) + 1
        if status == "ready" and entry.get("readiness") is True:
            ready_entries += 1

    sources = [config_source, queue_source, usage_source, preservation_source]
    updates = []
    assignments = []
    usage_observations = []
    warnings = [usage_warning] if usage_warning else []
    for binding in plan.workers:
        heartbeat_path = state / f"heartbeat-{binding.runner_worker_id}.json"
        heartbeat_label = f"heartbeat:{binding.runner_worker_id}"
        try:
            heartbeat_raw, heartbeat_source = _capture_source(
                heartbeat_path, heartbeat_label, volatile=True
            )
        except LiveObservationError:
            heartbeat_raw = b"{}"
            heartbeat_source = CapturedSource(
                heartbeat_label,
                heartbeat_path,
                "MISSING",
                "MISSING",
                True,
            )
            update = _missing_heartbeat_update(binding)
            assignment = None
            heartbeat_warnings = (
                f"HEARTBEAT_SOURCE_MISSING_OR_INVALID:{binding.runner_worker_id}",
            )
        else:
            try:
                update, assignment, heartbeat_warnings = _heartbeat_update(
                    heartbeat_raw, binding
                )
            except LiveObservationError:
                update = _missing_heartbeat_update(binding)
                assignment = None
                heartbeat_warnings = (
                    f"HEARTBEAT_SOURCE_MISSING_OR_INVALID:{binding.runner_worker_id}",
                )
        sources.append(heartbeat_source)
        updates.append(update)
        if assignment is not None:
            assignments.append(assignment)
        warnings.extend(heartbeat_warnings)
        normalized, usage_warnings = _normalized_usage(usage, binding, plan.policy)
        usage_observations.extend(normalized)
        warnings.extend(usage_warnings)
    # A live decision timestamp is sampled only after every source has been
    # captured. Heartbeats continue updating while slower preservation inputs
    # are read; sampling before capture can therefore make a healthy heartbeat
    # look as if it came from the future. An explicit timestamp exists only for
    # deterministic replay/tests and is never supplied by the live CLI.
    if observed_at is None:
        now = (clock or (lambda: datetime.now(timezone.utc)))()
        if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
            raise LiveObservationError("clock must return a timezone-aware datetime")
        observed_at = now.astimezone(timezone.utc).isoformat(
            timespec="microseconds"
        ).replace("+00:00", "Z")
    else:
        observed_at = _canonical_time(observed_at, field="observed_at")
    complete = not any(value.startswith("ACTIVE_HEARTBEAT_WITHOUT_TASK:") for value in warnings)
    if ready_entries:
        # queue.json deliberately excludes issue bodies and therefore task IDs.
        # Do not invent which package the legacy runner would claim next.
        warnings.append(f"LEGACY_READY_QUEUE_UNRESOLVED:count={ready_entries}")
        complete = False
    # Parse now so a malformed preservation file cannot be hidden in evidence.
    _json_object(preservation_raw, label="preservation")
    return LiveObservation(
        observed_at,
        tuple(sorted(updates, key=lambda value: str(value["registry_worker_id"]))),
        tuple(sorted(usage_observations, key=lambda value: str(value["id"]))),
        LegacyObservation(
            "installed-runner-files",
            observed_at,
            tuple(sorted(assignments)),
            complete=complete,
        ),
        dict(sorted(queue_status_counts.items())),
        tuple(sorted(set(warnings))),
        tuple(sources),
    )


def project_live_observation(
    snapshot: DispatchSnapshot,
    observation: LiveObservation,
    plan: ObservationPlan,
) -> DispatchSnapshot:
    """Project live observations onto a copied backend-neutral snapshot."""
    update_by_id = {str(value["registry_worker_id"]): value for value in observation.worker_updates}
    binding_by_id = {value.registry_worker_id: value for value in plan.workers}
    snapshot_worker_ids = [str(value.get("id")) for value in snapshot.workers]
    missing = sorted(set(binding_by_id) - set(snapshot_worker_ids))
    if missing:
        raise LiveObservationError(f"registry workers missing from snapshot: {','.join(missing)}")
    workers = []
    for original in snapshot.workers:
        value = copy.deepcopy(dict(original))
        worker_id = str(value.get("id"))
        if worker_id in update_by_id:
            update = update_by_id[worker_id]
            binding = binding_by_id[worker_id]
            value["availability"] = update["availability"]
            value["last_heartbeat_at"] = update["last_heartbeat_at"]
            value["capacity_scopes"] = list(binding.capacity_scopes)
        workers.append(value)
    replaced = {
        (binding.registry_worker_id, scope)
        for binding in plan.workers
        for scope in binding.capacity_scopes
    }
    usages = [
        copy.deepcopy(dict(value))
        for value in snapshot.usage_observations
        if (str(value.get("worker_id")), str(value.get("capacity_scope") or "default"))
        not in replaced
    ]
    usages.extend(copy.deepcopy(dict(value)) for value in observation.usage_observations)
    return DispatchSnapshot(
        revision=snapshot.revision,
        observed_at=observation.observed_at,
        active_parent_limit=snapshot.active_parent_limit,
        orchestra_reserve_percent=snapshot.orchestra_reserve_percent,
        features=tuple(copy.deepcopy(value) for value in snapshot.features),
        work_packages=tuple(copy.deepcopy(value) for value in snapshot.work_packages),
        dependencies=tuple(copy.deepcopy(value) for value in snapshot.dependencies),
        workers=tuple(workers),
        active_leases=tuple(copy.deepcopy(value) for value in snapshot.active_leases),
        usage_observations=tuple(sorted(usages, key=lambda value: str(value.get("id")))),
    )


def reconcile_preservation(
    raw: bytes,
    snapshot: DispatchSnapshot,
    expectation: PreservationExpectation,
) -> PreservationReconciliation:
    value = _json_object(raw, label="preservation")
    worktrees = value.get("worktrees")
    branches = value.get("unmerged_local_branches")
    tasks = value.get("open_task_mapping")
    services = value.get("services")
    if not isinstance(worktrees, list) or not isinstance(branches, list) or not isinstance(tasks, list):
        raise LiveObservationError("preservation lists are missing")
    if not isinstance(services, Mapping) or not isinstance(services.get("heartbeats"), Mapping):
        raise LiveObservationError("preservation heartbeat inventory is missing")
    source_task_ids = []
    malformed_source_tasks = 0
    for item in tasks:
        task_id = item.get("task") if isinstance(item, Mapping) else None
        if not isinstance(task_id, str) or not task_id.strip():
            malformed_source_tasks += 1
            continue
        source_task_ids.append(task_id)
    source_task_counts = {
        task_id: source_task_ids.count(task_id) for task_id in set(source_task_ids)
    }
    duplicate_source_tasks = tuple(
        sorted(task_id for task_id, count in source_task_counts.items() if count > 1)
    )
    expected_import_id = f"preservation:{expectation.sha256[:20]}"
    imported_registry_task_ids = []
    for item in snapshot.work_packages:
        diagnostics = item.get("provider_diagnostics")
        if (
            isinstance(diagnostics, Mapping)
            and diagnostics.get("preservation_import_id") == expected_import_id
        ):
            imported_registry_task_ids.append(str(item.get("id")))
    registry_task_counts = {
        task_id: imported_registry_task_ids.count(task_id)
        for task_id in set(imported_registry_task_ids)
    }
    duplicate_registry_tasks = tuple(
        sorted(task_id for task_id, count in registry_task_counts.items() if count > 1)
    )
    source_tasks = set(source_task_ids)
    registry_tasks = set(imported_registry_task_ids)
    source_workers = {str(value) for value in services["heartbeats"]}
    registry_workers = {
        str(item.get("provider_diagnostics", {}).get("legacy_worker"))
        for item in snapshot.workers
        if isinstance(item.get("provider_diagnostics"), Mapping)
        and item.get("provider_diagnostics", {}).get("legacy_worker")
    }
    unexplained = (
        len(source_tasks ^ registry_tasks)
        + len(source_workers ^ registry_workers)
        + sum(count - 1 for count in source_task_counts.values() if count > 1)
        + sum(count - 1 for count in registry_task_counts.values() if count > 1)
        + malformed_source_tasks
    )
    digest = _sha256(raw)
    worktree_count = len(worktrees)
    dirty_count = int(value.get("dirty_worktree_count", -1))
    dirty_entry_count = sum(
        1 for item in worktrees if isinstance(item, Mapping) and item.get("dirty") is True
    )
    branch_count = len(branches)
    active_records = sum(
        1
        for item in value.get("issue_state_records", {}).values()
        if isinstance(item, Mapping)
        and str(item.get("status", "")).lower() in {"starting", "agent", "validation", "running"}
    )
    active_lease_count = len(snapshot.active_leases)
    checks = (
        (digest == expectation.sha256, "preservation SHA-256 mismatch"),
        (worktree_count == expectation.worktree_count, "worktree count mismatch"),
        (dirty_count == expectation.dirty_worktree_count, "dirty worktree count mismatch"),
        (dirty_entry_count == dirty_count, "dirty worktree inventory is internally inconsistent"),
        (branch_count == expectation.unmerged_branch_count, "unmerged branch count mismatch"),
        (
            unexplained == expectation.unexplained_record_count,
            "unexplained record count mismatch",
        ),
        (
            not duplicate_source_tasks,
            "duplicate source task IDs: " + ",".join(duplicate_source_tasks),
        ),
        (
            not duplicate_registry_tasks,
            "duplicate imported registry task IDs: " + ",".join(duplicate_registry_tasks),
        ),
        (
            malformed_source_tasks == 0,
            f"malformed source task records: count={malformed_source_tasks}",
        ),
        (active_lease_count == expectation.active_lease_count, "active ownership count mismatch"),
        (
            active_records == expectation.active_legacy_record_count,
            "active legacy record count mismatch",
        ),
    )
    failures = tuple(detail for passed, detail in checks if not passed)
    return PreservationReconciliation(
        digest,
        worktree_count,
        dirty_count,
        branch_count,
        unexplained,
        active_lease_count,
        active_records,
        not failures,
        failures,
    )


def verify_source_proofs(
    sources: Sequence[CapturedSource],
    *,
    reader: Callable[[Path], bytes] | None = None,
) -> tuple[SourceProof, ...]:
    reader = reader or (lambda path: path.read_bytes())
    proofs = []
    for source in sources:
        try:
            after = reader(source.path)
        except OSError:
            after_sha = "MISSING"
            semantic = "MISSING"
        else:
            after_sha = _sha256(after)
            semantic = _heartbeat_semantic(after) if source.volatile else after_sha
        proofs.append(
            SourceProof(
                source.label,
                source.before_sha256,
                after_sha,
                source.volatile,
                after_sha == source.before_sha256,
                semantic == source.semantic_sha256,
            )
        )
    return tuple(proofs)


def run_live_shadow_sweep(
    snapshot: DispatchSnapshot,
    config_path: Path,
    preservation_path: Path,
    plan: ObservationPlan,
    *,
    observed_at: str | None = None,
    clock: Callable[[], datetime] | None = None,
    source_reader: Callable[[Path], bytes] | None = None,
) -> LiveSweepEvidence:
    """Capture and evaluate one real-state sweep without factory mutation."""
    before = snapshot_fingerprint(snapshot)
    observation = capture_live_observation(
        config_path,
        preservation_path,
        plan,
        observed_at=observed_at,
        clock=clock,
    )
    projected = project_live_observation(snapshot, observation, plan)
    decision = decide_shadow(projected, policy=plan.policy.shadow_policy())
    comparison = compare_with_legacy(
        decision,
        observation.legacy_observation,
        observation_tolerance_seconds=plan.policy.comparison_tolerance_seconds,
    )
    preservation_source = next(
        value for value in observation.sources if value.label == "preservation"
    )
    if preservation_source.raw is None:
        raise LiveObservationError("preservation source bytes were not retained")
    preservation = reconcile_preservation(
        preservation_source.raw, snapshot, plan.preservation
    )
    proofs = verify_source_proofs(observation.sources, reader=source_reader)
    failures = []
    if snapshot_fingerprint(snapshot) != before:
        failures.append("input DispatchSnapshot mutated")
    for proof in proofs:
        if not proof.semantic_unchanged:
            failures.append(f"source changed semantically during sweep: {proof.label}")
    if not preservation.passed:
        failures.extend(f"preservation: {value}" for value in preservation.failures)
    if decision.global_rejections:
        failures.append("shadow decision has global rejections")
    if not comparison.gate_passed:
        failures.append("legacy comparison has unresolved differences")
    return LiveSweepEvidence(
        1,
        observation.observed_at,
        before,
        snapshot_fingerprint(projected),
        proofs,
        preservation,
        observation.warnings,
        observation.queue_status_counts,
        decision,
        comparison,
        not failures,
        tuple(failures),
    )


def write_live_sweep_evidence(
    evidence: LiveSweepEvidence,
    destination: Path,
    *,
    config_path: Path,
    preservation_path: Path,
    other_inputs: Sequence[Path] = (),
) -> Path:
    """Write one immutable observation artifact outside factory state."""
    validate_evidence_destination(
        destination,
        config_path,
        preservation_path,
        other_inputs=other_inputs,
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("x", encoding="utf-8") as handle:
        handle.write(evidence.to_json())
        handle.write("\n")
    return destination


def validate_evidence_destination(
    destination: Path,
    config_path: Path,
    preservation_path: Path,
    *,
    other_inputs: Sequence[Path] = (),
) -> None:
    """Reject evidence writes into Factory-controlled or preserved locations."""
    config = _json_object(config_path.read_bytes(), label="runner config")
    preservation = _json_object(preservation_path.read_bytes(), label="preservation")
    protected_roots = []
    for key in ("state", "repo", "worktrees"):
        value = config.get(key)
        if isinstance(value, str) and Path(value).is_absolute():
            protected_roots.append(Path(value).resolve(strict=False))
    canonical = preservation.get("canonical_repository")
    if isinstance(canonical, Mapping) and isinstance(canonical.get("path"), str):
        protected_roots.append(Path(str(canonical["path"])).resolve(strict=False))
    for item in preservation.get("worktrees", ()):
        if isinstance(item, Mapping) and isinstance(item.get("worktree"), str):
            protected_roots.append(Path(str(item["worktree"])).resolve(strict=False))
    target = destination.resolve(strict=False)
    protected_files = {
        config_path.resolve(strict=False),
        preservation_path.resolve(strict=False),
        *(value.resolve(strict=False) for value in other_inputs),
    }
    if target in protected_files or any(target == root or root in target.parents for root in protected_roots):
        raise LiveObservationError("evidence destination is Factory-controlled or preserved")


def dispatch_snapshot_from_mapping(value: Mapping[str, Any]) -> DispatchSnapshot:
    required = {
        "revision",
        "observed_at",
        "active_parent_limit",
        "orchestra_reserve_percent",
        "features",
        "work_packages",
        "dependencies",
        "workers",
        "active_leases",
        "usage_observations",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise LiveObservationError("snapshot JSON does not match DispatchSnapshot")
    try:
        return DispatchSnapshot(
            revision=int(value["revision"]),
            observed_at=str(value["observed_at"]),
            active_parent_limit=int(value["active_parent_limit"]),
            orchestra_reserve_percent=float(value["orchestra_reserve_percent"]),
            features=tuple(value["features"]),
            work_packages=tuple(value["work_packages"]),
            dependencies=tuple(value["dependencies"]),
            workers=tuple(value["workers"]),
            active_leases=tuple(value["active_leases"]),
            usage_observations=tuple(value["usage_observations"]),
        )
    except (TypeError, ValueError) as error:
        raise LiveObservationError("invalid DispatchSnapshot JSON") from error


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture one read-only Factory shadow sweep")
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--preservation", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    snapshot = dispatch_snapshot_from_mapping(_json_object(args.snapshot.read_bytes(), label="snapshot"))
    plan = ObservationPlan.from_mapping(_json_object(args.plan.read_bytes(), label="plan"))
    evidence = run_live_shadow_sweep(
        snapshot,
        args.config,
        args.preservation,
        plan,
    )
    write_live_sweep_evidence(
        evidence,
        args.output,
        config_path=args.config,
        preservation_path=args.preservation,
        other_inputs=(args.snapshot, args.plan),
    )
    print(json.dumps({"output": str(args.output), "passed": evidence.passed}, sort_keys=True))
    return 0 if evidence.passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
