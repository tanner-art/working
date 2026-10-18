"""Restartable delivery actions; implementation still uses Registry worker leases.

This module is deliberately not another scheduler. It prepares owner-authorized
features, publishes exact reviews, and integrates approved artifacts. Ordinary
waiting/blocked features never pause unrelated work. All external effects have
a durable action reservation and checkpoints in the authoritative Registry.
"""
from __future__ import annotations

from dataclasses import dataclass
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import fcntl
import os
from pathlib import Path
import re
import subprocess
import time
from typing import Any, Mapping
import uuid

from .delivery_integration import ApprovalBinding, IntegrationError, IntegrationPolicy, prepare_integration, publish_integration
from .delivery_plan import FeatureBrief, PlanError, build_packages, build_planner_prompt, validate_plan
from .delivery_runtime import (DeliveryRuntimeError, ExternalActionUncertain, GitHubProjection,
    planner_request_digest, recover_planner_result, run_readonly_planner)
from .repository import RegistryConflict
from .shadow_dispatch import decide_shadow
from .sqlite_delivery import digest, timestamp


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _object(properties):
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


_STR = {"type": "string"}
_LIST = {"type": "array", "items": _STR}
_PACKAGE_SCHEMA = _object({**{key: _STR for key in (
    "behavior", "module_boundary", "persistence_owner", "instructions", "capacity_size", "capacity_risk")},
    **{key: _LIST for key in ("public_interface", "acceptance_criteria", "out_of_scope", "planning_paths",
       "existing_paths", "new_paths", "integration_paths", "test_paths", "required_capabilities")},
    "end_to_end": _object({key: _STR for key in ("entry_point", "user_action", "observable_result")})})
PLAN_SCHEMA = _object({"state": {"type": "string", "enum": ["PREPARED", "NEEDS_DECISION"]},
    "feature_id": _STR, "base_commit": _STR, "user_experience": _STR,
    "dependency_feature_ids": _LIST, "decisions_needed": _LIST,
    "package": {"anyOf": [_PACKAGE_SCHEMA, {"type": "null"}]}})


def normalized_plan(value):
    result = dict(value)
    if result.get("state") == "NEEDS_DECISION" and result.get("package") is None:
        result.pop("package", None)
    return result


@dataclass(frozen=True)
class PlannerConfiguration:
    provider: str
    command: tuple[str, ...]
    environment: Mapping[str, str]
    worker_id: str
    timeout_seconds: int = 900
    capacity_pool: str | None = None


def require_coordinator_health(dispatch, planner):
    """Shared read-only activation/runtime gate for the real coordinator account."""
    rejected = decide_shadow(dispatch).global_rejections
    if rejected:
        raise RegistryConflict("DELIVERY_COORDINATOR_CAPACITY_BLOCKED", ",".join(str(item.code) for item in rejected))
    worker = next((item for item in dispatch.workers if item["id"] == planner.worker_id), None)
    if worker is None or worker.get("role") != "ORCHESTRA":
        raise RegistryConflict("DELIVERY_COORDINATOR_INVALID")
    try:
        age = (datetime.fromisoformat(timestamp(dispatch.observed_at).replace("Z", "+00:00")) -
               datetime.fromisoformat(timestamp(worker.get("last_heartbeat_at")).replace("Z", "+00:00"))).total_seconds()
    except (TypeError, ValueError, RegistryConflict):
        age = -1
    if not 0 <= age <= 180 or worker.get("availability") not in {"IDLE", "BUSY"}:
        raise RegistryConflict("DELIVERY_COORDINATOR_HEARTBEAT_INVALID")
    pool = planner.capacity_pool
    if (not isinstance(pool, str) or not re.fullmatch(r"[0-9a-f]{64}", pool)
            or worker.get("provider_diagnostics", {}).get("capacity_pool") != pool):
        raise RegistryConflict("DELIVERY_COORDINATOR_ACCOUNT_UNBOUND")
    for scope in worker.get("capacity_scopes") or ("default",):
        observations = [item for item in dispatch.usage_observations if item.get("worker_id") == worker["id"]
            and item.get("capacity_scope", "default") == scope]
        latest = max(observations, key=lambda item: item["observed_at"], default={})
        if latest.get("provider_diagnostics", {}).get("capacity_pool") != pool:
            raise RegistryConflict("DELIVERY_COORDINATOR_CAPACITY_ACCOUNT_MISMATCH")


