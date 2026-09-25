#!/usr/bin/env python3
"""Reviewed command line surface for a controlled local Factory restart."""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
from typing import Any


ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.factory_registry.operator import (  # noqa: E402
    OperatorError,
    canary_worker_gate,
    enable_live,
    parse_canary_spec,
    preflight,
    prepare_dry_run,
    reconcile,
    return_paused,
    status,
    stop,
    utc_now,
    validate_telemetry_payload,
    _load_object,
)
from scripts.factory_registry.repository import RegistryError  # noqa: E402
from scripts.factory_registry.sqlite_registry import SQLiteRegistry  # noqa: E402


def _context(parser: argparse.ArgumentParser, *, revision: bool = True) -> None:
    parser.add_argument("--database", required=True, type=pathlib.Path)
    parser.add_argument("--config", required=True, type=pathlib.Path)
    parser.add_argument("--release", required=True, type=pathlib.Path)
    parser.add_argument("--release-commit", required=True)
    parser.add_argument("--preservation", required=True, type=pathlib.Path)
    if revision:
        parser.add_argument("--expect-revision", required=True, type=int)


def _preflight_args(args: argparse.Namespace, **kwargs: Any) -> dict[str, Any]:
    values = dict(
        database=args.database,
        config_path=args.config,
        release=args.release,
        preservation_path=args.preservation,
        expected_commit=args.release_commit,
        expected_revision=args.expect_revision,
        observed_at=getattr(args, "observed_at", None),
    )
    values.update(kwargs)
    return values


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    command = subparsers.add_parser("status", help="Read Registry control and ownership state")
    command.add_argument("--database", required=True, type=pathlib.Path)
    command.add_argument("--observed-at")

    command = subparsers.add_parser("preflight", help="Verify the complete restart gate")
    _context(command)
    command.add_argument("--observed-at")
    command.add_argument("--require-workers", action="store_true")
    command.add_argument("--canary-feature")

    command = subparsers.add_parser(
        "prepare-dry-run", help="Kill first, reconcile, migrate config, and load dry-run services"
    )
    _context(command)
    command.add_argument("--migration", required=True, type=pathlib.Path)
    command.add_argument("--mode", choices=("serial", "lanes"), default="lanes")
    command.add_argument("--dashboard-port", type=int, default=8787)

    command = subparsers.add_parser("sync-worker", help="Persist fresh active worker telemetry")
    _context(command)
    command.add_argument("--telemetry", required=True, type=pathlib.Path)
    command.add_argument("--observed-at")

    command = subparsers.add_parser("register-canary", help="Register one bounded implementation/review pair")
    _context(command)
    command.add_argument("--spec", required=True, type=pathlib.Path)
    command.add_argument("--observed-at")

    command = subparsers.add_parser("enable-live", help="Promote reviewed plists and CAS PAUSED to LIVE")
    _context(command)
    command.add_argument("--canary-feature", required=True)
    command.add_argument("--observed-at")
    command.add_argument("--mode", choices=("serial", "lanes"), default="lanes")
    command.add_argument("--dashboard-port", type=int, default=8787)

    command = subparsers.add_parser("stop", help="Unconditionally engage the Registry kill switch")
    command.add_argument("--database", required=True, type=pathlib.Path)
    command.add_argument("--reason", required=True)

    command = subparsers.add_parser("reconcile", help="Terminate and close STOPPING ownership")
    _context(command)
    command.add_argument("--observed-at")

    command = subparsers.add_parser("requeue-failed", help="Requeue one terminal failed package")
    _context(command)
    command.add_argument("--package", required=True)
    command.add_argument("--reason", required=True)
    command.add_argument("--observed-at")

    command = subparsers.add_parser("return-paused", help="CAS drained STOPPING state to PAUSED")
    _context(command)
    command.add_argument("--reason", required=True)
    command.add_argument("--observed-at")
    return parser


