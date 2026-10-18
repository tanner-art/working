"""Continuous delivery transactions in the authoritative Registry adapter.

Versioned metadata records use the Registry's existing transaction/revision and
operation journal. They are not a second database or scheduler. Historical
requests, generations and integration receipts are immutable; action state
changes have append-only events. Legacy bounded runs retain their old rules.
"""

from __future__ import annotations

from dataclasses import asdict, replace
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any, Mapping

from .delivery_plan import FeatureBrief, PlanError, validate_prepared_pair
from .models import PackageKind, TaskStatus, WorkPackage
from .repository import RegistryConflict, RegistryNotFound


PREFIX = "delivery:"
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}")


def encoded(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value: Any) -> str:
    return hashlib.sha256(encoded(value).encode()).hexdigest()


def timestamp(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("timezone required")
        return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
    except (AttributeError, TypeError, ValueError) as error:
        raise RegistryConflict("DELIVERY_TIMESTAMP_INVALID") from error


def identifier(value: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise RegistryConflict("DELIVERY_ID_INVALID")
    return value


def read_record(connection, key: str) -> dict | None:
    row = connection.execute("SELECT value FROM registry_metadata WHERE key=?", (PREFIX + key,)).fetchone()
    if row is None:
        return None
    try:
        value = json.loads(row[0])
        if not isinstance(value, dict) or value.get("schema_version") != 1:
            raise ValueError("unsupported record")
        return value
    except (ValueError, TypeError) as error:
        raise RegistryConflict("DELIVERY_METADATA_INVALID", key) from error


def write_record(connection, key: str, value: Mapping[str, Any], *, replace_existing=False) -> None:
    previous = read_record(connection, key)
    value = {**value, "schema_version": 1}
    if previous is not None and not replace_existing:
        if previous != value:
            raise RegistryConflict("DELIVERY_RECORD_IMMUTABLE", key)
        return
    connection.execute("INSERT INTO registry_metadata(key,value) VALUES (?,?) "
                       "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (PREFIX + key, encoded(value)))


class DeliveryRegistryMixin:
    """Internal SQLite adapter mixin; callers use these public Registry methods."""

    def _delivery_activation_packages(self, connection, scope, now):
        """Only registered delivery review placeholders may enter a LIVE scope."""
        if scope is None:
            return set()
        authorization = read_record(connection, "authorization:" + scope["run_id"])
        if authorization is None:
            if not scope["package_ids"]:
                raise RegistryConflict("DELIVERY_COORDINATOR_CONTINUATION_NOT_AUTHORIZED")
            return set()
        active = read_record(connection, "active-authorization")
        if (active is None or active.get("run_id") != scope["run_id"]
                or read_record(connection, "run-state:" + scope["run_id"]) is not None
                or any(scope.get(key) != authorization[key] for key in ("run_id", "deadline", "base_ref", "parent_limit"))
                or now >= authorization["deadline"]):
            raise RegistryConflict("DELIVERY_ACTIVATION_INVALID")
        for feature_id, expected_hash in authorization["request_hashes"].items():
            request = read_record(connection, "request:" + feature_id)
            if (request is None or request["request_sha256"] != expected_hash
                    or digest(request["brief"]) != expected_hash):
                raise RegistryConflict("DELIVERY_REQUEST_CHANGED")
        pairs = [json.loads(row[0]) for row in connection.execute(
            "SELECT value FROM registry_metadata WHERE key LIKE 'delivery:membership:%'")]
        pairs = [pair for pair in pairs if pair["run_id"] == scope["run_id"]]
        allowed, deferred = set(), set()
        for pair in pairs:
            implementation = connection.execute("SELECT status FROM work_packages WHERE id=?", (pair["implementation_id"],)).fetchone()
            review = connection.execute("SELECT status FROM work_packages WHERE id=?", (pair["review_id"],)).fetchone()
            if implementation is None or review is None:
                raise RegistryConflict("DELIVERY_MEMBERSHIP_INVALID")
            if implementation[0] == "READY" and review[0] == "ON_DECK":
                allowed.update((pair["implementation_id"], pair["review_id"]))
                deferred.add(pair["review_id"])
            elif implementation[0] == "VERIFY_REVIEW" and review[0] in {"ON_DECK", "READY"}:
                # The completed implementation remains context, not runnable
                # scope. Existing review-only provenance checks still apply.
                allowed.add(pair["review_id"])
                if review[0] == "ON_DECK":
                    deferred.add(pair["review_id"])
        if not allowed and not scope["package_ids"]:
            self._delivery_continuation_certificate(connection, scope, authorization)
            return set()
        if set(scope["package_ids"]) != allowed:
            raise RegistryConflict("DELIVERY_ACTIVATION_PACKAGE_MISMATCH")
        return deferred

    def _delivery_continuation_certificate(self, connection, scope, authorization):
        """Certify exact native approvals, never infer authority from an empty queue."""
        from .sqlite_registry import _review_input_from_evidence, _verify_operator_review_packet, _with_native_review_ci
        if scope["package_ids"]:
            raise RegistryConflict("DELIVERY_CONTINUATION_SCOPE_NOT_EMPTY")
        if (connection.execute("SELECT 1 FROM leases WHERE released_at IS NULL").fetchone()
                or connection.execute("SELECT 1 FROM attempts WHERE ended_at IS NULL").fetchone()
                or connection.execute("SELECT 1 FROM attempt_runtime_ownership WHERE released_at IS NULL").fetchone()):
            raise RegistryConflict("ACTIVE_OWNERSHIP_PRESENT")
        actions = [json.loads(row[0]) for row in connection.execute(
            "SELECT value FROM registry_metadata WHERE key LIKE 'delivery:action:%'")]
        if any(action["feature_id"] in authorization["feature_ids"]
               and action["state"] in {"RUNNING", "UNCERTAIN"} for action in actions):
            raise RegistryConflict("DELIVERY_ACTION_UNRESOLVED")
        bindings = []
        for feature_id in sorted(authorization["feature_ids"]):
            if read_record(connection, "integration:" + feature_id) is not None:
                continue
            pairs = [json.loads(row[0]) for row in connection.execute(
                "SELECT value FROM registry_metadata WHERE key LIKE ?", (PREFIX + "pair:" + feature_id + ":%",))]
            if not pairs:
                continue
            pair = max(pairs, key=lambda item: item["generation"])
            membership = read_record(connection, f"membership:{scope['run_id']}:{feature_id}:{pair['generation']}")
            if membership is None or any(membership.get(key) != pair.get(key)
                    for key in ("feature_id", "generation", "implementation_id", "review_id", "plan_action_id")):
                raise RegistryConflict("DELIVERY_MEMBERSHIP_INVALID")
            implementation = connection.execute("SELECT status FROM work_packages WHERE id=?", (pair["implementation_id"],)).fetchone()
            review = connection.execute("SELECT status FROM work_packages WHERE id=?", (pair["review_id"],)).fetchone()
            if implementation is None or review is None:
                raise RegistryConflict("DELIVERY_MEMBERSHIP_INVALID")
            if implementation[0] != "VERIFY_REVIEW" or review[0] != "DONE":
                continue
            outcome = connection.execute("SELECT state FROM review_outcomes WHERE review_package_id=?",
                                         (pair["review_id"],)).fetchone()
            if outcome is None or outcome[0] != "APPROVED":
                continue
            approval = self._delivery_approval(connection, feature_id)
            evidence = connection.execute("SELECT * FROM evidence WHERE id=?", (approval["review_input_evidence_id"],)).fetchone()
            source = _with_native_review_ci(connection, _review_input_from_evidence(evidence))
            _verify_operator_review_packet(source)
            for attempt_id, package_id, worker_id in (
                (source.implementation_attempt_id, pair["implementation_id"], approval["implementer_worker_id"]),
                (approval["review_attempt_id"], pair["review_id"], approval["reviewer_worker_id"]),
            ):
                attempt = connection.execute("SELECT * FROM attempts WHERE id=?", (attempt_id,)).fetchone()
                if (attempt is None or attempt["package_id"] != package_id or attempt["worker_id"] != worker_id
                        or attempt["outcome"] != "SUCCEEDED" or attempt["ended_at"] is None):
                    raise RegistryConflict("DELIVERY_CONTINUATION_NATIVE_ATTEMPT_REQUIRED")
            if approval["implementer_worker_id"] == approval["reviewer_worker_id"]:
                raise RegistryConflict("REVIEW_INDEPENDENCE_REQUIRED")
            bindings.append(approval)
        if not bindings:
            raise RegistryConflict("DELIVERY_COORDINATOR_CONTINUATION_NOT_AUTHORIZED")
        certificate = {"coordinator_only": True, "run_id": scope["run_id"],
                       "coordinator_worker_id": authorization["coordinator_worker_id"],
                       "authorization_sha256": digest(authorization), "initial_scope": dict(scope),
                       "approved_bindings": bindings}
        return {**certificate, "certificate_sha256": digest(certificate)}

    def delivery_activation_preflight(self, scope, *, observed_at):
        """Read-only gate; LIVE repeats this validation inside its CAS transaction."""
        from .sqlite_registry import _bounded_run_scope
        with self._connection() as connection:
            connection.execute("BEGIN")
            limit = int(connection.execute("SELECT value FROM registry_metadata WHERE key='active_parent_limit'").fetchone()[0])
            scope = _bounded_run_scope(scope, active_parent_limit=limit)
            self._delivery_activation_packages(connection, scope, timestamp(observed_at))
            if scope is None or scope["package_ids"]:
                return {"coordinator_only": False}
            authorization = read_record(connection, "authorization:" + scope["run_id"])
            return self._delivery_continuation_certificate(connection, scope, authorization)

    def _delivery_control_transition(self, connection, new_mode, scope, now):
        active = read_record(connection, "active-authorization")
        if active is None:
            return
        run_id = active["run_id"]
        prior = read_record(connection, "run-state:" + run_id)
        if new_mode == "LIVE" and scope and scope["run_id"] == run_id:
            state = {"state": "LIVE", "activated_at": now, "initial_scope": dict(scope)}
            if not scope["package_ids"]:
                state["continuation_certificate"] = self._delivery_continuation_certificate(
                    connection, scope, read_record(connection, "authorization:" + run_id))
            write_record(connection, "run-state:" + run_id, state)
        elif prior and new_mode in {"STOPPING", "PAUSED", "RECOVERY_REQUIRED"}:
            write_record(connection, "run-state:" + run_id,
                         {**prior, "state": "STOPPED", "stopped_at": now}, replace_existing=True)

    def _delivery_mutate(self, kind, operation_id, request, expected_revision, recorded_at, mutation):
        recorded_at = timestamp(recorded_at)
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                self._require_control_schema(connection)
                replay = self._operation_replay(connection, operation_id=operation_id,
                                               operation_kind=kind, request=request)
                if replay is not None:
                    connection.rollback()
                    return dict(replay)
                self._require_revision(connection, expected_revision)
                result = dict(mutation(connection, recorded_at) or {})
                revision = self._bump_revision(connection)
                result["revision"] = revision
                self._insert_event(connection, kind, recorded_at, result.get("package_id"),
                                   None, None, {"operation_id": operation_id,
                                                "request_sha256": digest(request), **result})
                self._record_operation(connection, operation_id=operation_id, operation_kind=kind,
                                       request=request, result=result, recorded_at=recorded_at)
                connection.commit()
                return result
            except Exception:
                connection.rollback()
                raise

    def submit_delivery_request(self, brief: Mapping[str, Any], *, expected_revision: int,
                                recorded_at: str) -> Mapping[str, Any]:
        brief = FeatureBrief.from_dict(brief).as_dict()
        feature_id = brief["id"]

        def submit(connection, now):
            existing = read_record(connection, "request:" + feature_id)
            if existing is not None:
                if existing["brief"] != brief:
                    raise RegistryConflict("DELIVERY_REQUEST_IMMUTABLE", feature_id)
                return {"feature_id": feature_id}
            if connection.execute("SELECT 1 FROM features WHERE id=?", (feature_id,)).fetchone():
                raise RegistryConflict("DELIVERY_FEATURE_ID_CONFLICT", feature_id)
            connection.execute("INSERT INTO features(id,title,description,priority,status,created_at,updated_at) "
                               "VALUES (?,?,?,50,'ON_DECK',?,?)",
                               (feature_id, brief["title"], brief["user_experience"], now, now))
            write_record(connection, "request:" + feature_id,
                         {"brief": brief, "request_sha256": digest(brief), "submitted_at": now})
            return {"feature_id": feature_id}

        return self._delivery_mutate("DELIVERY_REQUEST_SUBMITTED", "delivery-request:" + feature_id,
                                     brief, expected_revision, recorded_at, submit)

    def authorize_delivery_run(self, spec: Mapping[str, Any], *, expected_revision: int,
                               recorded_at: str) -> Mapping[str, Any]:
        required = {"run_id", "feature_ids", "deadline", "base_ref", "parent_limit",
                    "max_generations", "coordinator_worker_id"}
        if not isinstance(spec, Mapping) or set(spec) != required:
            raise RegistryConflict("DELIVERY_AUTHORIZATION_INVALID")
        spec = dict(spec)
        identifier(spec["run_id"])
        ids = spec["feature_ids"]
        if (not isinstance(ids, list) or not ids or len(ids) > 100 or len(set(ids)) != len(ids)
                or isinstance(spec["max_generations"], bool) or not isinstance(spec["max_generations"], int)
                or not 1 <= spec["max_generations"] <= 6
                or isinstance(spec["parent_limit"], bool) or not isinstance(spec["parent_limit"], int)
                or not 1 <= spec["parent_limit"] <= 3
                or not isinstance(spec["base_ref"], str)
                or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*", spec["base_ref"])
                or ".." in spec["base_ref"] or spec["base_ref"].endswith("/")):
            raise RegistryConflict("DELIVERY_AUTHORIZATION_INVALID")
        for feature_id in ids:
            identifier(feature_id)
        spec["deadline"] = timestamp(spec["deadline"])

        def authorize(connection, now):
            control = connection.execute("SELECT * FROM factory_control WHERE singleton=1").fetchone()
            if control["dispatch_mode"] != "PAUSED" or not control["kill_switch_engaged"]:
                raise RegistryConflict("DELIVERY_AUTHORIZATION_REQUIRES_PAUSED")
            if spec["deadline"] <= now:
                raise RegistryConflict("RUN_DEADLINE_REACHED")
            if (connection.execute("SELECT 1 FROM leases WHERE released_at IS NULL").fetchone()
                    or connection.execute("SELECT 1 FROM attempts WHERE ended_at IS NULL").fetchone()
                    or connection.execute("SELECT 1 FROM attempt_runtime_ownership WHERE released_at IS NULL").fetchone()):
                raise RegistryConflict("ACTIVE_OWNERSHIP_PRESENT")
            worker = connection.execute("SELECT role FROM workers WHERE id=?",
                                        (spec["coordinator_worker_id"],)).fetchone()
            if worker is None or worker["role"] != "ORCHESTRA":
                raise RegistryConflict("DELIVERY_COORDINATOR_INVALID")
            requests = {}
            for feature_id in ids:
                request = read_record(connection, "request:" + feature_id)
                if request is None:
                    raise RegistryNotFound("delivery request " + feature_id)
                requests[feature_id] = request
                unresolved = [json.loads(row[0]) for row in connection.execute(
                    "SELECT value FROM registry_metadata WHERE key LIKE 'delivery:action:%'")]
                if any(item["feature_id"] == feature_id and item["state"] in {"RUNNING", "UNCERTAIN"} for item in unresolved):
                    raise RegistryConflict("DELIVERY_ACTION_UNRESOLVED", feature_id)
            visited, visiting = set(), set()

            def visit(feature_id):
                if feature_id in visiting:
                    raise RegistryConflict("DELIVERY_DEPENDENCY_CYCLE")
                if feature_id in visited:
                    return
                visiting.add(feature_id)
                for dependency in requests[feature_id]["brief"].get("dependency_feature_ids", []):
                    if dependency in requests:
                        visit(dependency)
                    elif read_record(connection, "integration:" + dependency) is None:
                        raise RegistryConflict("DELIVERY_DEPENDENCY_NOT_AUTHORIZED", dependency)
                visiting.remove(feature_id)
                visited.add(feature_id)

            for feature_id in ids:
                visit(feature_id)
            authorization = {**spec, "request_hashes": {key: value["request_sha256"]
                                                       for key, value in requests.items()}, "authorized_at": now}
            write_record(connection, "authorization:" + spec["run_id"], authorization)
            write_record(connection, "active-authorization", {"run_id": spec["run_id"]}, replace_existing=True)
            # A new bounded run can continue immutable unfinished work from a
            # stopped run. Membership is new evidence; old provenance is not
            # rewritten and historical packages do not become dispatchable.
            for feature_id in ids:
                pairs = [json.loads(row[0]) for row in connection.execute(
                    "SELECT value FROM registry_metadata WHERE key LIKE ?", (PREFIX + "pair:" + feature_id + ":%",))]
                if pairs and read_record(connection, "integration:" + feature_id) is None:
                    pair = max(pairs, key=lambda item: item["generation"])
                    write_record(connection, f"membership:{spec['run_id']}:{feature_id}:{pair['generation']}",
                                 {**pair, "run_id": spec["run_id"], "original_run_id": pair["run_id"], "adopted_at": now})
            return {"run_id": spec["run_id"], "feature_ids": ids}

        return self._delivery_mutate("DELIVERY_RUN_AUTHORIZED", "delivery-authorize:" + spec["run_id"],
                                     spec, expected_revision, recorded_at, authorize)

    def _delivery_scope(self, connection, run_id, feature_id, now, *, allow_paused=False, reconcile=False):
        authorization = read_record(connection, "authorization:" + identifier(run_id))
        request = read_record(connection, "request:" + identifier(feature_id))
        active = read_record(connection, "active-authorization")
        if (authorization is None or request is None
                or (not reconcile and (active is None or active.get("run_id") != run_id))
                or authorization["request_hashes"].get(feature_id) != request["request_sha256"]
                or digest(request["brief"]) != request["request_sha256"]):
            raise RegistryConflict("DELIVERY_FEATURE_NOT_AUTHORIZED", feature_id)
        if reconcile:
            # Recording an already-published effect must remain possible after
            # a deadline/stop. This branch never grants new external authority.
            return authorization, request, None
        if now >= authorization["deadline"]:
            raise RegistryConflict("RUN_DEADLINE_REACHED")
        control = connection.execute("SELECT * FROM factory_control WHERE singleton=1").fetchone()
        scope_row = connection.execute("SELECT value FROM registry_metadata WHERE key='bounded_run_scope'").fetchone()
        scope = json.loads(scope_row[0]) if scope_row else None
        if control["dispatch_mode"] == "PAUSED" and control["kill_switch_engaged"] and allow_paused:
            if read_record(connection, "run-state:" + run_id) is not None or (isinstance(scope, dict) and scope.get("run_id") == run_id):
                raise RegistryConflict("DELIVERY_RUN_ALREADY_STOPPED")
            return authorization, request, None
        if control["dispatch_mode"] != "LIVE" or control["kill_switch_engaged"]:
            raise RegistryConflict("DISPATCH_PAUSED")
        if (not isinstance(scope, dict) or any(scope.get(key) != authorization[key]
                for key in ("run_id", "deadline", "base_ref", "parent_limit"))):
            raise RegistryConflict("DELIVERY_RUN_SCOPE_CHANGED")
        return authorization, request, scope

    def reserve_delivery_action(self, run_id: str, feature_id: str, action_id: str, action: str,
                                inputs: Mapping[str, Any], *, owner: str, expected_revision: int,
                                recorded_at: str) -> Mapping[str, Any]:
        if action not in {"PLAN", "PROJECT", "INTEGRATE", "PUBLISH_REVIEW"} or not owner:
            raise RegistryConflict("DELIVERY_ACTION_INVALID")
        identifier(action_id)
        request = dict(run_id=run_id, feature_id=feature_id, action_id=action_id,
                       action=action, inputs=dict(inputs), owner=owner)

        def reserve(connection, now):
            self._delivery_scope(connection, run_id, feature_id, now, allow_paused=action in {"PLAN", "PROJECT"})
            prior = read_record(connection, "action:" + action_id)
            if prior is not None:
                raise RegistryConflict("DELIVERY_ACTION_ALREADY_RESERVED", prior["state"])
            # An unfinished external action for this feature must be reconciled first.
            for row in connection.execute("SELECT value FROM registry_metadata WHERE key LIKE 'delivery:action:%'"):
                other = json.loads(row[0])
                if other["feature_id"] == feature_id and other["state"] in {"RUNNING", "UNCERTAIN"}:
                    raise RegistryConflict("DELIVERY_ACTION_UNRESOLVED", other["action_id"])
            record = {**request, "input_sha256": digest(inputs), "state": "RUNNING", "started_at": now,
                      "checkpoint": {}, "runtime_seconds": None}
            write_record(connection, "action:" + action_id, record)
            return {"action_id": action_id, "feature_id": feature_id}

        return self._delivery_mutate("DELIVERY_ACTION_RESERVED", "delivery-action-reserve:" + action_id,
                                     request, expected_revision, recorded_at, reserve)

    def update_delivery_action(self, action_id: str, *, owner: str, state: str,
                               result: Mapping[str, Any], expected_revision: int,
                               recorded_at: str) -> Mapping[str, Any]:
        if state not in {"RUNNING", "SUCCEEDED", "FAILED", "UNCERTAIN"}:
            raise RegistryConflict("DELIVERY_ACTION_INVALID")
        request = {"action_id": action_id, "owner": owner, "state": state, "result": dict(result)}

        def update(connection, now):
            current = read_record(connection, "action:" + identifier(action_id))
            if current is None or current["owner"] != owner:
                raise RegistryConflict("DELIVERY_ACTION_OWNER_MISMATCH")
            if current["state"] not in {"RUNNING", "UNCERTAIN"}:
                raise RegistryConflict("DELIVERY_ACTION_ALREADY_TERMINAL")
            duration = (datetime.fromisoformat(now.replace("Z", "+00:00")) -
                        datetime.fromisoformat(current["started_at"].replace("Z", "+00:00"))).total_seconds()
            if duration < 0:
                raise RegistryConflict("INVALID_ATTEMPT_CHRONOLOGY")
            updated = {**current, "state": state, "checkpoint": dict(result), "updated_at": now,
                       "runtime_seconds": duration if state in {"SUCCEEDED", "FAILED"} else None}
            write_record(connection, "checkpoint:" + action_id + ":" + digest(request),
                         {"action_id": action_id, "state": state, "result": dict(result), "recorded_at": now})
            write_record(connection, "action:" + action_id, updated, replace_existing=True)
            return {"action_id": action_id, "feature_id": current["feature_id"], "state": state}

        key = "delivery-action-update:" + action_id + ":" + digest(request)
        return self._delivery_mutate("DELIVERY_ACTION_UPDATED", key, request, expected_revision, recorded_at, update)

    def register_delivery_pair(self, run_id: str, feature_id: str, generation: int,
                               implementation: WorkPackage, review: WorkPackage,
                               *, plan_action_id: str, previous_review_id: str | None,
                               expected_revision: int, recorded_at: str) -> Mapping[str, Any]:
        if isinstance(generation, bool) or not isinstance(generation, int) or generation < 0:
            raise RegistryConflict("DELIVERY_GENERATION_INVALID")
        request = {"run_id": run_id, "feature_id": feature_id, "generation": generation,
                   "implementation": asdict(implementation), "review": asdict(review),
                   "plan_action_id": plan_action_id, "previous_review_id": previous_review_id}

        def register(connection, now):
            authorization, owner_request, scope = self._delivery_scope(
                connection, run_id, feature_id, now, allow_paused=True)
            if generation >= authorization["max_generations"]:
                raise RegistryConflict("DELIVERY_GENERATION_BUDGET_EXHAUSTED")
            if read_record(connection, "integration:" + feature_id):
                raise RegistryConflict("DELIVERY_ALREADY_INTEGRATED")
            action = read_record(connection, "action:" + plan_action_id)
            if (action is None or action["state"] != "SUCCEEDED" or action["action"] != "PLAN"
                    or action["feature_id"] != feature_id or action["run_id"] != run_id
                    or action["inputs"].get("generation") != generation
                    or read_record(connection, "invalid-plan:" + plan_action_id) is not None
                    or action["checkpoint"].get("plan", {}).get("state") != "PREPARED"):
                raise RegistryConflict("DELIVERY_VERIFIED_PLAN_REQUIRED")
            prior = read_record(connection, f"pair:{feature_id}:{generation - 1}") if generation else None
            if generation and prior is None:
                raise RegistryConflict("DELIVERY_GENERATION_GAP")
            if prior:
                retired = read_record(connection, f"retired-pair:{feature_id}:{generation - 1}")
                verdict = connection.execute("SELECT * FROM review_outcomes WHERE review_package_id=?",
                                             (prior["review_id"],)).fetchone()
                if retired:
                    if previous_review_id is not None:
                        raise RegistryConflict("DELIVERY_CORRECTION_LINEAGE_INVALID")
                elif (previous_review_id != prior["review_id"] or verdict is None
                      or verdict["state"] != "CHANGES_REQUESTED"):
                    raise RegistryConflict("DELIVERY_CORRECTION_REQUIRES_REJECTION")
                if previous_review_id:
                    old = connection.execute("SELECT provider_diagnostics_json FROM work_packages WHERE id=?",
                                             (prior["implementation_id"],)).fetchone()
                    if not set(json.loads(old[0])["exclusive_paths"]) <= set(implementation.provider_diagnostics.get("exclusive_paths", ())):
                        raise RegistryConflict("DELIVERY_CORRECTION_OWNERSHIP_LOST")
            elif previous_review_id is not None:
                raise RegistryConflict("DELIVERY_CORRECTION_LINEAGE_INVALID")
            dependency_packages = {}
            for dependency in owner_request["brief"].get("dependency_feature_ids", []):
                receipt = read_record(connection, "integration:" + dependency)
                if receipt is None:
                    raise RegistryConflict("DELIVERY_DEPENDENCY_NOT_INTEGRATED", dependency)
                dependency_packages[dependency] = receipt["package_id"]
            if (implementation.feature_id != feature_id or review.feature_id != feature_id
                    or implementation.id == review.id or implementation.kind != PackageKind.PARENT
                    or review.kind != PackageKind.REVIEW or review.lane is None or review.lane.value != "ASSURANCE"
                    or set(implementation.dependency_ids) != set(dependency_packages.values())
                    or tuple(review.dependency_ids) != (implementation.id,)
                    or not implementation.required_capabilities
                    or not {"review", "independent-review"}.intersection(review.required_capabilities)):
                raise RegistryConflict("DELIVERY_PAIR_INVALID")
            try:
                validate_prepared_pair(action["checkpoint"]["plan"],
                    brief=FeatureBrief.from_dict(owner_request["brief"]),
                    implementation=implementation, review=review, target_ref=authorization["base_ref"],
                    dependency_packages=dependency_packages)
            except PlanError as error:
                raise RegistryConflict("DELIVERY_PLAN_BINDING_MISMATCH", str(error)) from error
            for package in (implementation, review):
                diagnostics = package.provider_diagnostics
                if (not re.fullmatch(r"TASK-[1-9][0-9]*", package.id)
                        or diagnostics.get("readiness_schema_version") != 2
                        or not re.fullmatch(r"[1-9][0-9]*", str(diagnostics.get("github_source_ref", "")))):
                    raise RegistryConflict("DELIVERY_V2_SOURCE_REQUIRED")
                self._require_ready_package_contract(package)
                if diagnostics["readiness_proof"].get("target_ref") != authorization["base_ref"]:
                    raise RegistryConflict("DELIVERY_PLAN_BASE_MISMATCH")
            if (implementation.provider_diagnostics["readiness_proof"]["base_commit"] !=
                    action["checkpoint"]["plan"].get("base_commit")):
                raise RegistryConflict("DELIVERY_PLAN_BASE_MISMATCH")
            for package, status in ((implementation, TaskStatus.READY), (review, TaskStatus.ON_DECK)):
                bound = replace(package, status=status, provider_diagnostics={**package.provider_diagnostics,
                    "delivery_feature_id": feature_id, "delivery_run_id": run_id,
                    "delivery_generation": generation, "delivery_plan_action_id": plan_action_id})
                self._insert_package(connection, bound, now, source_system="github_issue",
                                     source_ref=str(package.provider_diagnostics["github_source_ref"]))
                for dependency_id in package.dependency_ids:
                    connection.execute("INSERT INTO task_dependencies(package_id,dependency_id) VALUES (?,?)",
                                       (package.id, dependency_id))
            connection.execute("UPDATE features SET status='READY',updated_at=? WHERE id=?", (now, feature_id))
            pair = {"run_id": run_id, "feature_id": feature_id, "generation": generation,
                    "implementation_id": implementation.id, "review_id": review.id,
                    "plan_action_id": plan_action_id, "previous_review_id": previous_review_id,
                    "registered_at": now}
            write_record(connection, f"pair:{feature_id}:{generation}", pair)
            write_record(connection, f"membership:{run_id}:{feature_id}:{generation}", pair)
            if scope is not None:
                # Only this checked transaction may extend a delivery-authorized run.
                scope["package_ids"] = sorted(set(scope["package_ids"]) | {implementation.id, review.id})
                connection.execute("UPDATE registry_metadata SET value=? WHERE key='bounded_run_scope'", (encoded(scope),))
            return {"feature_id": feature_id, "generation": generation,
                    "package_id": implementation.id, "review_id": review.id}

        return self._delivery_mutate("DELIVERY_PAIR_REGISTERED", f"delivery-pair:{feature_id}:{generation}",
                                     request, expected_revision, recorded_at, register)

    def invalidate_delivery_plan(self, plan_action_id: str, current_commit: str, reason: str, *,
                                 expected_revision: int, recorded_at: str) -> Mapping[str, Any]:
        request = dict(plan_action_id=plan_action_id, current_commit=current_commit, reason=reason)

        def invalidate(connection, now):
            action = read_record(connection, "action:" + identifier(plan_action_id))
            if (action is None or action["action"] != "PLAN" or action["state"] != "SUCCEEDED"
                    or not re.fullmatch(r"[0-9a-f]{40}", current_commit)
                    or current_commit == action["checkpoint"].get("plan", {}).get("base_commit")
                    or not reason):
                raise RegistryConflict("DELIVERY_PLAN_INVALIDATION_INVALID")
            self._delivery_scope(connection, action["run_id"], action["feature_id"], now, allow_paused=True)
            pairs = connection.execute("SELECT value FROM registry_metadata WHERE key LIKE 'delivery:pair:%'")
            if any(json.loads(row[0])["plan_action_id"] == plan_action_id for row in pairs):
                raise RegistryConflict("DELIVERY_REGISTERED_PLAN_REQUIRES_RETIREMENT")
            write_record(connection, "invalid-plan:" + plan_action_id, {**request, "recorded_at": now})
            return {"feature_id": action["feature_id"], "plan_action_id": plan_action_id}

        return self._delivery_mutate("DELIVERY_PLAN_INVALIDATED", "delivery-invalid-plan:" + plan_action_id,
                                     request, expected_revision, recorded_at, invalidate)

    def retire_unclaimed_delivery_pair(self, run_id: str, feature_id: str, current_commit: str, *,
                                       expected_revision: int, recorded_at: str) -> Mapping[str, Any]:
        request = dict(run_id=run_id, feature_id=feature_id, current_commit=current_commit)

        def retire(connection, now):
            self._delivery_scope(connection, run_id, feature_id, now, allow_paused=True)
            pairs = [json.loads(row[0]) for row in connection.execute(
                "SELECT value FROM registry_metadata WHERE key LIKE ?", (PREFIX + "pair:" + feature_id + ":%",))]
            if not pairs or not re.fullmatch(r"[0-9a-f]{40}", current_commit):
                raise RegistryConflict("DELIVERY_PAIR_RETIREMENT_INVALID")
            pair = max(pairs, key=lambda value: value["generation"])
            plan = read_record(connection, "action:" + pair["plan_action_id"])["checkpoint"]["plan"]
            if (read_record(connection, f"membership:{run_id}:{feature_id}:{pair['generation']}") is None
                    or current_commit == plan["base_commit"]):
                raise RegistryConflict("DELIVERY_PAIR_RETIREMENT_INVALID")
            for package_id, status in ((pair["implementation_id"], "READY"), (pair["review_id"], "ON_DECK")):
                row = connection.execute("SELECT status FROM work_packages WHERE id=?", (package_id,)).fetchone()
                if (row is None or row[0] != status
                        or connection.execute("SELECT 1 FROM attempts WHERE package_id=?", (package_id,)).fetchone()
                        or connection.execute("SELECT 1 FROM leases WHERE package_id=?", (package_id,)).fetchone()
                        or connection.execute("SELECT 1 FROM attempt_runtime_ownership r JOIN attempts a ON a.id=r.attempt_id WHERE a.package_id=?", (package_id,)).fetchone()):
                    raise RegistryConflict("DELIVERY_PAIR_ALREADY_CONSUMED", package_id)
                connection.execute("UPDATE work_packages SET status='BLOCKED',failure_detail=?,updated_at=? WHERE id=?",
                                   ("DELIVERY_BASE_MOVED: superseded by freshly prepared generation", now, package_id))
            write_record(connection, f"retired-pair:{feature_id}:{pair['generation']}",
                         {**request, "generation": pair["generation"], "recorded_at": now})
            return {"feature_id": feature_id, "generation": pair["generation"]}

        return self._delivery_mutate("DELIVERY_PAIR_RETIRED", "delivery-retire:" + digest(request),
                                     request, expected_revision, recorded_at, retire)

    def delivery_repair_binding(self, package_id: str) -> Mapping[str, Any] | None:
        from .sqlite_registry import _review_input_from_evidence
        with self._connection() as connection:
            connection.execute("BEGIN")
            package = connection.execute("SELECT * FROM work_packages WHERE id=?", (package_id,)).fetchone()
            if package is None:
                raise RegistryNotFound(package_id)
            diagnostics = json.loads(package["provider_diagnostics_json"])
            feature_id, generation = diagnostics.get("delivery_feature_id"), diagnostics.get("delivery_generation")
            if not feature_id or not generation:
                return None
            pair = read_record(connection, f"pair:{feature_id}:{generation}")
            if pair is None or pair["implementation_id"] != package_id:
                raise RegistryConflict("DELIVERY_REPAIR_BINDING_INVALID")
            if pair["previous_review_id"] is None:
                return None
            prior = read_record(connection, f"pair:{feature_id}:{generation - 1}")
            outcome = connection.execute("SELECT * FROM review_outcomes WHERE review_package_id=?",
                                         (pair["previous_review_id"],)).fetchone()
            inputs = connection.execute("SELECT * FROM evidence WHERE package_id=? AND kind='review-input'",
                                        (pair["previous_review_id"],)).fetchall()
            if (not prior or len(inputs) != 1 or outcome is None or outcome["state"] != "CHANGES_REQUESTED"
                    or outcome["target_package_id"] != prior["implementation_id"]):
                raise RegistryConflict("DELIVERY_REPAIR_BINDING_INVALID")
            source = _review_input_from_evidence(inputs[0])
            original = connection.execute("SELECT provider_diagnostics_json FROM work_packages WHERE id=?",
                                          (prior["implementation_id"],)).fetchone()
            return {"previous_package_id": prior["implementation_id"], "review_id": pair["previous_review_id"],
                    "outcome_id": outcome["id"], "implementation_commit": source.implementation_commit,
                    "base_commit": source.base_commit,
                    "paths": json.loads(original[0])["exclusive_paths"],
                    "changes_requested": json.loads(outcome["changes_requested_json"])}

    def delivery_review_input(self, review_id: str) -> Mapping[str, Any]:
        """Read native review material before CI publication; never dispatch it."""
        from .sqlite_registry import _review_input_from_evidence, _with_native_review_ci
        with self._connection() as connection:
            connection.execute("BEGIN")
            package = connection.execute("SELECT * FROM work_packages WHERE id=?", (review_id,)).fetchone()
            if (package is None or package["kind"] != "REVIEW"
                    or not json.loads(package["provider_diagnostics_json"]).get("delivery_feature_id")):
                raise RegistryConflict("DELIVERY_REVIEW_TARGET_INVALID")
            rows = connection.execute("SELECT * FROM evidence WHERE package_id=? AND kind='review-input'", (review_id,)).fetchall()
            if len(rows) != 1:
                raise RegistryConflict("REVIEW_INPUT_REQUIRED")
            return asdict(_with_native_review_ci(connection, _review_input_from_evidence(rows[0])))

    def delivery_scope_extension_is_safe(self, baseline, current) -> bool:
        if not isinstance(baseline, dict) or not isinstance(current, dict):
            return False
        if ({key: value for key, value in baseline.items() if key != "package_ids"}
                != {key: value for key, value in current.items() if key != "package_ids"}):
            return False
        old, new = set(baseline.get("package_ids", ())), set(current.get("package_ids", ()))
        if not old <= new:
            return False
        with self._connection() as connection:
            connection.execute("BEGIN")
            active = read_record(connection, "active-authorization")
            auth = read_record(connection, "authorization:" + str(current.get("run_id")))
            if (not auth or not active or active["run_id"] != auth["run_id"]
                    or any(current.get(key) != auth[key] for key in ("run_id", "deadline", "base_ref", "parent_limit"))):
                return False
            if not old:
                state = read_record(connection, "run-state:" + auth["run_id"]) or {}
                certificate = state.get("continuation_certificate") or {}
                unsigned = {key: value for key, value in certificate.items() if key != "certificate_sha256"}
                if (state.get("initial_scope") != baseline or certificate.get("initial_scope") != baseline
                        or certificate.get("coordinator_only") is not True or not certificate.get("approved_bindings")
                        or certificate.get("run_id") != auth["run_id"]
                        or certificate.get("coordinator_worker_id") != auth["coordinator_worker_id"]
                        or certificate.get("authorization_sha256") != digest(auth)
                        or certificate.get("certificate_sha256") != digest(unsigned)):
                    return False
            scope = connection.execute("SELECT value FROM registry_metadata WHERE key='bounded_run_scope'").fetchone()
            if scope is None or json.loads(scope[0]) != current:
                return False
            pairs = [json.loads(row[0]) for row in connection.execute(
                "SELECT value FROM registry_metadata WHERE key LIKE 'delivery:membership:%'")]
            certified = {pair[key] for pair in pairs if pair["run_id"] == auth["run_id"]
                         for key in ("implementation_id", "review_id")}
            return new <= certified

    def delivery_snapshot(self, *, run_id: str | None = None) -> Mapping[str, Any]:
        with self._connection() as connection:
            connection.execute("BEGIN")
            try:
                records = {}
                for row in connection.execute("SELECT key FROM registry_metadata WHERE key LIKE 'delivery:%'"):
                    key = row[0][len(PREFIX):]
                    records[key] = read_record(connection, key)
                revision = int(connection.execute("SELECT value FROM registry_metadata WHERE key='revision'").fetchone()[0])
                packages = {row["id"]: dict(row) for row in connection.execute("SELECT * FROM work_packages")}
                outcomes = {row["review_package_id"]: dict(row) for row in connection.execute("SELECT * FROM review_outcomes")}
                control = dict(connection.execute("SELECT * FROM factory_control WHERE singleton=1").fetchone())
                rows = []
                authorization = records.get("authorization:" + run_id) if run_id else None
                for key, request in sorted(records.items()):
                    if not key.startswith("request:"):
                        continue
                    feature_id = request["brief"]["id"]
                    if run_id and (authorization is None or feature_id not in authorization["feature_ids"]):
                        continue
                    pairs = sorted((value for name, value in records.items() if name.startswith("pair:")
                                    and value["feature_id"] == feature_id), key=lambda item: item["generation"])
                    pair = pairs[-1] if pairs else None
                    receipt = records.get("integration:" + feature_id)
                    waiting = [dep for dep in request["brief"].get("dependency_feature_ids", [])
                               if "integration:" + dep not in records]
                    action, reason = "PLAN", None
                    outcome = outcomes.get(pair["review_id"]) if pair else None
                    retired = records.get(f"retired-pair:{feature_id}:{pair['generation']}") if pair else None
                    if receipt:
                        action = "COMPLETE"
                    elif waiting:
                        action, reason = "WAIT_DEPENDENCIES", ",".join(waiting)
                    elif pair:
                        implementation, review = packages[pair["implementation_id"]], packages[pair["review_id"]]
                        if retired:
                            action = "PLAN"
                            if authorization and pair["generation"] + 1 >= authorization["max_generations"]:
                                action, reason = "BLOCKED", "DELIVERY_GENERATION_BUDGET_EXHAUSTED"
                        elif outcome:
                            action = "INTEGRATE" if outcome["state"] == "APPROVED" else "REPAIR"
                            if action == "REPAIR" and authorization and pair["generation"] + 1 >= authorization["max_generations"]:
                                action, reason = "BLOCKED", "DELIVERY_GENERATION_BUDGET_EXHAUSTED"
                        elif implementation["status"] == "BLOCKED" or review["status"] == "BLOCKED":
                            action, reason = "BLOCKED", implementation.get("failure_detail") or review.get("failure_detail")
                            if not reason:
                                failed = connection.execute("SELECT COALESCE(a.failure_detail,r.release_reason) FROM attempts a "
                                    "LEFT JOIN attempt_runtime_ownership r ON r.attempt_id=a.id WHERE a.package_id IN (?,?) "
                                    "AND a.outcome='FAILED' ORDER BY a.ended_at DESC LIMIT 1",
                                    (pair["implementation_id"], pair["review_id"])).fetchone()
                                reason = (failed[0] if failed else None) or "DELIVERY_ATTEMPT_BLOCKED_RECONCILIATION_REQUIRED"
                        elif implementation["status"] == "VERIFY_REVIEW":
                            action = "PUBLISH_REVIEW" if review["status"] == "ON_DECK" else "WAIT_REVIEW"
                        else:
                            action = "WAIT_IMPLEMENTATION"
                    unfinished = [value for name, value in records.items() if name.startswith("action:")
                                  and value["feature_id"] == feature_id and value["state"] in {"RUNNING", "UNCERTAIN"}]
                    generation = pair["generation"] + 1 if (action == "REPAIR" or retired) else (pair["generation"] if pair else 0)
                    plans = [value for name, value in records.items() if name.startswith("action:")
                             and value["feature_id"] == feature_id and value["action"] == "PLAN"
                             and value["inputs"].get("generation") == generation
                             and "invalid-plan:" + value["action_id"] not in records
                             and (not run_id or value["run_id"] == run_id)]
                    prepared = next((value for value in reversed(plans) if value["state"] == "SUCCEEDED"), None)
                    if action in {"PLAN", "REPAIR"} and prepared:
                        plan = prepared["checkpoint"].get("plan", {})
                        if plan.get("state") == "PREPARED":
                            action = "PROJECT"
                        else:
                            action, reason = "NEEDS_DECISION", "; ".join(plan.get("decisions_needed", []))
                    elif action in {"PLAN", "REPAIR"} and len(plans) >= 2:
                        action, reason = "BLOCKED", "DELIVERY_PLANNING_ATTEMPTS_EXHAUSTED"
                    if action == "INTEGRATE":
                        failures = [value for name, value in records.items() if name.startswith("action:")
                                    and value["feature_id"] == feature_id and value["action"] == "INTEGRATE"
                                    and value["state"] == "FAILED"]
                        if len(failures) >= 2:
                            action, reason = "BLOCKED", "DELIVERY_INTEGRATION_ATTEMPTS_EXHAUSTED"
                    if unfinished and not receipt:
                        action, reason = "RECONCILE_ACTION", unfinished[-1]["action_id"]
                    rows.append({"feature_id": feature_id, "brief": request["brief"], "pair": pair,
                                 "implementation_status": packages[pair["implementation_id"]]["status"] if pair else None,
                                 "review_status": packages[pair["review_id"]]["status"] if pair else None,
                                 "next_action": action, "reason": reason, "review_outcome": outcome,
                                 "generation": generation, "prepared_plan": prepared, "plan_attempts": len(plans),
                                 "integration": receipt, "unresolved_actions": unfinished})
                connection.rollback()
                return {"revision": revision, "control": control, "authorization": authorization,
                        "features": rows, "records": records}
            except Exception:
                connection.rollback()
                raise

    def publish_delivery_review(self, run_id: str, feature_id: str, review_id: str,
                                ci: Mapping[str, Any], *, expected_revision: int,
                                recorded_at: str) -> Mapping[str, Any]:
        """Publish a deferred review after trusted operator verification of CI."""
        from .sqlite_registry import _review_input_from_evidence, _verify_operator_review_packet
        request = dict(run_id=run_id, feature_id=feature_id, review_id=review_id, ci=dict(ci))

        def publish(connection, now):
            self._delivery_scope(connection, run_id, feature_id, now)
            review = connection.execute("SELECT * FROM work_packages WHERE id=?", (review_id,)).fetchone()
            if (review is None or review["kind"] != "REVIEW" or review["status"] != "ON_DECK"
                    or review["feature_id"] != feature_id
                    or read_record(connection, f"membership:{run_id}:{feature_id}:"
                        + str(json.loads(review["provider_diagnostics_json"]).get("delivery_generation"))) is None):
                raise RegistryConflict("DELIVERY_REVIEW_TARGET_INVALID")
            inputs = connection.execute("SELECT * FROM evidence WHERE package_id=? AND kind='review-input'",
                                        (review_id,)).fetchall()
            if len(inputs) != 1:
                raise RegistryConflict("REVIEW_INPUT_REQUIRED")
            review_input = _review_input_from_evidence(inputs[0])
            if (set(ci) != {"state", "implementation_commit", "pr_url", "run_url"}
                    or ci["state"] != "SUCCESS" or ci["implementation_commit"] != review_input.implementation_commit
                    or ci["pr_url"] != review_input.pr_url
                    or not re.fullmatch(r"https://github\.com/[^/]+/[^/]+/actions/runs/[1-9][0-9]*", str(ci["run_url"]))
                    or now <= timestamp(review_input.recorded_at)):
                raise RegistryConflict("REVIEW_CI_ATTESTATION_MISMATCH")
            _verify_operator_review_packet(replace(review_input, validation_evidence={
                **review_input.validation_evidence, "ci": dict(ci)}))
            metadata = {"review_input_id": review_input.id, "target_package_id": review_input.target_package_id,
                        "implementation_attempt_id": review_input.implementation_attempt_id,
                        "implementation_commit": review_input.implementation_commit,
                        "base_commit": review_input.base_commit, "pr_url": review_input.pr_url, "ci": dict(ci)}
            connection.execute("INSERT INTO evidence(id,package_id,kind,uri,summary,recorded_at,metadata_json) "
                               "VALUES (?,?,'review-ci',?,?,?,?)",
                               (f"review-ci:{review_input.id}", review_id, ci["run_url"],
                                "Exact implementation CI verified before delivery review publication.", now, encoded(metadata)))
            reasons = self._review_readiness_reasons(connection, review_id)
            if reasons:
                raise RegistryConflict("DELIVERY_REVIEW_NOT_REVIEWABLE", ",".join(reasons))
            self._require_ready_row_contract(connection, review_id)
            connection.execute("UPDATE work_packages SET status='READY',ready_at=?,updated_at=? WHERE id=?",
                               (now, now, review_id))
            return {"feature_id": feature_id, "package_id": review_id, "review_input_id": review_input.id}

        return self._delivery_mutate("DELIVERY_REVIEW_PUBLISHED", "delivery-review-publish:" + review_id,
                                     request, expected_revision, recorded_at, publish)

    def _delivery_approval(self, connection, feature_id):
        from .sqlite_registry import _review_input_from_evidence, _with_native_review_ci
        pairs = [json.loads(row[0]) for row in connection.execute(
            "SELECT value FROM registry_metadata WHERE key LIKE ?", (PREFIX + "pair:" + feature_id + ":%",))]
        if not pairs:
            raise RegistryConflict("DELIVERY_PAIR_MISSING")
        pair = max(pairs, key=lambda value: value["generation"])
        outcome = connection.execute("SELECT * FROM review_outcomes WHERE review_package_id=?",
                                     (pair["review_id"],)).fetchone()
        if outcome is None or outcome["state"] != "APPROVED":
            raise RegistryConflict("DELIVERY_APPROVAL_REQUIRED")
        inputs = connection.execute("SELECT * FROM evidence WHERE package_id=? AND kind='review-input'",
                                    (pair["review_id"],)).fetchall()
        if len(inputs) != 1:
            raise RegistryConflict("REVIEW_INPUT_REQUIRED")
        review_input = _with_native_review_ci(connection, _review_input_from_evidence(inputs[0]))
        ids = json.loads(outcome["approval_evidence_ids_json"])
        if not ids:
            raise RegistryConflict("DELIVERY_APPROVAL_REQUIRED")
        evidence = connection.execute("SELECT * FROM evidence WHERE id=?", (ids[0],)).fetchone()
        metadata = json.loads(evidence["metadata_json"]) if evidence else {}
        if (metadata.get("reviewed_commit") != review_input.implementation_commit
                or metadata.get("reviewed_base_commit") != review_input.base_commit
                or metadata.get("contract_sha256") != review_input.contract_sha256
                or metadata.get("review_input_evidence_id") != review_input.id):
            raise RegistryConflict("DELIVERY_APPROVAL_BINDING_MISMATCH")
        return {"feature_id": feature_id, "package_id": pair["implementation_id"],
                "implementation_commit": review_input.implementation_commit,
                "implementation_base": review_input.base_commit, "contract_sha256": review_input.contract_sha256,
                "review_outcome_id": outcome["id"], "review_attempt_id": metadata["attempt_id"],
                "reviewer_worker_id": outcome["reviewer_worker_id"],
                "implementer_worker_id": outcome["implementer_worker_id"],
                "reviewed_commit": review_input.implementation_commit, "reviewed_base_commit": review_input.base_commit,
                "pr_url": review_input.pr_url, "reviewed_pr_url": review_input.pr_url,
                "validation_commit": review_input.implementation_commit,
                "validation_evidence_ids": [review_input.id, f"review-ci:{review_input.id}"],
                "review_input_evidence_id": review_input.id, "approval_evidence_ids": ids, "verdict": "APPROVED"}

    def delivery_approval(self, feature_id: str) -> Mapping[str, Any]:
        with self._connection() as connection:
            connection.execute("BEGIN")
            try:
                result = self._delivery_approval(connection, identifier(feature_id))
                connection.rollback()
                return result
            except Exception:
                connection.rollback()
                raise

    def record_delivery_integration(self, run_id: str, feature_id: str, action_id: str,
                                    publication: Mapping[str, Any], *, expected_revision: int,
                                    recorded_at: str) -> Mapping[str, Any]:
        request = dict(run_id=run_id, feature_id=feature_id, action_id=action_id, publication=dict(publication))

        def integrate(connection, now):
            authorization, _, _ = self._delivery_scope(connection, run_id, feature_id, now, reconcile=True)
            action = read_record(connection, "action:" + action_id)
            if (action is None or action["action"] != "INTEGRATE" or action["feature_id"] != feature_id
                    or action["run_id"] != run_id or action["state"] not in {"RUNNING", "UNCERTAIN"}):
                raise RegistryConflict("DELIVERY_INTEGRATION_ACTION_INVALID")
            candidate = action["checkpoint"].get("candidate")
            if not isinstance(candidate, dict):
                raise RegistryConflict("DELIVERY_CANDIDATE_NOT_PERSISTED")
            approval = self._delivery_approval(connection, feature_id)
            unsigned_candidate = {key: value for key, value in candidate.items() if key != "receipt_sha256"}
            unsigned_publication = {key: value for key, value in publication.items() if key != "receipt_sha256"}
            if (candidate.get("receipt_sha256") != digest(unsigned_candidate)
                    or publication.get("receipt_sha256") != digest(unsigned_publication)
                    or candidate.get("kind") != "factory-integration-candidate"
                    or publication.get("kind") != "factory-integration-publication"
                    or publication.get("state") not in {"PUBLISHED", "ALREADY_PUBLISHED"}
                    or candidate.get("approval") != approval or publication.get("approval") != approval
                    or publication.get("candidate_receipt_sha256") != candidate["receipt_sha256"]
                    or publication.get("target_after") != candidate.get("target_after")
                    or publication.get("target_before") != candidate.get("target_before")
                    or publication.get("target_branch") != authorization["base_ref"]
                    or publication.get("integration_id") != candidate.get("integration_id")):
                raise RegistryConflict("DELIVERY_INTEGRATION_BINDING_MISMATCH")
            validations = candidate.get("validation")
            if (not isinstance(validations, list) or not validations
                    or any(item.get("returncode") != 0 or item.get("timed_out") is not False
                           or item.get("validated_commit") != candidate["target_after"] for item in validations)):
                raise RegistryConflict("DELIVERY_INTEGRATION_VALIDATION_REQUIRED")
            receipt = {"run_id": run_id, "feature_id": feature_id, "package_id": approval["package_id"],
                       "implementation_commit": approval["implementation_commit"], "pr_url": approval["pr_url"],
                       "review_outcome_id": approval["review_outcome_id"], "integration_commit": candidate["target_after"],
                       "candidate": candidate, "publication": dict(publication), "recorded_at": now}
            write_record(connection, "integration:" + feature_id, receipt)
            connection.execute("INSERT INTO evidence(id,package_id,kind,uri,summary,recorded_at,metadata_json) "
                               "VALUES (?,?,'artifact',?,?,?,?)",
                               ("delivery-integration:" + feature_id, approval["package_id"],
                                approval["pr_url"], "Approved implementation integrated at " + candidate["target_after"],
                                now, encoded({"integration_commit": candidate["target_after"],
                                    "implementation_commit": approval["implementation_commit"],
                                    "review_outcome_id": approval["review_outcome_id"],
                                    "publication_receipt_sha256": publication["receipt_sha256"]})))
            connection.execute("UPDATE work_packages SET status='DONE',updated_at=? WHERE id=?",
                               (now, approval["package_id"]))
            connection.execute("UPDATE features SET status='DONE',updated_at=? WHERE id=?", (now, feature_id))
            duration = (datetime.fromisoformat(now.replace("Z", "+00:00")) -
                        datetime.fromisoformat(action["started_at"].replace("Z", "+00:00"))).total_seconds()
            write_record(connection, "action:" + action_id,
                         {**action, "state": "SUCCEEDED", "checkpoint": {"candidate": candidate,
                          "publication": dict(publication)}, "runtime_seconds": max(0, duration), "updated_at": now},
                         replace_existing=True)
            return {"feature_id": feature_id, "package_id": approval["package_id"],
                    "integration_commit": candidate["target_after"]}

        return self._delivery_mutate("DELIVERY_INTEGRATED", "delivery-integrate:" + feature_id,
                                     request, expected_revision, recorded_at, integrate)
