"""Bind the delivery coordinator to the installed, account-verified runner config."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import time

from .delivery_coordinator import DeliveryCoordinator, PlannerConfiguration
from .delivery_integration import IntegrationError, IntegrationPolicy
from .delivery_plan import PlanError
from .delivery_runtime import DeliveryRuntimeError, GitHubProjection
from .operator import _validate_config
from .repository import RegistryConflict
from .sqlite_registry import SQLiteRegistry
from scripts.runner.registry_control import RunnerRegistryControl
from scripts.runner.capacity_publication import usage_path, write_collected_usage


def waiting_result(control, run_id=None):
    """An installed service waits without planning, telemetry writes or files."""
    return {"run_id": run_id, "revision": control["revision"], "state": "WAITING",
            "reason": "DISPATCH_PAUSED", "factory_mode": control["dispatch_mode"], "results": []}


class _ServiceCoordinator(DeliveryCoordinator):
    """Separate explicit preparation from a launchd service's LIVE authority."""

    def __init__(self, *args, prepare=False, **kwargs):
        super().__init__(*args, **kwargs)
        self._prepare = prepare

    def _require_first_paused_run(self, snapshot):
        control = snapshot["control"]
        scope = self.registry.dispatch_control().get("bounded_run")
        if (control["dispatch_mode"] != "PAUSED" or not control["kill_switch_engaged"]
                or "run-state:" + self.run_id in snapshot["records"]
                or (isinstance(scope, dict) and scope.get("run_id") == self.run_id)):
            raise RegistryConflict("DELIVERY_PREPARATION_NOT_AUTHORIZED")

    def _guard(self, *, bootstrap=False, planner=False):
        if self._prepare:
            self._require_first_paused_run(self.snapshot())
        result = super()._guard(bootstrap=bootstrap if self._prepare else False, planner=planner)
        if self._prepare:
            self._require_first_paused_run(result)
        return result

    def tick(self):
        if not self._prepare:
            control = self.registry.dispatch_control()
            if control["dispatch_mode"] != "LIVE" or control["kill_switch_engaged"]:
                return waiting_result(control, self.run_id)
        return super().tick()

    def _tick_locked(self):
        if not self._prepare:
            control = self.registry.dispatch_control()
            if control["dispatch_mode"] != "LIVE" or control["kill_switch_engaged"]:
                return waiting_result(control, self.run_id)
            return super()._tick_locked()
        snapshot = self._guard(bootstrap=True)
        self.state.mkdir(parents=True, exist_ok=True, mode=0o700)
        results = []
        for feature in snapshot["features"]:
            action = feature["next_action"]
            recover_preparation = (action == "RECONCILE_ACTION" and feature["unresolved_actions"]
                                   and feature["unresolved_actions"][-1]["action"] in {"PLAN", "PROJECT"})
            if action not in {"PLAN", "REPAIR", "PROJECT"} and not recover_preparation:
                results.append({"feature_id": feature["feature_id"], "action": action, "state": "WAITING"})
                continue
            try:
                self._guard(bootstrap=True)
                if recover_preparation:
                    self._recover(feature)
                elif action in {"PLAN", "REPAIR"}:
                    self._plan(feature)
                else:
                    self._project(feature)
                results.append({"feature_id": feature["feature_id"], "action": action, "state": "OBSERVED"})
            except (RegistryConflict, PlanError, DeliveryRuntimeError, IntegrationError, OSError, subprocess.SubprocessError) as error:
                results.append({"feature_id": feature["feature_id"], "action": action, "state": "BLOCKED",
                                "code": getattr(error, "code", str(error))[:300]})
        return {"run_id": self.run_id, "revision": self.snapshot()["revision"], "results": results}