def run(args: argparse.Namespace) -> dict[str, Any]:
    if args.command == "status":
        return dict(status(args.database, observed_at=args.observed_at))
    if args.command == "preflight":
        return dict(preflight(
            **_preflight_args(
                args,
                require_workers=args.require_workers or bool(args.canary_feature),
                canary_feature_id=args.canary_feature,
            )
        ))
    if args.command == "prepare-dry-run":
        migration = _load_object(args.migration, "config migration")
        return dict(prepare_dry_run(
            args.database, args.config, args.release, args.preservation,
            args.release_commit, args.expect_revision, migration,
            mode=args.mode, dashboard_port=args.dashboard_port,
        ))
    if args.command == "sync-worker":
        observed_at = args.observed_at or utc_now()
        preflight(**_preflight_args(args, observed_at=observed_at))
        payload = _load_object(args.telemetry, "worker telemetry")
        worker, observations = validate_telemetry_payload(payload, observed_at)
        revision = SQLiteRegistry(args.database).sync_worker_telemetry(
            worker,
            observations,
            expected_revision=args.expect_revision,
            recorded_at=observed_at,
        )
        return {
            "kind": "threadline-factory-sync-worker",
            "passed": True,
            "worker_id": worker.id,
            "usage_observation_ids": [value["id"] for value in observations],
            "previous_revision": args.expect_revision,
            "revision": revision,
        }
    if args.command == "register-canary":
        observed_at = args.observed_at or utc_now()
        preflight(**_preflight_args(args, observed_at=observed_at, require_workers=True))
        feature, implementation, review = parse_canary_spec(
            _load_object(args.spec, "canary spec")
        )
        registry = SQLiteRegistry(args.database)
        worker_gate = canary_worker_gate(
            registry.dispatch_snapshot(observed_at=observed_at),
            implementation,
            review,
            observed_at=observed_at,
        )
        revision = registry.register_canary_bundle(
            feature,
            implementation,
            review,
            expected_revision=args.expect_revision,
            recorded_at=observed_at,
        )
        return {
            "kind": "threadline-factory-register-canary",
            "passed": True,
            "feature_id": feature.id,
            "implementation_package_id": implementation.id,
            "review_package_id": review.id,
            "previous_revision": args.expect_revision,
            "revision": revision,
            "worker_gate": worker_gate,
        }
    if args.command == "enable-live":
        return dict(enable_live(
            args.database, args.config, args.release, args.preservation,
            args.release_commit, args.expect_revision, args.canary_feature,
            mode=args.mode, dashboard_port=args.dashboard_port,
        ))
    if args.command == "stop":
        return dict(stop(args.database, args.reason))
    if args.command == "reconcile":
        preflight(**_preflight_args(
            args,
            allowed_modes=("STOPPING",),
            require_empty_ownership=False,
            require_workers=False,
        ))
        return dict(reconcile(args.database, expected_revision=args.expect_revision))
    if args.command == "requeue-failed":
        observed_at = args.observed_at or utc_now()
        preflight(**_preflight_args(args, observed_at=observed_at, require_workers=True))
        revision = SQLiteRegistry(args.database).requeue_failed_package(
            args.package,
            expected_revision=args.expect_revision,
            changed_at=observed_at,
            reason=args.reason,
        )
        return {
            "kind": "threadline-factory-requeue-failed",
            "passed": True,
            "package_id": args.package,
            "previous_revision": args.expect_revision,
            "revision": revision,
        }
    if args.command == "return-paused":
        preflight(**_preflight_args(
            args,
            allowed_modes=("STOPPING", "RECOVERY_REQUIRED"),
            require_workers=False,
        ))
        return dict(return_paused(
            args.database, expected_revision=args.expect_revision, reason=args.reason
        ))
    raise OperatorError(f"unsupported command: {args.command}")


def main(argv: list[str] | None = None) -> int:
    os.umask(0o077)
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        evidence = run(args)
    except (OperatorError, RegistryError, ValueError, OSError) as error:
        print(json.dumps({
            "kind": "threadline-factory-operator-error",
            "passed": False,
            "command": args.command,
            "error_type": type(error).__name__,
            "error": str(error),
        }, separators=(",", ":"), sort_keys=True), file=sys.stderr)
        return 1
    print(json.dumps(evidence, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
