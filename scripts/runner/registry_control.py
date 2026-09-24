"""Opt-in Registry gate for the controlled runner path.

Legacy GitHub polling remains unchanged when ``registry_database`` is absent.
When configured, every claim and provider launch fails closed through the
authoritative Registry and attempt/process provenance is persisted there.
"""

from __future__ import annotations

import os
import pathlib
import sys
from datetime import datetime, timezone


ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.factory_registry.models import TaskStatus  # noqa: E402
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

    def pre_claim(self) -> int:
        return self.registry.require_live_dispatch()

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