def load_coordinator(config_path: Path, database: Path, *, prepare: bool = False) -> DeliveryCoordinator:
    """No free-form planner identity: use one configured account + shared pool."""
    if (not config_path.is_absolute() or config_path.is_symlink() or not config_path.is_file()
            or config_path.stat().st_uid != os.getuid() or config_path.stat().st_mode & 0o077):
        raise RegistryConflict("DELIVERY_PRIVATE_CONFIG_REQUIRED")
    config = json.loads(config_path.read_text())
    release = Path(__file__).resolve().parents[2]
    _validate_config(config, database, release)
    delivery = config.get("delivery")
    fields = {"run_id", "planner_agent", "coordinator_worker_id", "validation_commands"}
    if not isinstance(delivery, dict) or set(delivery) != fields:
        raise RegistryConflict("DELIVERY_SERVICE_CONFIG_INVALID")
    registry = SQLiteRegistry(database)
    snapshot = registry.delivery_snapshot(run_id=delivery["run_id"])
    auth = snapshot.get("authorization")
    if not auth or auth["coordinator_worker_id"] != delivery["coordinator_worker_id"]:
        raise RegistryConflict("DELIVERY_AUTHORIZATION_REQUIRED")
    # This repository's governing instructions currently forbid agent merges
    # into main. No configuration flag silently overrides that policy.
    if auth["base_ref"] in {"main", "master"}:
        raise RegistryConflict("MAIN_INTEGRATION_NOT_AUTHORIZED")
    agent_id = delivery["planner_agent"]
    agent = config["agents"].get(agent_id)
    collector = config.get("capacity_collectors", {}).get(agent_id)
    if not isinstance(agent, dict) or agent.get("provider") != "openai" or not isinstance(collector, dict):
        raise RegistryConflict("DELIVERY_PLANNER_ACCOUNT_CONFIG_INVALID")
    coordinator_id = auth["coordinator_worker_id"]
    if coordinator_id not in collector.get("shared_account_aliases", ()):
        raise RegistryConflict("DELIVERY_SHARED_ACCOUNT_ALIAS_REQUIRED")
    environment = {"PATH": config["path"], "HOME": str(Path.home()), "USER": os.environ.get("USER", ""),
                   **agent.get("env", {})}
    measured_environment = {"PATH": config["path"], "HOME": str(Path.home()), "USER": os.environ.get("USER", ""),
                            **collector.get("environment", {}), "CODEX_HOME": collector.get("codex_home")}
    if (not isinstance(environment.get("CODEX_HOME"), str)
            or Path(environment["CODEX_HOME"]).resolve() != Path(collector.get("codex_home", "")).resolve()
            or Path(agent["command"][0]).resolve() != Path(collector.get("executable", "")).resolve()
            or environment != measured_environment):
        raise RegistryConflict("DELIVERY_PLANNER_ACCOUNT_SOURCE_MISMATCH")
    workers = {item["id"]: item for item in registry.dispatch_snapshot(observed_at=datetime.now(timezone.utc).isoformat()).workers}
    pools = [(workers.get(worker_id) or {}).get("provider_diagnostics", {}).get("capacity_pool")
             for worker_id in (agent_id, coordinator_id)]
    if not isinstance(pools[0], str) or not re.fullmatch(r"[0-9a-f]{64}", pools[0]) or pools[0] != pools[1]:
        raise RegistryConflict("DELIVERY_PLANNER_ACCOUNT_UNBOUND")
    commands = delivery["validation_commands"]
    if (not isinstance(commands, list) or not commands
            or any(not isinstance(command, list) or not command
                   or any(not isinstance(arg, str) or not arg for arg in command) for command in commands)):
        raise RegistryConflict("DELIVERY_VALIDATION_CONFIG_INVALID")
    control = RunnerRegistryControl(database, repository=Path(config["repo"]))
    last_refresh = [None]

    def refresh_health():
        now = time.monotonic()
        if last_refresh[0] is None or now - last_refresh[0] >= 60:
            results = control.refresh_configured_capacity(config)
            # The coordinator and worker lanes share the same measured facts.
            # Publish before a fresh Registry signal suppresses another probe.
            write_collected_usage(usage_path(config), config, results)
            fresh = [item for item in results if item.get("worker_id") == coordinator_id and item.get("observations")]
            if not fresh:
                raise RegistryConflict("DELIVERY_COORDINATOR_TELEMETRY_UNAVAILABLE")
            last_refresh[0] = now
        # This is the coordinator's own observed liveness, not invented worker
        # activity or a re-dated capacity observation.
        if prepare:
            registry.record_delivery_preparation_heartbeat(auth['run_id'], coordinator_id,
                expected_revision=registry.dispatch_control()['revision'],
                recorded_at=datetime.now(timezone.utc).isoformat())
        else:
            control.observe_worker_heartbeat(coordinator_id)

    return _ServiceCoordinator(registry, repository=Path(config["repo"]), run_id=auth["run_id"], prepare=prepare,
        state_directory=Path(config["state"]) / "delivery", health_refresh=refresh_health,
        shared_git_lock=Path(config["state"]) / "git.lock",
        planner=PlannerConfiguration(provider=agent["provider"], command=tuple(agent["command"]),
            environment=environment, worker_id=coordinator_id, capacity_pool=pools[0]),
        github=GitHubProjection([config["gh"]], config["github"], environment={
            "PATH": config["path"], "HOME": str(Path.home()), "USER": os.environ.get("USER", "")}),
        integration=IntegrationPolicy(remote="origin", target_branch=auth["base_ref"],
                                      validation_commands=tuple(tuple(command) for command in commands)))
