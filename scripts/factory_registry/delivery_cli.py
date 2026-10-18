"""Owner intake and bounded authorization for the continuous delivery loop.

Run with ``python -m scripts.factory_registry.delivery_cli``. These commands
preserve owner requests and authorization through the Registry API. Explicit
``prepare`` permits first-run PAUSED planning/projection; supervised ``tick``
executes only while LIVE. Neither command activates the Factory itself.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import pathlib
import sqlite3
import sys
from typing import Any, Sequence


# Importing an installed release must not create bytecode inside that release.
sys.dont_write_bytecode = True

from .delivery_plan import FeatureBrief, PlanError  # noqa: E402
from .repository import RegistryConflict, RegistryError, RegistryNotFound  # noqa: E402
from .sqlite_delivery import identifier  # noqa: E402
from .sqlite_registry import SQLiteRegistry  # noqa: E402


class DeliveryUsageError(ValueError):
    """Invalid CLI input; the diagnostic must not repeat supplied values."""


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        raise DeliveryUsageError("DELIVERY_ARGUMENTS_INVALID")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _nonnegative_integer(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise ValueError("nonnegative integer required")
    return parsed


def _context(parser: argparse.ArgumentParser, *, mutation: bool) -> None:
    parser.add_argument("--database", required=True, type=pathlib.Path,
                        help="Absolute path to the existing authoritative Registry")
    if mutation:
        parser.add_argument("--expected-revision", required=True, type=_nonnegative_integer,
                            help="Registry revision observed immediately before this operation")


def parser() -> argparse.ArgumentParser:
    root = _ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    submit = commands.add_parser("submit", help="Preserve one feature and the desired user experience")
    _context(submit, mutation=True)
    submit.add_argument("--id", required=True, dest="feature_id")
    submit.add_argument("--title", required=True)
    submit.add_argument("--experience", required=True,
                        help="Describe what the user should be able to do and observe")
    submit.add_argument("--constraint", action="append", default=[])
    submit.add_argument("--acceptance", action="append", default=[])
    submit.add_argument("--depends-on", action="append", default=[])

    authorize = commands.add_parser("authorize", help="Authorize a bounded feature scope; keep Factory mode unchanged")
    _context(authorize, mutation=True)
    authorize.add_argument("--run-id", required=True)
    authorize.add_argument("--feature-id", action="append", required=True)
    authorize.add_argument("--deadline", required=True, help="ISO 8601 deadline with explicit time zone")
    authorize.add_argument("--base-ref", required=True)
    authorize.add_argument("--parent-limit", required=True, type=int)
    authorize.add_argument("--max-generations", required=True, type=int)
    authorize.add_argument("--coordinator-worker-id", required=True)

    status = commands.add_parser("status", help="Read delivery requests, next actions and authoritative state")
    _context(status, mutation=False)
    status.add_argument("--run-id", help="Limit to an existing authorized run")
    tick = commands.add_parser("tick", help="Perform one authorized delivery pass; never activate LIVE")
    _context(tick, mutation=False)
    tick.add_argument("--config", required=True, type=pathlib.Path)
    prepare = commands.add_parser("prepare", help="Explicitly plan/project a fresh authorized run while PAUSED")
    _context(prepare, mutation=True)
    prepare.add_argument("--config", required=True, type=pathlib.Path)
    return root


def run(args: argparse.Namespace) -> dict[str, Any]:
    if not args.database.is_absolute() or not args.database.is_file():
        raise RegistryConflict("DELIVERY_DATABASE_UNAVAILABLE")
    registry = SQLiteRegistry(args.database)
    if args.command == "submit":
        raw = {"id": args.feature_id, "title": args.title, "user_experience": args.experience}
        for field, values in (("constraints", args.constraint),
                              ("acceptance_criteria", args.acceptance),
                              ("dependency_feature_ids", args.depends_on)):
            if values:
                raw[field] = values
        brief = FeatureBrief.from_dict(raw)
        result = registry.submit_delivery_request(brief.as_dict(),
            expected_revision=args.expected_revision, recorded_at=utc_now())
    elif args.command == "authorize":
        result = registry.authorize_delivery_run({
            "run_id": args.run_id, "feature_ids": sorted(args.feature_id),
            "deadline": args.deadline, "base_ref": args.base_ref,
            "parent_limit": args.parent_limit, "max_generations": args.max_generations,
            "coordinator_worker_id": args.coordinator_worker_id,
        }, expected_revision=args.expected_revision, recorded_at=utc_now())
    elif args.command == "status":
        if args.run_id is not None:
            identifier(args.run_id)
        result = registry.delivery_snapshot(run_id=args.run_id)
        if args.run_id is not None and result.get("authorization") is None:
            raise RegistryNotFound("delivery authorization")
    elif args.command == "tick":
        from .delivery_service import load_coordinator, waiting_result
        control = registry.dispatch_control()
        if control["dispatch_mode"] != "LIVE" or control["kill_switch_engaged"]:
            result = waiting_result(control)
        else:
            result = load_coordinator(args.config, args.database).tick()
    elif args.command == "prepare":
        from .delivery_service import load_coordinator
        if registry.dispatch_control()["revision"] != args.expected_revision:
            raise RegistryConflict("REGISTRY_REVISION_CHANGED")
        result = load_coordinator(args.config, args.database, prepare=True).tick()
    else:
        raise DeliveryUsageError("DELIVERY_ARGUMENTS_INVALID")
    return {"kind": "threadline-factory-delivery", "passed": True,
            "command": args.command, **dict(result)}


def _write_error(command: str | None, code: str, *, status: int = 1) -> int:
    print(json.dumps({"kind": "threadline-factory-delivery-error", "passed": False,
                      "command": command, "error": code}, sort_keys=True,
                     separators=(",", ":")), file=sys.stderr)
    return status


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = parser().parse_args(argv)
    except DeliveryUsageError:
        return _write_error(None, "DELIVERY_ARGUMENTS_INVALID", status=2)
    try:
        result = run(args)
    except RegistryConflict as error:
        return _write_error(args.command, error.code)
    except RegistryNotFound:
        return _write_error(args.command, "DELIVERY_NOT_FOUND")
    except PlanError:
        return _write_error(args.command, "FEATURE_BRIEF_INVALID")
    except (OSError, sqlite3.Error):
        return _write_error(args.command, "DELIVERY_REGISTRY_UNAVAILABLE")
    except (RegistryError, ValueError, TypeError):
        return _write_error(args.command, "DELIVERY_INPUT_INVALID")
    print(json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
