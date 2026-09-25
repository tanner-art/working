"""Read-only Registry projection for the authenticated Factory Control Center."""

from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit

from .models import ControlCenterReadSnapshot
from .repository import Registry


SCHEMA_VERSION = 2
_STATES = {"ON_DECK", "READY", "ACTIVE", "VERIFY_REVIEW", "BLOCKED", "DONE"}
_EVENT_KINDS = {
    "READY", "CLAIMED", "LAUNCHED", "HEARTBEAT", "VALIDATION", "REVIEW",
    "FAILURE", "RETRY", "DONE", "LEASE_RELEASED", "LEASE_EXPIRED",
}
_CAPACITY_STATES = {"normal", "caution", "checkpoint", "hard_stop", "limited", "unknown"}
_EVIDENCE_KINDS = {"commit", "check", "test", "review", "artifact", "screenshot"}
_REVIEW_STATES = {"waiting", "assigned", "changes_requested", "approved"}
_HEARTBEAT_FRESH_SECONDS = 180


class ControlCenterProjectionError(RuntimeError):
    """The Registry read cannot be represented truthfully by schema version 2."""


def _iso(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _strings(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [item for item in value if isinstance(item, str)]


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(float(value)) else None


def _nonnegative(value: Any, default: float = 0) -> float:
    number = _finite_number(value)
    return number if number is not None and number >= 0 else default


def _safe_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
        return None
    return value


def _health(availability: Any) -> str:
    if availability == "OFFLINE":
        return "offline"
    if availability in {"CONSTRAINED", "PRESERVED"}:
        return "constrained"
    if availability in {"IDLE", "BUSY"}:
        return "healthy"
    raise ControlCenterProjectionError("worker availability cannot be projected truthfully")


def _effective_worker_health(
    availability: Any,
    service_state: str,
    authentication_state: str,
    heartbeat_at: str | None,
    observed_at: str,
) -> str:
    """Apply the same conservative evidence rules used by worker cards."""
    availability_health = _health(availability)
    if availability_health == "offline" or service_state == "offline":
        return "offline"
    if authentication_state == "invalid":
        return "constrained"
    if service_state != "healthy" or authentication_state != "valid":
        return "constrained"
    heartbeat = _iso(heartbeat_at)
    observed = _iso(observed_at)
    if heartbeat is None or observed is None:
        return "constrained"
    heartbeat_time = datetime.fromisoformat(heartbeat.replace("Z", "+00:00"))
    observed_time = datetime.fromisoformat(observed.replace("Z", "+00:00"))
    age_seconds = (observed_time - heartbeat_time).total_seconds()
    if age_seconds < 0 or age_seconds > _HEARTBEAT_FRESH_SECONDS:
        return "constrained"
    return "constrained" if availability_health == "constrained" else "healthy"


def _capacity_state(value: Any) -> str:
    normalized = str(value or "").strip().upper()
    if normalized in {"GREEN", "NORMAL", "ELIGIBLE"}:
        return "normal"
    if normalized in {"YELLOW", "SLOW", "CAUTION"}:
        return "caution"
    if normalized in {"FINISH_ONLY", "FINISH-ONLY", "CHECKPOINT"}:
        return "checkpoint"
    if normalized in {"RED", "STOP", "HARD_STOP"}:
        return "hard_stop"
    if normalized in {"EXHAUSTED", "LIMITED", "RATE_LIMITED"}:
        return "limited"
    return "unknown"


def _attempt_outcome(value: Any, ended_at: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"success", "succeeded", "complete", "completed", "done"}:
        return "succeeded"
    if normalized in {"failed", "failure", "error"}:
        return "failed"
    if normalized in {"blocked"}:
        return "blocked"
    if normalized in {"cancelled", "canceled"}:
        return "cancelled"
    if ended_at is None:
        return "active"
    return "unknown"


def _evidence(item: Mapping[str, Any]) -> dict[str, Any]:
    raw_kind = str(item.get("kind") or "").strip().lower().replace("_", "-")
    kind = {
        "commit": "commit",
        "check": "check", "checks": "check", "ci": "check",
        "test": "test", "tests": "test",
        "review": "review", "assurance": "review",
        "screenshot": "screenshot", "image": "screenshot",
        "artifact": "artifact", "runner-log": "artifact", "log": "artifact",
        "telemetry": "artifact", "bundle": "artifact",
    }.get(raw_kind, "artifact")
    return {
        "id": str(item.get("id", "")),
        "kind": kind,
        "label": str(item.get("summary") or item.get("id") or "Evidence"),
        "url": _safe_url(item.get("uri")),
        "recordedAt": _iso(item.get("recorded_at")),
    }


def _project_reconciliation(snapshot: ControlCenterReadSnapshot) -> dict[str, Any]:
    latest = snapshot.preservation_imports[-1] if snapshot.preservation_imports else None
    if latest is None:
        return {
            "status": "unknown", "worktreeCount": None, "dirtyWorktreeCount": None,
            "unmergedBranchCount": None, "unexplainedRecordCount": None,
            "activeStaleLeaseCount": sum(
                1 for lease in snapshot.leases
                if lease.get("released_at") is None
                and isinstance(lease.get("expires_at"), str)
                and str(lease["expires_at"]) <= snapshot.observed_at
            ),
            "observedAt": snapshot.observed_at,
        }
    reconciliation = _mapping(latest.get("reconciliation"))
    artifacts = [item for item in snapshot.preserved_artifacts if item.get("import_id") == latest.get("id")]
    worktrees = [item for item in artifacts if item.get("kind") == "WORKTREE"]
    branches = [item for item in artifacts if item.get("kind") == "BRANCH"]
    unexplained = _finite_number(reconciliation.get("unexplained_records"))
    expected_pairs = (
        ("expected_tasks", "imported_tasks"),
        ("expected_workers", "imported_workers"),
        ("expected_worktrees", "imported_worktrees"),
        ("expected_branches", "imported_branches"),
    )
    comparable = all(_finite_number(reconciliation.get(key)) is not None for pair in expected_pairs for key in pair)
    matched = comparable and all(reconciliation.get(left) == reconciliation.get(right) for left, right in expected_pairs)
    status = "clean" if matched and unexplained == 0 else "mismatch" if comparable or unexplained is not None else "unknown"
    return {
        "status": status,
        "worktreeCount": len(worktrees),
        "dirtyWorktreeCount": sum(1 for item in worktrees if bool(item.get("dirty"))),
        "unmergedBranchCount": len(branches),
        "unexplainedRecordCount": unexplained,
        "activeStaleLeaseCount": sum(
            1 for lease in snapshot.leases
            if lease.get("released_at") is None
            and isinstance(lease.get("expires_at"), str)
            and str(lease["expires_at"]) <= snapshot.observed_at
        ),
        "observedAt": _iso(latest.get("imported_at")) or snapshot.observed_at,
    }


def _project_usage_invocations(snapshot: ControlCenterReadSnapshot) -> list[dict[str, Any]]:
    sources: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for source in snapshot.usage_sources:
        sources[str(source.get("ledger_id"))].append(source)
    attempts = {str(item.get("id")): item for item in snapshot.attempts}
    projected = []
    for item in snapshot.usage_invocations:
        observation_class = str(item.get("observation_class"))
        if observation_class not in {"AUTONOMOUS", "DIAGNOSTIC", "LEGACY_UNCLASSIFIED"}:
            raise ControlCenterProjectionError("usage invocation has unsupported observation class")
        package_id = item.get("package_id") if isinstance(item.get("package_id"), str) else None
        attempt_id = item.get("attempt_id") if isinstance(item.get("attempt_id"), str) else None
        if observation_class == "AUTONOMOUS":
            attempt = attempts.get(attempt_id or "")
            if attempt is None or attempt.get("package_id") != package_id:
                raise ControlCenterProjectionError("autonomous usage references an unknown package attempt")
            if attempt.get("worker_id") is not None and attempt.get("worker_id") != item.get("worker_id"):
                raise ControlCenterProjectionError("autonomous usage worker does not own its attempt")
        if observation_class == "DIAGNOSTIC" and (package_id is not None or attempt_id is not None):
            raise ControlCenterProjectionError("diagnostic usage carries task provenance")
        source_rows = sources.get(str(item.get("id")), [])
        if not source_rows:
            primary_type = item.get("primary_source_type")
            if primary_type in {"CLI_JSON", "CLI_STREAM_JSON", "TRANSCRIPT"}:
                source_rows = [{"source_type": primary_type, "observed_at": item.get("observed_at")}]
        if not source_rows:
            raise ControlCenterProjectionError("usage invocation has no observation source")
        outcome = str(item.get("outcome"))
        if outcome not in {"SUCCEEDED", "FAILED", "LIMITED"}:
            raise ControlCenterProjectionError("usage invocation has unsupported outcome")
        provider = str(item.get("provider") or "Provider")
        projected.append({
            "id": str(item.get("id", "")),
            "workerId": str(item.get("worker_id", "")),
            "accountLabel": f"{provider.title()} account (identity withheld)",
            "sessionId": str(item.get("session_id", "")),
            "packageId": package_id,
            "attemptId": attempt_id,
            "observationClass": observation_class,
            "observedAt": _iso(item.get("observed_at")),
            "modelDiagnostic": item.get("model_diagnostic") if isinstance(item.get("model_diagnostic"), str) else None,
            "inputTokens": _finite_number(item.get("input_tokens")),
            "outputTokens": _finite_number(item.get("output_tokens")),
            "cacheReadTokens": _finite_number(item.get("cache_read_input_tokens")),
            "cacheWriteTokens": _finite_number(item.get("cache_creation_input_tokens")),
            "durationSeconds": (
                _finite_number(item.get("duration_ms")) / 1000
                if _finite_number(item.get("duration_ms")) is not None else None
            ),
            "outcome": outcome,
            "limitSignal": item.get("limit_signal") if isinstance(item.get("limit_signal"), str) else None,
            "sources": [
                {
                    "sourceType": source.get("source_type"),
                    "observedAt": _iso(source.get("observed_at")),
                }
                for source in source_rows
                if source.get("source_type") in {"CLI_JSON", "CLI_STREAM_JSON", "TRANSCRIPT"}
            ],
        })
    return projected


def _measurement(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    def token_sum(field: str) -> float | None:
        values = [_finite_number(item.get(field)) for item in rows]
        actual = [value for value in values if value is not None]
        return sum(actual) if actual else None

    return {
        "inputTokens": token_sum("input_tokens"),
        "outputTokens": token_sum("output_tokens"),
        "cacheReadTokens": token_sum("cache_read_input_tokens"),
        "cacheWriteTokens": token_sum("cache_creation_input_tokens"),
        "requestCount": len(rows),
        "durationSeconds": sum(_nonnegative(item.get("duration_ms")) for item in rows) / 1000,
        "completedTasks": sum(1 for item in rows if bool(item.get("task_completed"))),
    }


def _project_capacity(snapshot: ControlCenterReadSnapshot) -> list[dict[str, Any]]:
    capacity = []
    for item in snapshot.usage_observations:
        diagnostics = _mapping(item.get("provider_diagnostics"))
        source = diagnostics.get("source")
        source = source if source in {"provider_reported", "factory_measured", "inferred", "unknown"} else "unknown"
        scope = diagnostics.get("capacity_scope") or item.get("capacity_scope") or "Capacity observation"
        capacity.append({
            "id": str(item.get("id", "")), "workerId": str(item.get("worker_id", "")),
            "label": str(scope).replace("_", " ").title(), "source": source,
            "observedAt": _iso(item.get("observed_at")), "state": _capacity_state(item.get("state")),
            "usedPercent": _finite_number(item.get("consumed_percent")),
            "resetAt": _iso(item.get("reset_at")),
            "rolling24Hours": _measurement(()), "rolling7Days": _measurement(()),
            "averageTokensPerTask": None, "outputTokensPerHour": None,
            "productiveRuntimeSeconds": 0, "reviewThroughput": 0,
            "inferredCeilingTokens": None, "limitHitCount": 0, "lastLimitHitAt": None,
        })
    now = datetime.fromisoformat(snapshot.observed_at.replace("Z", "+00:00"))
    ledger_by_worker: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for item in snapshot.usage_invocations:
        ledger_by_worker[str(item.get("worker_id"))].append(item)
    for worker_id, rows in ledger_by_worker.items():
        def since(delta: timedelta) -> list[Mapping[str, Any]]:
            result = []
            for item in rows:
                observed = _iso(item.get("observed_at"))
                if observed and datetime.fromisoformat(observed.replace("Z", "+00:00")) >= now - delta:
                    result.append(item)
            return result
        day, week = since(timedelta(hours=24)), since(timedelta(days=7))
        week_measurement = _measurement(week)
        task_count = week_measurement["completedTasks"]
        token_total = sum(
            value or 0 for value in (
                week_measurement["inputTokens"], week_measurement["outputTokens"],
                week_measurement["cacheReadTokens"], week_measurement["cacheWriteTokens"],
            )
        )
        duration = week_measurement["durationSeconds"]
        latest = max(rows, key=lambda item: str(item.get("observed_at")))
        limited = [item for item in rows if item.get("limit_signal") or item.get("outcome") == "LIMITED"]
        capacity.append({
            "id": f"factory-measured:{worker_id}", "workerId": worker_id,
            "label": "Factory-measured consumption", "source": "factory_measured",
            "observedAt": _iso(latest.get("observed_at")),
            "state": "limited" if latest.get("limit_signal") or latest.get("outcome") == "LIMITED" else "normal",
            "usedPercent": None, "resetAt": None,
            "rolling24Hours": _measurement(day), "rolling7Days": week_measurement,
            "averageTokensPerTask": token_total / task_count if task_count else None,
            "outputTokensPerHour": (
                (week_measurement["outputTokens"] or 0) / (duration / 3600)
                if duration else None
            ),
            "productiveRuntimeSeconds": duration,
            "reviewThroughput": sum(1 for item in week if bool(item.get("review_completed"))),
            "inferredCeilingTokens": None, "limitHitCount": len(limited),
            "lastLimitHitAt": _iso(max(limited, key=lambda item: str(item.get("observed_at"))).get("observed_at")) if limited else None,
        })
    return capacity


def _project_reviews(snapshot: ControlCenterReadSnapshot) -> list[dict[str, Any]]:
    reviews = []
    dependencies: dict[str, list[str]] = defaultdict(list)
    for dependency in snapshot.dependencies:
        dependencies[str(dependency.get("package_id"))].append(str(dependency.get("dependency_id")))
    attempts: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for attempt in snapshot.attempts:
        attempts[str(attempt.get("package_id"))].append(attempt)
    active_leases = {
        str(lease.get("package_id")): lease for lease in snapshot.leases
        if lease.get("released_at") is None and str(lease.get("expires_at")) > snapshot.observed_at
    }
    reviewer_ids = [
        str(worker.get("id")) for worker in snapshot.workers
        if "review" in {capability.lower() for capability in _strings(worker.get("capabilities"))}
        or "ASSURANCE" in _strings(worker.get("approved_lanes"))
    ]
    evidence_by_id = {str(item.get("id")): item for item in snapshot.evidence}
    represented_review_packages: set[str] = set()
    for outcome in snapshot.review_outcomes:
        review_package_id = str(outcome.get("review_package_id", ""))
        target_id = str(outcome.get("target_package_id", ""))
        implementer = str(outcome.get("implementer_worker_id", ""))
        reviewer = str(outcome.get("reviewer_worker_id", ""))
        state = {
            "APPROVED": "approved",
            "CHANGES_REQUESTED": "changes_requested",
        }.get(outcome.get("state"))
        requested_at = _iso(outcome.get("requested_at"))
        decided_at = _iso(outcome.get("decided_at"))
        if not state or requested_at is None or decided_at is None:
            raise ControlCenterProjectionError("structured review outcome is invalid")
        target_attempts = attempts.get(target_id, [])
        completed_implementations = [
            attempt for attempt in target_attempts
            if attempt.get("worker_id") is not None
            and attempt.get("outcome") == "SUCCEEDED"
            and _iso(attempt.get("ended_at")) is not None
            and _iso(attempt.get("ended_at")) <= requested_at
        ]
        if not completed_implementations:
            raise ControlCenterProjectionError("structured review implementer provenance is missing")
        actual_implementation = max(
            completed_implementations,
            key=lambda attempt: (
                str(_iso(attempt.get("ended_at"))), str(_iso(attempt.get("started_at"))),
                str(attempt.get("id")),
            ),
        )
        if actual_implementation.get("worker_id") != implementer:
            raise ControlCenterProjectionError("structured review implementer is invalid")
        if any(attempt.get("worker_id") == reviewer for attempt in target_attempts):
            raise ControlCenterProjectionError("structured review independence is invalid")
        if any(
            _iso(attempt.get("started_at")) is not None
            and str(_iso(attempt.get("started_at"))) <= decided_at
            and (
                _iso(attempt.get("ended_at")) is None
                or str(_iso(attempt.get("ended_at"))) > requested_at
            )
            for attempt in target_attempts
        ):
            raise ControlCenterProjectionError("structured review target changed during review")
        reviewer_attempts = [
            attempt for attempt in attempts.get(review_package_id, [])
            if attempt.get("worker_id") == reviewer
            and attempt.get("outcome") == "SUCCEEDED"
            and _iso(attempt.get("ended_at")) is not None
            and _iso(attempt.get("started_at")) is not None
            and str(_iso(attempt.get("started_at"))) >= requested_at
            and str(_iso(attempt.get("ended_at"))) <= decided_at
        ]
        if not reviewer_attempts:
            raise ControlCenterProjectionError("structured review attempt is missing")
        reviewer_attempt = max(
            reviewer_attempts,
            key=lambda attempt: (
                str(_iso(attempt.get("ended_at"))), str(_iso(attempt.get("started_at"))),
                str(attempt.get("id")),
            ),
        )
        evidence_ids = _strings(outcome.get("approval_evidence_ids"))
        approval_evidence = []
        for evidence_id in evidence_ids:
            item = evidence_by_id.get(evidence_id)
            metadata = _mapping(item.get("metadata")) if item is not None else {}
            if (
                item is None
                or str(item.get("kind", "")).lower() != "review"
                or item.get("package_id") != review_package_id
                or metadata.get("attempt_id") != reviewer_attempt.get("id")
                or _iso(item.get("recorded_at")) is None
                or str(_iso(item.get("recorded_at"))) < str(_iso(reviewer_attempt.get("started_at")))
                or str(_iso(item.get("recorded_at"))) > decided_at
            ):
                raise ControlCenterProjectionError("structured review evidence is missing")
            approval_evidence.append(_evidence(item))
        reviews.append({
            "id": str(outcome.get("id", "")),
            "packageId": target_id,
            "implementerWorkerId": implementer,
            "eligibleReviewerIds": [worker_id for worker_id in reviewer_ids if worker_id != implementer],
            "assignedReviewerId": reviewer,
            "requestedAt": requested_at,
            "state": state,
            "findings": _strings(outcome.get("findings")),
            "changesRequested": _strings(outcome.get("changes_requested")),
            "approvalEvidence": approval_evidence,
        })
        represented_review_packages.add(review_package_id)
    for package in snapshot.work_packages:
        review_package_id = str(package.get("id", ""))
        if (
            package.get("kind") != "REVIEW"
            or package.get("status") not in {"READY", "ACTIVE"}
            or review_package_id in represented_review_packages
        ):
            continue
        target_id = next(iter(dependencies.get(review_package_id, [])), None)
        target_attempts = attempts.get(target_id or "", [])
        implementer = target_attempts[-1].get("worker_id") if target_attempts else None
        state = "assigned" if package.get("status") == "ACTIVE" else "waiting"
        requested_at = _iso(package.get("ready_at")) or _iso(package.get("created_at"))
        eligible = [worker_id for worker_id in reviewer_ids if worker_id != implementer]
        lease = active_leases.get(review_package_id)
        assigned = str(lease.get("worker_id")) if lease else None
        if requested_at is None or not isinstance(implementer, str):
            continue
        reviews.append({
            "id": f"review:{review_package_id}",
            "packageId": target_id,
            "implementerWorkerId": implementer,
            "eligibleReviewerIds": eligible,
            "assignedReviewerId": assigned,
            "requestedAt": requested_at, "state": state,
            "findings": [],
            "changesRequested": [],
            "approvalEvidence": [],
        })
    return reviews


def _event_kind(item: Mapping[str, Any]) -> str | None:
    value = str(item.get("event_type") or "")
    if value in _EVENT_KINDS:
        return value
    if value == "LEASE_ACQUIRED":
        return "CLAIMED"
    if value == "LEASE_RENEWED":
        return "HEARTBEAT"
    if value == "REVIEW_OUTCOME_RECORDED":
        return "REVIEW"
    if value == "PACKAGE_STATUS_CHANGED":
        target = _mapping(item.get("detail")).get("to")
        return {"READY": "READY", "VERIFY_REVIEW": "VALIDATION", "BLOCKED": "FAILURE", "DONE": "DONE"}.get(target)
    return None


def project_control_center(snapshot: ControlCenterReadSnapshot) -> dict[str, Any]:
    """Translate an immutable Registry read into schema-v2 dashboard JSON."""
    feature_ids = {str(feature.get("id", "")) for feature in snapshot.features}
    package_ids = [str(package.get("id", "")) for package in snapshot.work_packages]
    if len(feature_ids) != len(snapshot.features):
        raise ControlCenterProjectionError("Registry read contains duplicate Feature IDs")
    if len(set(package_ids)) != len(package_ids):
        raise ControlCenterProjectionError("Registry read contains duplicate package IDs")
    orphaned = [
        package_id for package_id, package in zip(package_ids, snapshot.work_packages)
        if str(package.get("feature_id", "")) not in feature_ids
    ]
    if orphaned:
        raise ControlCenterProjectionError(
            f"Registry packages are absent from the queue projection: {', '.join(orphaned)}"
        )
    packages_by_feature: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for package in snapshot.work_packages:
        packages_by_feature[str(package.get("feature_id"))].append(package)
    dependencies: dict[str, list[str]] = defaultdict(list)
    for item in snapshot.dependencies:
        dependencies[str(item.get("package_id"))].append(str(item.get("dependency_id")))
    active_leases = {
        str(item.get("package_id")): item
        for item in snapshot.leases
        if item.get("released_at") is None and str(item.get("expires_at")) > snapshot.observed_at
    }
    attempts: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for item in snapshot.attempts:
        attempts[str(item.get("package_id"))].append(item)
    evidence: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    evidence_by_attempt: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for item in snapshot.evidence:
        evidence[str(item.get("package_id"))].append(item)
        attempt_id = _mapping(item.get("metadata")).get("attempt_id")
        if isinstance(attempt_id, str):
            evidence_by_attempt[attempt_id].append(item)
    failures_by_worker: dict[str, list[str]] = defaultdict(list)
    packages_by_worker: dict[str, list[str]] = defaultdict(list)
    for item in snapshot.failures:
        if isinstance(item.get("worker_id"), str):
            failures_by_worker[str(item["worker_id"])].append(str(item.get("id")))
    for item in snapshot.attempts:
        if isinstance(item.get("worker_id"), str):
            packages_by_worker[str(item["worker_id"])].append(str(item.get("package_id")))

    projected_features = []
    projected_packages: dict[str, dict[str, Any]] = {}
    for feature in snapshot.features:
        feature_id = str(feature.get("id", ""))
        feature_packages = []
        for package in packages_by_feature.get(feature_id, []):
            package_id = str(package.get("id", ""))
            lease = active_leases.get(package_id)
            package_attempts = attempts.get(package_id, [])
            review_state = (
                "waiting" if package.get("kind") == "REVIEW" and package.get("status") == "READY"
                else "assigned" if package.get("kind") == "REVIEW" and package.get("status") == "ACTIVE"
                else None
            )
            projected_attempts = []
            for index, attempt in enumerate(package_attempts, start=1):
                attempt_diagnostics = _mapping(attempt.get("provider_diagnostics"))
                projected_attempts.append({
                    "id": str(attempt.get("id", "")), "number": index,
                    "workerId": attempt.get("worker_id") if isinstance(attempt.get("worker_id"), str) else None,
                    "startedAt": _iso(attempt.get("started_at")), "endedAt": _iso(attempt.get("ended_at")),
                    "outcome": _attempt_outcome(attempt.get("outcome"), attempt.get("ended_at")),
                    "branch": attempt_diagnostics.get("branch") if isinstance(attempt_diagnostics.get("branch"), str) else None,
                    "commitSha": attempt_diagnostics.get("commit_sha") if isinstance(attempt_diagnostics.get("commit_sha"), str) else None,
                    "pullRequestUrl": _safe_url(attempt_diagnostics.get("pr_url")),
                    "evidence": [_evidence(item) for item in evidence_by_attempt.get(str(attempt.get("id")), [])],
                })
            projected = {
                "id": package_id, "featureId": feature_id,
                "title": str(package.get("title", "")),
                "kind": str(package.get("kind", "")),
                "priority": int(_nonnegative(package.get("priority"))),
                "lane": package.get("lane") if isinstance(package.get("lane"), str) else None,
                "state": package.get("status"), "dependencies": dependencies.get(package_id, []),
                "requiredCapabilities": _strings(package.get("required_capabilities")),
                "ownerWorkerId": lease.get("worker_id") if lease else None,
                "currentLease": ({
                    "id": str(lease.get("id", "")), "workerId": str(lease.get("worker_id", "")),
                    "acquiredAt": _iso(lease.get("acquired_at")), "expiresAt": _iso(lease.get("expires_at")),
                } if lease else None),
                "attemptNumber": len(package_attempts),
                "elapsedRuntimeSeconds": _nonnegative(package.get("runtime_seconds")),
                "branch": package.get("branch") if isinstance(package.get("branch"), str) else None,
                "pullRequestUrl": _safe_url(package.get("pr_url")),
                "reviewState": review_state,
                "failureCode": package.get("failure_code") if isinstance(package.get("failure_code"), str) else None,
                "blockReason": package.get("failure_detail") if isinstance(package.get("failure_detail"), str) else None,
                "acceptanceCriteria": _strings(package.get("acceptance_criteria")),
                "evidence": [_evidence(item) for item in evidence.get(package_id, [])],
                "attempts": projected_attempts,
            }
            projected_packages[package_id] = projected
            feature_packages.append(projected)
        projected_features.append({
            "id": feature_id, "title": str(feature.get("title", "")),
            "description": str(feature.get("description", "")),
            "priority": int(_nonnegative(feature.get("priority"))),
            "state": feature.get("status"), "packages": feature_packages,
        })

    projected_workers = []
    for worker in snapshot.workers:
        worker_id = str(worker.get("id", ""))
        diagnostics = _mapping(worker.get("provider_diagnostics"))
        lease = next((item for item in active_leases.values() if item.get("worker_id") == worker_id), None)
        worker_attempts = [item for item in snapshot.attempts if item.get("worker_id") == worker_id]
        current_package_attempts = attempts.get(str(lease.get("package_id")), []) if lease else []
        current_attempt = next((index for index, item in enumerate(current_package_attempts, start=1) if item.get("lease_id") == lease.get("id") and item.get("ended_at") is None), None) if lease else None
        capabilities = _strings(worker.get("capabilities"))
        role = "ORCHESTRA" if worker.get("role") == "ORCHESTRA" else "REVIEWER" if "review" in {item.lower() for item in capabilities} else "IMPLEMENTER"
        service_state = diagnostics.get("service_state") if diagnostics.get("service_state") in {"healthy", "degraded", "offline", "unknown"} else "unknown"
        authentication_state = diagnostics.get("authentication_state") if diagnostics.get("authentication_state") in {"valid", "invalid", "unknown"} else "unknown"
        heartbeat_at = _iso(worker.get("last_heartbeat_at"))
        projected_workers.append({
            "id": worker_id, "displayName": str(worker.get("display_name", worker_id)), "role": role,
            "provider": diagnostics.get("provider") if isinstance(diagnostics.get("provider"), str) else None,
            "model": diagnostics.get("model") if isinstance(diagnostics.get("model"), str) else None,
            "health": _effective_worker_health(
                worker.get("availability"), service_state, authentication_state,
                heartbeat_at, snapshot.observed_at,
            ),
            "serviceState": service_state,
            "authenticationState": authentication_state,
            "heartbeatAt": heartbeat_at,
            "currentPackageId": str(lease.get("package_id")) if lease else None,
            "activeLease": ({
                "id": str(lease.get("id")), "workerId": worker_id,
                "acquiredAt": _iso(lease.get("acquired_at")), "expiresAt": _iso(lease.get("expires_at")),
            } if lease else None),
            "currentAttempt": current_attempt, "approvedCapabilities": capabilities,
            "approvedLanes": _strings(worker.get("approved_lanes")),
            "productiveRuntimeSeconds": sum(_nonnegative(item.get("runtime_seconds")) for item in worker_attempts),
            "idleSeconds": 0,
            "blockedSeconds": sum(_nonnegative(item.get("blocked_seconds")) for item in worker_attempts),
            "recentTaskIds": list(dict.fromkeys(reversed(packages_by_worker.get(worker_id, []))))[:10],
            "recentFailureIds": list(reversed(failures_by_worker.get(worker_id, [])))[:10],
            "capacityState": _capacity_state(worker.get("usage_state")),
        })

    reconciliation = _project_reconciliation(snapshot)
    projected_reviews = _project_reviews(snapshot)
    failures = []
    package_state = {str(item.get("id")): item.get("status") for item in snapshot.work_packages}
    for item in snapshot.failures:
        package_id = item.get("package_id") if isinstance(item.get("package_id"), str) else None
        code = str(item.get("code", "UNKNOWN_FAILURE"))
        failures.append({
            "id": str(item.get("id", "")), "code": code,
            "title": code.replace("_", " ").title(), "detail": str(item.get("detail", "")),
            "severity": "critical" if code in {"AUTH_FAILURE", "SCOPE_DRIFT", "ORCHESTRA_CAPACITY_RISK"} else "warning",
            "occurredAt": _iso(item.get("observed_at")),
            "workerId": item.get("worker_id") if isinstance(item.get("worker_id"), str) else None,
            "packageId": package_id, "requiresHuman": package_id is None or package_state.get(package_id) == "BLOCKED",
        })
    if reconciliation["status"] == "mismatch":
        failures.append({
            "id": f"preservation:{snapshot.revision}", "code": "PRESERVATION_MISMATCH",
            "title": "Preservation mismatch", "detail": "Registry preservation counts do not reconcile.",
            "severity": "critical", "occurredAt": reconciliation["observedAt"],
            "workerId": None, "packageId": None, "requiresHuman": True,
        })

    structured_review_packages = {
        str(item["packageId"]) for item in projected_reviews
        if item["state"] in {"approved", "changes_requested"}
    }
    current_failure_keys = {
        (item["packageId"], item["code"]) for item in failures if item["requiresHuman"]
    }
    for package_id, package in projected_packages.items():
        has_review_evidence = any(item.get("kind") == "review" for item in package["evidence"])
        review_state_unrecorded = (
            package["state"] == "VERIFY_REVIEW"
            and package["reviewState"] is None
            and package["failureCode"] is None
            and has_review_evidence
            and package_id not in structured_review_packages
            and (package_id, "REVIEW_STATE_UNRECORDED") not in current_failure_keys
        )
        if review_state_unrecorded:
            failures.append({
                "id": f"review-state-unrecorded:{package_id}:{snapshot.revision}",
                "code": "REVIEW_STATE_UNRECORDED",
                "title": "Review outcome is not recorded",
                "detail": (
                    "Review evidence exists for this VERIFY / REVIEW package, but this "
                    "Registry revision has no structured review outcome or current failure."
                ),
                "severity": "warning", "occurredAt": snapshot.observed_at,
                "workerId": package["ownerWorkerId"], "packageId": package_id,
                "requiresHuman": True,
            })

    events = []
    for item in snapshot.events:
        kind = _event_kind(item)
        if kind is None:
            continue
        detail = _mapping(item.get("detail"))
        package_id = item.get("package_id") if isinstance(item.get("package_id"), str) else None
        feature_id = projected_packages.get(package_id or "", {}).get("featureId")
        attempt_id = item.get("attempt_id") if isinstance(item.get("attempt_id"), str) else None
        package_attempts = attempts.get(package_id or "", [])
        attempt_number = next((index for index, attempt in enumerate(package_attempts, 1) if attempt.get("id") == attempt_id), None)
        events.append({
            "id": str(item.get("id", "")), "kind": kind,
            "occurredAt": _iso(item.get("recorded_at")), "featureId": feature_id,
            "packageId": package_id, "attemptNumber": attempt_number,
            "workerId": item.get("worker_id") if isinstance(item.get("worker_id"), str) else None,
            "branch": detail.get("branch") if isinstance(detail.get("branch"), str) else None,
            "commitSha": detail.get("commit_sha") if isinstance(detail.get("commit_sha"), str) else None,
            "pullRequestUrl": _safe_url(detail.get("pr_url")),
            "evidenceIds": _strings(detail.get("evidence_ids")),
            "summary": str(detail.get("summary") or str(item.get("event_type", kind)).replace("_", " ").title()),
        })

    active_parent_count = sum(1 for item in snapshot.work_packages if item.get("kind") == "PARENT" and item.get("status") == "ACTIVE")
    orchestra = [item for item in projected_workers if item["role"] == "ORCHESTRA"]
    constrained = (
        reconciliation["status"] == "mismatch"
        or bool(reconciliation["activeStaleLeaseCount"])
        or any(item["severity"] == "critical" and item["requiresHuman"] for item in failures)
        or any(item["code"] == "REVIEW_STATE_UNRECORDED" and item["requiresHuman"] for item in failures)
        or not orchestra
        or any(item["health"] != "healthy" for item in orchestra)
    )
    factory_health = "constrained" if constrained else "healthy"
    projection = {
        "schemaVersion": SCHEMA_VERSION, "registryRevision": str(snapshot.revision),
        "generatedAt": snapshot.observed_at,
        "source": {"kind": "registry-projection", "projectionId": f"registry:{snapshot.revision}"},
        "factory": {
            "health": factory_health, "activeParentCount": active_parent_count,
            "activeParentLimit": snapshot.active_parent_limit,
            "orchestraReservePercent": snapshot.orchestra_reserve_percent,
            "readyCount": sum(1 for item in snapshot.work_packages if item.get("status") == "READY"),
            "verifyReviewCount": sum(1 for item in snapshot.work_packages if item.get("status") == "VERIFY_REVIEW"),
            "blockedCount": sum(1 for item in snapshot.work_packages if item.get("status") == "BLOCKED"),
            "attentionCount": sum(1 for item in failures if item["requiresHuman"]),
        },
        "reconciliation": reconciliation, "features": projected_features,
        "workers": projected_workers, "reviews": projected_reviews,
        "capacity": _project_capacity(snapshot),
        "usageInvocations": _project_usage_invocations(snapshot),
        "events": events, "failures": failures,
    }
    validate_control_center_projection(projection)
    return projection


def build_control_center_projection(registry: Registry, *, observed_at: str) -> dict[str, Any]:
    """Use only the backend-neutral Registry API to create a dashboard projection."""
    return project_control_center(registry.control_center_snapshot(observed_at=observed_at))


def serialize_control_center_projection(projection: Mapping[str, Any]) -> bytes:
    validate_control_center_projection(projection)
    return json.dumps(projection, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def validate_control_center_projection(value: Mapping[str, Any]) -> None:
    """Fail closed on the cross-language schema-v2 fields consumed by the UI."""
    required = {
        "schemaVersion", "registryRevision", "generatedAt", "source", "factory",
        "reconciliation", "features", "workers", "reviews", "capacity",
        "usageInvocations", "events", "failures",
    }
    if set(value) != required or value.get("schemaVersion") != SCHEMA_VERSION:
        raise ControlCenterProjectionError("projection does not match schema version 2")
    if _iso(value.get("generatedAt")) is None or not isinstance(value.get("registryRevision"), str):
        raise ControlCenterProjectionError("projection identity is invalid")
    if _mapping(value.get("source")).get("kind") != "registry-projection":
        raise ControlCenterProjectionError("projection source is invalid")
    if not isinstance(_mapping(value.get("source")).get("projectionId"), str):
        raise ControlCenterProjectionError("projection source identity is invalid")
    factory = _mapping(value.get("factory"))
    if factory.get("health") not in {"healthy", "constrained", "offline"}:
        raise ControlCenterProjectionError("factory health is invalid")
    for field in ("activeParentCount", "activeParentLimit", "readyCount", "verifyReviewCount", "blockedCount", "attentionCount"):
        if _finite_number(factory.get(field)) is None:
            raise ControlCenterProjectionError("factory metrics are invalid")
    if factory.get("orchestraReservePercent") is not None and _finite_number(factory.get("orchestraReservePercent")) is None:
        raise ControlCenterProjectionError("Factory reserve is invalid")
    reconciliation = _mapping(value.get("reconciliation"))
    if reconciliation.get("status") not in {"clean", "mismatch", "unknown"}:
        raise ControlCenterProjectionError("reconciliation is invalid")
    for field in ("worktreeCount", "dirtyWorktreeCount", "unmergedBranchCount", "unexplainedRecordCount", "activeStaleLeaseCount"):
        if reconciliation.get(field) is not None and _finite_number(reconciliation.get(field)) is None:
            raise ControlCenterProjectionError("reconciliation count is invalid")
    if reconciliation.get("observedAt") is not None and _iso(reconciliation.get("observedAt")) is None:
        raise ControlCenterProjectionError("reconciliation time is invalid")
    for collection in ("features", "workers", "reviews", "capacity", "usageInvocations", "events", "failures"):
        if not isinstance(value.get(collection), list):
            raise ControlCenterProjectionError(f"{collection} must be a list")
    worker_ids = {item.get("id") for item in value.get("workers", []) if isinstance(item, Mapping)}
    if len(worker_ids) != len(value.get("workers", [])):
        raise ControlCenterProjectionError("worker identity is duplicated")
    feature_ids: set[str] = set()
    package_ids: set[str] = set()
    state_counts = {state: 0 for state in _STATES}
    attempts_by_package: dict[str, dict[str, Any]] = {}
    for feature in value.get("features", []):
        if (
            not isinstance(feature, Mapping) or feature.get("state") not in _STATES
            or not all(isinstance(feature.get(field), str) for field in ("id", "title", "description"))
            or _finite_number(feature.get("priority")) is None
            or not isinstance(feature.get("packages"), list)
        ):
            raise ControlCenterProjectionError("feature is invalid")
        feature_id = str(feature.get("id"))
        if feature_id in feature_ids:
            raise ControlCenterProjectionError("feature identity is duplicated")
        feature_ids.add(feature_id)
        for package in feature.get("packages", []):
            if (
                not isinstance(package, Mapping) or package.get("state") not in _STATES
                or package.get("featureId") != feature.get("id")
                or not all(isinstance(package.get(field), str) for field in ("id", "title"))
                or package.get("kind") not in {"PARENT", "TEST", "REVIEW", "EVALUATION"}
                or _finite_number(package.get("priority")) is None
                or not all(isinstance(package.get(field), list) for field in ("dependencies", "requiredCapabilities", "acceptanceCriteria", "evidence", "attempts"))
            ):
                raise ControlCenterProjectionError("package is invalid")
            package_id = str(package.get("id"))
            if package_id in package_ids:
                raise ControlCenterProjectionError("package identity is duplicated")
            package_ids.add(package_id)
            state_counts[str(package.get("state"))] += 1
            lease = package.get("currentLease")
            if lease is not None and (
                not isinstance(lease, Mapping)
                or not all(isinstance(lease.get(field), str) for field in ("id", "workerId"))
                or _iso(lease.get("acquiredAt")) is None or _iso(lease.get("expiresAt")) is None
            ):
                raise ControlCenterProjectionError("package lease is invalid")
            if package.get("reviewState") is not None and package.get("reviewState") not in _REVIEW_STATES:
                raise ControlCenterProjectionError("package review state is invalid")
            for item in package.get("evidence", []):
                _validate_evidence(item)
            attempts_by_package[str(package.get("id"))] = {
                str(attempt.get("id")): attempt for attempt in package.get("attempts", [])
                if isinstance(attempt, Mapping)
            }
            if len(attempts_by_package[str(package.get("id"))]) != len(package.get("attempts", [])):
                raise ControlCenterProjectionError("attempt is invalid")
            for attempt in package.get("attempts", []):
                if (
                    not isinstance(attempt.get("id"), str)
                    or _finite_number(attempt.get("number")) is None
                    or attempt.get("outcome") not in {"active", "succeeded", "failed", "blocked", "cancelled", "unknown"}
                    or _iso(attempt.get("startedAt")) is None
                    or (attempt.get("endedAt") is not None and _iso(attempt.get("endedAt")) is None)
                    or not isinstance(attempt.get("evidence"), list)
                ):
                    raise ControlCenterProjectionError("attempt is invalid")
                for item in attempt.get("evidence", []):
                    _validate_evidence(item)
    for feature in value.get("features", []):
        for package in feature.get("packages", []):
            if any(dependency not in package_ids for dependency in package.get("dependencies", [])):
                raise ControlCenterProjectionError("package dependency is absent from this Registry revision")
            if package.get("ownerWorkerId") is not None and package.get("ownerWorkerId") not in worker_ids:
                raise ControlCenterProjectionError("package owner is absent from this Registry revision")
            lease = package.get("currentLease")
            if isinstance(lease, Mapping) and lease.get("workerId") not in worker_ids:
                raise ControlCenterProjectionError("package lease worker is absent from this Registry revision")
    expected_counts = {
        "activeParentCount": sum(
            1 for feature in value.get("features", [])
            for package in feature.get("packages", [])
            if package.get("kind") == "PARENT" and package.get("state") == "ACTIVE"
        ),
        "readyCount": state_counts["READY"],
        "verifyReviewCount": state_counts["VERIFY_REVIEW"],
        "blockedCount": state_counts["BLOCKED"],
        "attentionCount": sum(
            1 for failure in value.get("failures", [])
            if isinstance(failure, Mapping) and failure.get("requiresHuman") is True
        ),
    }
    if any(factory.get(field) != expected for field, expected in expected_counts.items()):
        raise ControlCenterProjectionError("factory counts do not match this Registry revision")
    for worker in value.get("workers", []):
        if (
            not isinstance(worker, Mapping)
            or not all(isinstance(worker.get(field), str) for field in ("id", "displayName"))
            or worker.get("role") not in {"ORCHESTRA", "IMPLEMENTER", "REVIEWER"}
            or worker.get("health") not in {"healthy", "constrained", "offline"}
            or worker.get("serviceState") not in {"healthy", "degraded", "offline", "unknown"}
            or worker.get("authenticationState") not in {"valid", "invalid", "unknown"}
            or worker.get("capacityState") not in _CAPACITY_STATES
            or not all(isinstance(worker.get(field), list) for field in ("approvedCapabilities", "approvedLanes", "recentTaskIds", "recentFailureIds"))
        ):
            raise ControlCenterProjectionError("worker is invalid")
        if worker.get("currentPackageId") is not None and worker.get("currentPackageId") not in package_ids:
            raise ControlCenterProjectionError("worker package is absent from this Registry revision")
    for scope in value.get("capacity", []):
        if (
            not isinstance(scope, Mapping)
            or not all(isinstance(scope.get(field), str) for field in ("id", "workerId", "label"))
            or scope.get("source") not in {"provider_reported", "factory_measured", "inferred", "unknown"}
            or scope.get("state") not in _CAPACITY_STATES
        ):
            raise ControlCenterProjectionError("capacity scope is invalid")
        if scope.get("workerId") not in worker_ids:
            raise ControlCenterProjectionError("capacity worker is absent from this Registry revision")
        _validate_measurement(scope.get("rolling24Hours"))
        _validate_measurement(scope.get("rolling7Days"))
    for invocation in value.get("usageInvocations", []):
        if not isinstance(invocation, Mapping) or invocation.get("workerId") not in worker_ids:
            raise ControlCenterProjectionError("usage worker is invalid")
        observation_class = invocation.get("observationClass")
        if observation_class not in {"AUTONOMOUS", "DIAGNOSTIC", "LEGACY_UNCLASSIFIED"}:
            raise ControlCenterProjectionError("usage class is invalid")
        if invocation.get("outcome") not in {"SUCCEEDED", "FAILED", "LIMITED"} or not invocation.get("sources"):
            raise ControlCenterProjectionError("usage result is invalid")
        if _iso(invocation.get("observedAt")) is None or not all(isinstance(invocation.get(field), str) for field in ("id", "accountLabel", "sessionId")):
            raise ControlCenterProjectionError("usage identity is invalid")
        for source in invocation.get("sources", []):
            if not isinstance(source, Mapping) or source.get("sourceType") not in {"CLI_JSON", "CLI_STREAM_JSON", "TRANSCRIPT"} or _iso(source.get("observedAt")) is None:
                raise ControlCenterProjectionError("usage source is invalid")
        if observation_class == "AUTONOMOUS":
            attempt = attempts_by_package.get(str(invocation.get("packageId")), {}).get(str(invocation.get("attemptId")))
            if attempt is None or attempt.get("workerId") not in {None, invocation.get("workerId")}:
                raise ControlCenterProjectionError("usage attempt ownership is invalid")
        if observation_class == "DIAGNOSTIC" and (invocation.get("packageId") is not None or invocation.get("attemptId") is not None):
            raise ControlCenterProjectionError("diagnostic usage provenance is invalid")
    for event in value.get("events", []):
        if (
            not isinstance(event, Mapping) or event.get("kind") not in _EVENT_KINDS
            or not isinstance(event.get("id"), str) or not isinstance(event.get("summary"), str)
            or _iso(event.get("occurredAt")) is None or not isinstance(event.get("evidenceIds"), list)
        ):
            raise ControlCenterProjectionError("event is invalid")
    for review in value.get("reviews", []):
        if (
            not isinstance(review, Mapping) or review.get("state") not in _REVIEW_STATES
            or not all(isinstance(review.get(field), str) for field in ("id", "packageId", "implementerWorkerId"))
            or _iso(review.get("requestedAt")) is None
            or not all(isinstance(review.get(field), list) for field in ("eligibleReviewerIds", "findings", "changesRequested", "approvalEvidence"))
        ):
            raise ControlCenterProjectionError("review is invalid")
        if review.get("packageId") not in package_ids:
            raise ControlCenterProjectionError("review package is absent from this Registry revision")
        review_workers = [review.get("implementerWorkerId"), review.get("assignedReviewerId")]
        review_workers.extend(review.get("eligibleReviewerIds", []))
        if any(worker_id is not None and worker_id not in worker_ids for worker_id in review_workers):
            raise ControlCenterProjectionError("review worker is absent from this Registry revision")
        if review.get("assignedReviewerId") == review.get("implementerWorkerId"):
            raise ControlCenterProjectionError("review independence is invalid")
        if review.get("state") == "approved" and (
            review.get("assignedReviewerId") is None or not review.get("approvalEvidence")
        ):
            raise ControlCenterProjectionError("review approval evidence is invalid")
        if review.get("state") == "changes_requested" and not review.get("changesRequested"):
            raise ControlCenterProjectionError("review requested changes are invalid")
        for item in review.get("approvalEvidence", []):
            _validate_evidence(item)
    for failure in value.get("failures", []):
        if (
            not isinstance(failure, Mapping)
            or not all(isinstance(failure.get(field), str) for field in ("id", "code", "title", "detail"))
            or failure.get("severity") not in {"warning", "critical"}
            or _iso(failure.get("occurredAt")) is None
            or not isinstance(failure.get("requiresHuman"), bool)
        ):
            raise ControlCenterProjectionError("failure is invalid")
        if failure.get("packageId") is not None and failure.get("packageId") not in package_ids:
            raise ControlCenterProjectionError("failure package is absent from this Registry revision")
        if failure.get("workerId") is not None and failure.get("workerId") not in worker_ids:
            raise ControlCenterProjectionError("failure worker is absent from this Registry revision")


def _validate_evidence(value: Any) -> None:
    if (
        not isinstance(value, Mapping)
        or not all(isinstance(value.get(field), str) for field in ("id", "kind", "label"))
        or value.get("kind") not in _EVIDENCE_KINDS
        or _iso(value.get("recordedAt")) is None
        or (value.get("url") is not None and _safe_url(value.get("url")) is None)
    ):
        raise ControlCenterProjectionError("evidence is invalid")


def _validate_measurement(value: Any) -> None:
    if not isinstance(value, Mapping):
        raise ControlCenterProjectionError("capacity measurement is invalid")
    for field in ("requestCount", "durationSeconds", "completedTasks"):
        if _finite_number(value.get(field)) is None:
            raise ControlCenterProjectionError("capacity measurement is invalid")
    for field in ("inputTokens", "outputTokens", "cacheReadTokens", "cacheWriteTokens"):
        if value.get(field) is not None and _finite_number(value.get(field)) is None:
            raise ControlCenterProjectionError("capacity measurement is invalid")