class DeliveryCoordinator:
    def __init__(self, registry, *, repository: Path, run_id: str, state_directory: Path,
                 planner: PlannerConfiguration, github: GitHubProjection, integration: IntegrationPolicy,
                 clock=utc_now, planner_runner=run_readonly_planner, health_refresh=None, shared_git_lock=None):
        self.registry, self.repository, self.run_id = registry, repository.resolve(), run_id
        self.state = state_directory.resolve()
        self.planner, self.github, self.integration = planner, github, integration
        self.clock, self.planner_runner = clock, planner_runner
        self.health_refresh = health_refresh
        self.shared_git_lock = shared_git_lock
        self.owner = "delivery-" + uuid.uuid4().hex

    def snapshot(self):
        return self.registry.delivery_snapshot(run_id=self.run_id)

    def _write(self, method, *args, **kwargs):
        # Retry only a transaction that demonstrably made no authoritative change.
        for retry in range(3):
            snapshot = self.snapshot()
            try:
                return method(*args, **kwargs, expected_revision=snapshot["revision"], recorded_at=self.clock())
            except RegistryConflict as error:
                if error.code != "REGISTRY_REVISION_CHANGED" or retry == 2:
                    raise
        raise AssertionError("unreachable")

    def _guard(self, *, bootstrap=False, planner=False):
        if planner and self.health_refresh is not None:
            self.health_refresh()
        snapshot = self.snapshot()
        auth, control = snapshot["authorization"], snapshot["control"]
        if (not auth or auth["base_ref"] != self.integration.target_branch
                or auth["coordinator_worker_id"] != self.planner.worker_id
                or snapshot["records"].get("active-authorization", {}).get("run_id") != self.run_id):
            raise RegistryConflict("DELIVERY_RUN_SCOPE_CHANGED")
        if timestamp(self.clock()) >= auth["deadline"]:
            raise RegistryConflict("RUN_DEADLINE_REACHED")
        paused_bootstrap = (bootstrap and control["dispatch_mode"] == "PAUSED" and control["kill_switch_engaged"]
                            and "run-state:" + self.run_id not in snapshot["records"])
        if not paused_bootstrap:
            scope = self.registry.dispatch_control().get("bounded_run")
            if (control["dispatch_mode"] != "LIVE" or control["kill_switch_engaged"] or not scope
                    or any(scope.get(key) != auth[key] for key in ("run_id", "deadline", "base_ref", "parent_limit"))):
                raise RegistryConflict("DISPATCH_PAUSED")
        if planner:
            dispatch = self.registry.dispatch_snapshot(observed_at=self.clock())
            require_coordinator_health(dispatch, self.planner)
        return snapshot

    def _git(self, *args):
        if self.shared_git_lock is None:
            return self._git_unlocked(*args)
        self.shared_git_lock.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.shared_git_lock.open("a") as lock:
            deadline = time.monotonic() + self.integration.git_timeout_seconds
            while True:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise RegistryConflict("DELIVERY_GIT_BUSY")
                    time.sleep(0.05)
            return self._git_unlocked(*args)

    def _git_unlocked(self, *args):
        result = subprocess.run(["git", "--no-replace-objects", "-c", "core.hooksPath=/dev/null",
                                 "-C", str(self.repository), *args], text=True, capture_output=True,
                                timeout=self.integration.git_timeout_seconds, check=False)
        if result.returncode:
            raise DeliveryRuntimeError("DELIVERY_GIT_OPERATION_FAILED")
        return result.stdout.strip()

    def _refresh_base(self):
        branch = self.integration.target_branch
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*", branch) or ".." in branch:
            raise RegistryConflict("DELIVERY_TARGET_INVALID")
        observed = self._git("ls-remote", "--refs", "--", self.integration.remote, "refs/heads/" + branch).splitlines()
        if len(observed) != 1 or len(observed[0].split()) != 2:
            raise RegistryConflict("DELIVERY_TARGET_UNAVAILABLE")
        base, ref = observed[0].split()
        if not re.fullmatch(r"[0-9a-f]{40}", base) or ref != "refs/heads/" + branch:
            raise RegistryConflict("DELIVERY_TARGET_UNAVAILABLE")
        self._git("fetch", "--no-tags", "--no-write-fetch-head", self.integration.remote, base)
        # Never move a checked-out branch behind its working tree.
        worktrees = self._git("worktree", "list", "--porcelain")
        if "branch refs/heads/" + branch in worktrees.splitlines():
            existing = self._git("rev-parse", "refs/heads/" + branch)
            if existing != base:
                raise RegistryConflict("DELIVERY_TARGET_CHECKED_OUT")
        else:
            self._git("update-ref", "refs/heads/" + branch, base)
        return base

    def _reserve(self, feature, kind, inputs):
        action_id = "delivery-" + uuid.uuid4().hex
        self._write(self.registry.reserve_delivery_action, self.run_id, feature["feature_id"], action_id, kind,
                    inputs, owner=self.owner)
        return self.snapshot()["records"]["action:" + action_id]

    def _checkpoint(self, action, result, state="RUNNING"):
        self._write(self.registry.update_delivery_action, action["action_id"], owner=action["owner"],
                    state=state, result=result)
        return self.snapshot()["records"]["action:" + action["action_id"]]

    def _plan(self, feature):
        self._guard(bootstrap=True, planner=True)
        base = self._refresh_base()
        brief = FeatureBrief.from_dict(feature["brief"])
        prompt = build_planner_prompt(brief, repository=self.repository, target_ref=self.integration.target_branch)
        prompt += "\nFor the machine output schema, use package:null when NEEDS_DECISION.\n"
        if feature["review_outcome"]:
            source = self.registry.review_input(feature["pair"]["review_id"])
            original = self.snapshot()["records"]["action:" + feature["pair"]["plan_action_id"]]["checkpoint"]["plan"]
            prompt += ("\nCORRECTION: The next worker receives the exact rejected patch on the current base. "
                "Preserve ownership of every previous implementation file in this correction. Fix the review findings "
                "within the original owner scope; do not discard working code.\n" + json.dumps({
                    "previous_plan": original, "review_outcome": feature["review_outcome"],
                    "implementation_commit": source["implementation_commit"]}, sort_keys=True))
        request_hash = planner_request_digest(provider=self.planner.provider, prompt=prompt, schema=PLAN_SCHEMA)
        action = self._reserve(feature, "PLAN", {"generation": feature["generation"], "base_commit": base,
            "prompt": prompt, "request_sha256": request_hash})
        workspace = self.state / action["action_id"] / "worktree"
        logs = workspace.parent / "planner"
        workspace.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._git("worktree", "add", "--detach", str(workspace), base)
            action = self._checkpoint(action, {"workspace": str(workspace), "logs": str(logs)})
            def validate(result):
                return validate_plan(normalized_plan(result), brief=brief, repository=self.repository,
                                     target_ref=self.integration.target_branch)
            def started(pid, pgid):
                self._checkpoint(action, {"workspace": str(workspace), "logs": str(logs), "pid": pid, "pgid": pgid})
            def completed(result, elapsed):
                self._checkpoint(action, {"plan": validate(result).as_dict(), "provider_seconds": elapsed,
                                          "workspace": str(workspace), "logs": str(logs)}, "SUCCEEDED")
            self.planner_runner(provider=self.planner.provider, command=self.planner.command,
                environment=self.planner.environment, prompt=prompt, repository=workspace,
                schema=PLAN_SCHEMA, log_directory=logs, on_start=started, on_result=completed,
                monitor=lambda: self._guard(bootstrap=True, planner=True), validate_result=validate,
                timeout_seconds=min(self.planner.timeout_seconds,
                    (datetime.fromisoformat(self.snapshot()["authorization"]["deadline"].replace("Z", "+00:00")) -
                     datetime.fromisoformat(timestamp(self.clock()).replace("Z", "+00:00"))).total_seconds()))
        except Exception as error:
            current = self.snapshot()["records"]["action:" + action["action_id"]]
            if current["state"] not in {"SUCCEEDED", "FAILED"}:
                self._checkpoint(action, {**current["checkpoint"], "error": type(error).__name__,
                    "code": getattr(error, "code", str(error))[:300]},
                    "UNCERTAIN" if (logs / "result.json").exists() else "FAILED")
            raise

    def _project(self, feature, action=None):
        self._guard(bootstrap=True)
        base = self._refresh_base()
        plan_action = feature["prepared_plan"]
        if plan_action is None and action:
            plan_action = self.snapshot()["records"]["action:" + action["inputs"]["plan_action_id"]]
        if plan_action["checkpoint"]["plan"]["base_commit"] != base:
            if action:
                self._checkpoint(action, {**action["checkpoint"], "code": "DELIVERY_BASE_MOVED"}, "FAILED")
            return self._write(self.registry.invalidate_delivery_plan, plan_action["action_id"], base,
                               "integration target advanced before registration")
        plan = validate_plan(plan_action["checkpoint"]["plan"], brief=FeatureBrief.from_dict(feature["brief"]),
                             repository=self.repository, target_ref=self.integration.target_branch)
        if action is None:
            action = self._reserve(feature, "PROJECT", {"plan_action_id": plan_action["action_id"],
                                                       "generation": feature["generation"]})
        checkpoint = dict(action["checkpoint"])
        try:
            for kind in ("implementation", "review"):
                key = kind + "_issue"
                if key not in checkpoint:
                    def intent(kind=kind):
                        checkpoint[kind + "_create_intent"] = True
                        self._checkpoint(action, checkpoint)
                        self._guard(bootstrap=True)
                    number = self.github.allocate_issue(
                        self.run_id + ":" + feature["feature_id"] + ":" + plan_action["action_id"] + ":" + kind,
                        feature["brief"]["title"] + (" — independent review" if kind == "review" else ""),
                        on_create=intent, reconcile_only=bool(checkpoint.get(kind + "_create_intent")))
                    checkpoint[key] = number
                    self._checkpoint(action, checkpoint)
            snapshot = self.snapshot()
            deps = {dep: snapshot["records"]["integration:" + dep]["package_id"]
                    for dep in feature["brief"].get("dependency_feature_ids", [])}
            prepared = build_packages(plan, repository=self.repository, target_ref=self.integration.target_branch,
                implementation_issue=checkpoint["implementation_issue"], review_issue=checkpoint["review_issue"],
                dependency_packages=deps)
            for kind, contract in (("implementation", prepared.implementation_contract), ("review", prepared.review_contract)):
                self._guard(bootstrap=True)
                projection = self.github.update_contract(checkpoint[kind + "_issue"], contract)
                checkpoint[kind + "_contract_sha256"] = projection["contract_sha256"]
                self._checkpoint(action, checkpoint)
            self._guard(bootstrap=True)
            if self._refresh_base() != base:
                raise PlanError("DELIVERY_BASE_MOVED")
            registered = self._write(self.registry.register_delivery_pair, self.run_id, feature["feature_id"],
                feature["generation"], prepared.implementation, prepared.review,
                plan_action_id=plan_action["action_id"],
                previous_review_id=feature["pair"]["review_id"] if feature["review_outcome"] else None)
            self._checkpoint(action, {**checkpoint, "registration": registered}, "SUCCEEDED")
        except Exception as error:
            self._checkpoint(action, {**checkpoint, "code": getattr(error, "code", str(error))[:300]}, "UNCERTAIN")
            raise

    def _ci(self, review_input):
        # GitHub is an observation, never the readiness/assignment authority.
        if not re.fullmatch(r"https://github\.com/" + re.escape(self.github.repository) + r"/pull/[1-9][0-9]*",
                            str(review_input.get("pr_url", ""))):
            raise RegistryConflict("DELIVERY_REPOSITORY_MISMATCH")
        pr = self.github._request(["pr", "view", review_input["pr_url"], "--repo", self.github.repository,
                                   "--json", "headRefOid,state"])
        if not isinstance(pr, dict):
            raise RegistryConflict("DELIVERY_PR_OBSERVATION_INVALID")
        if pr.get("headRefOid") != review_input["implementation_commit"] or pr.get("state") != "OPEN":
            raise RegistryConflict("DELIVERY_PR_HEAD_CHANGED")
        runs = self.github._request(["run", "list", "--repo", self.github.repository, "--commit",
            review_input["implementation_commit"], "--workflow", "Validate app", "--limit", "100",
            "--json", "headSha,status,conclusion,workflowName,url,createdAt"])
        if not isinstance(runs, list):
            raise RegistryConflict("DELIVERY_CI_UNAVAILABLE")
        matching = [run for run in runs if isinstance(run, dict)
                    and run.get("headSha") == review_input["implementation_commit"]
                    and run.get("workflowName") == "Validate app"]
        if not matching:
            raise RegistryConflict("DELIVERY_CI_PENDING")
        try:
            observed = [(timestamp(run.get("createdAt")), run) for run in matching]
        except RegistryConflict as error:
            raise RegistryConflict("DELIVERY_CI_OBSERVATION_INVALID") from error
        latest_time = max(when for when, _ in observed)
        newest = [run for when, run in observed if when == latest_time]
        if any(run.get("status") != "completed" or run.get("conclusion") != "success" for run in newest):
            raise RegistryConflict("DELIVERY_CI_NOT_GREEN")
        latest = newest[0]
        if not re.fullmatch(r"https://github\.com/" + re.escape(self.github.repository) + r"/actions/runs/[1-9][0-9]*",
                            str(latest.get("url", ""))):
            raise RegistryConflict("DELIVERY_CI_OBSERVATION_INVALID")
        return {"state": "SUCCESS", "implementation_commit": review_input["implementation_commit"],
                "pr_url": review_input["pr_url"], "run_url": latest["url"]}

    def _review(self, feature):
        self._guard()
        review_id = feature["pair"]["review_id"]
        packet = self.registry.delivery_review_input(review_id)
        ci = self._ci(packet)
        self._guard()
        return self._write(self.registry.publish_delivery_review, self.run_id, feature["feature_id"], review_id, ci)

    def _integrate(self, feature, action=None):
        approval = ApprovalBinding(**self.registry.delivery_approval(feature["feature_id"]))
        if action is None:
            self._guard()
            self._ci(self.registry.review_input(feature["pair"]["review_id"]))
            action = self._reserve(feature, "INTEGRATE", {"approval_sha256": digest(approval.__dict__)})
        candidate = action["checkpoint"].get("candidate")
        history = list(action["checkpoint"].get("superseded_candidates", []))
        try:
            if candidate is not None:
                # A target change is ordinary concurrency, not authority to
                # publish an old candidate. Rebuild and revalidate against the
                # new target, preserving the old candidate in the action log.
                try:
                    observed = publish_integration(self.repository, candidate, approval, self.integration,
                        before_publish=lambda: (_ for _ in ()).throw(RegistryConflict("DELIVERY_REPLAY_ONLY")))
                except RegistryConflict as error:
                    if error.code != "DELIVERY_REPLAY_ONLY":
                        raise
                except IntegrationError as error:
                    if error.code != "TARGET_MOVED":
                        raise
                    self._guard()
                    if len(history) >= 2:
                        self._checkpoint(action, {"superseded_candidates": history + [candidate],
                            "code": "DELIVERY_TARGET_CHURN_LIMIT"}, "FAILED")
                        return None
                    history.append(candidate)
                    candidate = None
                    action = self._checkpoint(action, {"superseded_candidates": history})
                else:
                    return self._write(self.registry.record_delivery_integration, self.run_id, feature["feature_id"],
                                       action["action_id"], observed)
            if candidate is None:
                self._guard()
                base = self._refresh_base()
                self._git("fetch", "--no-tags", "--no-write-fetch-head", self.integration.remote, approval.implementation_commit)
                candidate = prepare_integration(self.repository, approval, self.integration,
                    expected_target_sha=base, integration_id=action["action_id"], workspace_parent=self.state)
                self._checkpoint(action, {"candidate": candidate, "superseded_candidates": history})
            def before_publish():
                self._guard()
                if digest(self.registry.delivery_approval(feature["feature_id"])) != action["inputs"]["approval_sha256"]:
                    raise RegistryConflict("DELIVERY_APPROVAL_CHANGED")
                self._ci(self.registry.review_input(feature["pair"]["review_id"]))
            publication = publish_integration(self.repository, candidate, approval, self.integration,
                                               before_publish=before_publish)
            return self._write(self.registry.record_delivery_integration, self.run_id, feature["feature_id"],
                               action["action_id"], publication)
        except Exception as error:
            self._checkpoint(action, {**action["checkpoint"], **({"candidate": candidate} if candidate else {}),
                "superseded_candidates": history, "failure_evidence": getattr(error, "evidence", {}),
                "code": getattr(error, "code", str(error))[:300]},
                "UNCERTAIN" if candidate is not None else "FAILED")
            raise

    def _recover(self, feature):
        action = feature["unresolved_actions"][-1]
        if action["action"] == "INTEGRATE":
            return self._integrate(feature, action)
        if action["action"] == "PROJECT":
            registered = next((record for name, record in self.snapshot()["records"].items()
                if name.startswith("pair:") and record["plan_action_id"] == action["inputs"]["plan_action_id"]), None)
            if registered:
                return self._checkpoint(action, {**action["checkpoint"], "reconciled_pair": registered}, "SUCCEEDED")
            return self._project(feature, action)
        if action["action"] == "PLAN":
            logs = Path(action["checkpoint"].get("logs", str(self.state / action["action_id"] / "planner")))
            if not (logs / "result.json").exists():
                pgid = action["checkpoint"].get("pgid")
                if pgid is not None:
                    if type(pgid) is not int or pgid <= 1:
                        raise RegistryConflict("DELIVERY_PLANNER_PROCESS_IDENTITY_INVALID")
                    try:
                        os.killpg(pgid, 0)  # observation only; never signal a reused identity
                    except ProcessLookupError:
                        pass
                    else:
                        raise RegistryConflict("DELIVERY_PLANNER_PROCESS_STILL_PRESENT")
                # Service lock proves the prior coordinator is absent. Its
                # private lifeline closes, killing the provider group; before
                # on_start was recorded the exec barrier could not release.
                return self._checkpoint(action, {**action["checkpoint"],
                    "code": "PLANNER_EXIT_WITHOUT_RESULT", "recovered": True}, "FAILED")
            def validate(result):
                return validate_plan(normalized_plan(result), brief=FeatureBrief.from_dict(feature["brief"]),
                                     repository=self.repository, target_ref=self.integration.target_branch)
            result = recover_planner_result(logs, request_sha256=action["inputs"]["request_sha256"], validate_result=validate)
            return self._checkpoint(action, {**action["checkpoint"], "plan": validate(result["result"]).as_dict(),
                "provider_seconds": result["elapsed_seconds"], "recovered": True}, "SUCCEEDED")
        raise RegistryConflict("DELIVERY_ACTION_RECONCILIATION_REQUIRED")

    @contextmanager
    def _exclusive_service(self):
        # The lock is keyed by the actual database, not a caller-selected log
        # directory. A crashed process releases it; another live coordinator
        # cannot borrow its persisted owner token to repeat external effects.
        path = self.registry.database.resolve().with_suffix(".delivery.lock")
        descriptor = os.open(path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise RegistryConflict("DELIVERY_COORDINATOR_BUSY") from error
            yield
        finally:
            os.close(descriptor)

    def tick(self):
        with self._exclusive_service():
            return self._tick_locked()

    def _tick_locked(self):
        """One fair pass over authorized features; no queue-wide pause on waiting."""
        snapshot = self.snapshot()
        if not snapshot["authorization"]:
            raise RegistryConflict("DELIVERY_AUTHORIZATION_REQUIRED")
        self.state.mkdir(parents=True, exist_ok=True, mode=0o700)
        results = []
        health = None
        # Keep actual coordinator/account telemetry fresh even when every
        # feature is waiting on a worker or review. No stopped/expired run
        # starts fresh collection; the dashboard never fabricates heartbeats.
        if (self.health_refresh is not None
                and snapshot["control"]["dispatch_mode"] == "LIVE"
                and not snapshot["control"]["kill_switch_engaged"]
                and snapshot["records"].get("active-authorization", {}).get("run_id") == self.run_id
                and timestamp(self.clock()) < snapshot["authorization"]["deadline"]):
            try:
                self.health_refresh()
                health = {"state": "FRESH"}
            except (RegistryConflict, OSError, subprocess.SubprocessError) as error:
                health = {"state": "DEGRADED", "code": getattr(error, "code", "DELIVERY_TELEMETRY_UNAVAILABLE")}
                # Planners still enforce their own fresh-account gate. Read-only
                # recovery of an already-published receipt remains possible.
        for original in snapshot["features"]:
            feature = next(item for item in self.snapshot()["features"] if item["feature_id"] == original["feature_id"])
            action = feature["next_action"]
            try:
                if action in {"PLAN", "REPAIR"}:
                    self._plan(feature)
                elif action == "PROJECT":
                    self._project(feature)
                elif action == "PUBLISH_REVIEW":
                    self._review(feature)
                elif action == "INTEGRATE":
                    self._integrate(feature)
                elif action == "RECONCILE_ACTION":
                    self._recover(feature)
                elif action == "WAIT_IMPLEMENTATION" and feature["implementation_status"] == "READY":
                    self._guard(bootstrap=True)
                    base = self._refresh_base()
                    plan = self.snapshot()["records"]["action:" + feature["pair"]["plan_action_id"]]["checkpoint"]["plan"]
                    if base != plan["base_commit"]:
                        self._write(self.registry.retire_unclaimed_delivery_pair, self.run_id, feature["feature_id"], base)
                results.append({"feature_id": feature["feature_id"], "action": action, "state": "OBSERVED"})
            except (RegistryConflict, PlanError, DeliveryRuntimeError, IntegrationError, OSError, subprocess.SubprocessError) as error:
                results.append({"feature_id": feature["feature_id"], "action": action, "state": "BLOCKED",
                                "code": getattr(error, "code", str(error))[:300]})
        result = {"run_id": self.run_id, "revision": self.snapshot()["revision"], "results": results}
        if health is not None:
            result["health"] = health
        return result
