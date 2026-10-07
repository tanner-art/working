#!/usr/bin/env python3
"""Reviewed command line surface for a controlled local Factory restart."""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
from typing import Any


# A reviewed release must remain byte-for-byte identical while the operator
# imports its control modules from that release directory.
sys.dont_write_bytecode = True


ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.factory_registry.operator import (  # noqa: E402
    OperatorError,
    canary_worker_gate,
    enable_live,
    followup_review_worker_gate,
    migrate_registry_v3_to_v4,
    migrate_registry_v4_to_v5,
    migrate_registry_v5_to_v6,
    parse_canary_spec,
    parse_bounded_pilot_spec,
    parse_followup_review_spec,
    record_external_integration_review_input,
    parse_review_input_spec,
    parse_bounded_run_scope,
    preflight,
    prepare_ready_package,
    prepare_dry_run,
    record_review_decision,
    recover_allowed_authors_pending,
    reconcile,
    reconcile_historical_package,
    return_paused,
    restore_registry_v3_backup,
    restore_registry_v4_backup,
    status,
    stop,
    store_preservation_evidence,
    update_allowed_authors,
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

    command = subparsers.add_parser(
        "migrate-registry-v6",
        help="Atomically migrate a quiescent PAUSED Registry from v5 to v6",
    )
    command.add_argument("--database", required=True, type=pathlib.Path)
    command.add_argument("--release", required=True, type=pathlib.Path)
    command.add_argument("--release-commit", required=True)
    command.add_argument("--preservation", required=True, type=pathlib.Path)
    command.add_argument("--expect-revision", required=True, type=int)
    command.add_argument("--backup", type=pathlib.Path)
    command.add_argument("--observed-at")

    command = subparsers.add_parser(
        "restore-registry-v4", help="Restore the verified v4 backup before v5 receipts exist"
    )
    command.add_argument("--database", required=True, type=pathlib.Path)
    command.add_argument("--backup", required=True, type=pathlib.Path)
    command.add_argument("--backup-sha256", required=True)
    command.add_argument("--release", required=True, type=pathlib.Path)
    command.add_argument("--release-commit", required=True)
    command.add_argument("--preservation", required=True, type=pathlib.Path)
    command.add_argument("--expect-revision", required=True, type=int)
    command.add_argument("--observed-at")

    command = subparsers.add_parser(
        "reconcile-historical-package",
        help="Retire an integrated or superseded historical package with exact Git ancestry evidence",
    )
    _context(command)
    command.add_argument("--spec", required=True, type=pathlib.Path)

    command = subparsers.add_parser(
        "migrate-registry-v5",
        help="Atomically migrate a quiescent PAUSED Registry from v4 to v5",
    )
    command.add_argument("--database", required=True, type=pathlib.Path)
    command.add_argument("--release", required=True, type=pathlib.Path)
    command.add_argument("--release-commit", required=True)
    command.add_argument("--preservation", required=True, type=pathlib.Path)
    command.add_argument("--expect-revision", required=True, type=int)
    command.add_argument("--backup", type=pathlib.Path)
    command.add_argument("--observed-at")

    command = subparsers.add_parser(
        "install-preservation", help="Copy the approved snapshot into Registry evidence storage"
    )
    command.add_argument("--database", required=True, type=pathlib.Path)
    command.add_argument("--source", required=True, type=pathlib.Path)
    command.add_argument("--release", required=True, type=pathlib.Path)
    command.add_argument("--release-commit", required=True)
    command.add_argument("--expect-revision", required=True, type=int)
    command.add_argument("--observed-at")

    command = subparsers.add_parser(
        "migrate-registry-v4", help="Atomically migrate a quiescent PAUSED Registry from v3 to v4"
    )
    command.add_argument("--database", required=True, type=pathlib.Path)
    command.add_argument("--release", required=True, type=pathlib.Path)
    command.add_argument("--release-commit", required=True)
    command.add_argument("--preservation", required=True, type=pathlib.Path)
    command.add_argument("--expect-revision", required=True, type=int)
    command.add_argument("--backup", type=pathlib.Path)
    command.add_argument("--observed-at")

    command = subparsers.add_parser(
        "restore-registry-v3", help="Restore the verified v3 backup while cutover remains quiescent"
    )
    command.add_argument("--database", required=True, type=pathlib.Path)
    command.add_argument("--backup", required=True, type=pathlib.Path)
    command.add_argument("--backup-sha256", required=True)
    command.add_argument("--release", required=True, type=pathlib.Path)
    command.add_argument("--release-commit", required=True)
    command.add_argument("--preservation", required=True, type=pathlib.Path)
    command.add_argument("--expect-revision", required=True, type=int)
    command.add_argument("--observed-at")

    command = subparsers.add_parser("preflight", help="Verify the complete restart gate")
    _context(command)
    command.add_argument("--observed-at")
    command.add_argument("--require-workers", action="store_true")
    command.add_argument("--canary-feature")

    command = subparsers.add_parser(
        "update-allowed-authors",
        help="CAS a reviewed GitHub-author allowlist expansion while PAUSED",
    )
    _context(command)
    command.add_argument("--spec", required=True, type=pathlib.Path)

    command = subparsers.add_parser(
        "recover-allowed-authors",
        help="Finish or clear the durable pending journal from an interrupted allowlist update",
    )
    _context(command)

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

    command = subparsers.add_parser("register-bounded-pilot", help="Atomically register one or two reviewed Registry pairs")
    _context(command)
    command.add_argument("--spec", required=True, type=pathlib.Path)
    command.add_argument("--observed-at")

    command = subparsers.add_parser(
        "register-followup-review",
        help="Register one bounded review retry after changes were requested",
    )
    _context(command)
    command.add_argument("--spec", required=True, type=pathlib.Path)
    command.add_argument("--observed-at")

    command = subparsers.add_parser("record-review-input", help="Record immutable historical implementation facts for a registered review")
    _context(command)
    command.add_argument("--spec", required=True, type=pathlib.Path)

    command = subparsers.add_parser(
        "record-external-integration-review-input",
        help="Bind an exact externally merged implementation to a pending Registry review",
    )
    _context(command)
    command.add_argument("--spec", required=True, type=pathlib.Path)

    command = subparsers.add_parser("bind-legacy-source", help="CAS-bind an unstarted legacy package to its existing GitHub issue")
    _context(command)
    command.add_argument("--package", required=True)
    command.add_argument("--issue", required=True, type=int)
    command.add_argument("--queue-contract", required=True, type=pathlib.Path)
    command.add_argument("--observed-at")

    command = subparsers.add_parser("enable-live", help="Promote reviewed plists and CAS PAUSED to LIVE")
    _context(command)
    command.add_argument("--canary-feature", required=True)
    command.add_argument("--observed-at")
    command.add_argument("--mode", choices=("serial", "lanes"), default="lanes")
    command.add_argument("--dashboard-port", type=int, default=8787)
    command.add_argument("--bounded-run", type=pathlib.Path,
                         help="reviewed JSON run envelope; omission preserves legacy canary mode")

    command = subparsers.add_parser("stop", help="Engage the Registry kill switch (or no-op for a superseded run timer)")
    command.add_argument("--database", required=True, type=pathlib.Path)
    command.add_argument("--reason", required=True)
    command.add_argument("--run-id", help="scheduled run identity; omission is unconditional owner/emergency stop")

    command = subparsers.add_parser("reconcile", help="Terminate and close STOPPING ownership")
    _context(command)
    command.add_argument("--observed-at")

    command = subparsers.add_parser("requeue-failed", help="Requeue one terminal failed package")
    _context(command)
    command.add_argument("--package", required=True)
    command.add_argument("--reason", required=True)
    command.add_argument("--observed-at")

    command = subparsers.add_parser(
        "record-review-outcome",
        help="Atomically bind reviewer evidence and a structured review outcome",
    )
    _context(command)
    command.add_argument("--spec", required=True, type=pathlib.Path)

    command = subparsers.add_parser("return-paused", help="CAS drained STOPPING state to PAUSED")
    _context(command)
    command.add_argument("--reason", required=True)
    command.add_argument("--observed-at")
    return parser


def run(args: argparse.Namespace) -> dict[str, Any]:
    if args.command == "status":
        return dict(status(args.database, observed_at=args.observed_at))
    if args.command == "install-preservation":
        return dict(store_preservation_evidence(
            args.database,
            args.source,
            args.release,
            args.release_commit,
            args.expect_revision,
            observed_at=args.observed_at,
        ))
    if args.command == "migrate-registry-v4":
        return dict(migrate_registry_v3_to_v4(
            args.database,
            args.release,
            args.preservation,
            args.release_commit,
            args.expect_revision,
            backup_path=args.backup,
            observed_at=args.observed_at,
        ))
    if args.command == "migrate-registry-v5":
        return dict(migrate_registry_v4_to_v5(
            args.database,
            args.release,
            args.preservation,
            args.release_commit,
            args.expect_revision,
            backup_path=args.backup,
            observed_at=args.observed_at,
        ))
    if args.command == "migrate-registry-v6":
        return dict(migrate_registry_v5_to_v6(
            args.database, args.release, args.preservation, args.release_commit,
            args.expect_revision, backup_path=args.backup, observed_at=args.observed_at,
        ))
    if args.command == "restore-registry-v3":
        return dict(restore_registry_v3_backup(
            args.database,
            args.backup,
            args.release,
            args.preservation,
            args.release_commit,
            args.backup_sha256,
            args.expect_revision,
            observed_at=args.observed_at,
        ))
    if args.command == "restore-registry-v4":
        return dict(restore_registry_v4_backup(
            args.database,
            args.backup,
            args.release,
            args.preservation,
            args.release_commit,
            args.backup_sha256,
            args.expect_revision,
            observed_at=args.observed_at,
        ))
    if args.command == "preflight":
        return dict(preflight(
            **_preflight_args(
                args,
                require_workers=args.require_workers or bool(args.canary_feature),
                canary_feature_id=args.canary_feature,
            )
        ))
    if args.command == "update-allowed-authors":
        return dict(update_allowed_authors(
            args.database, args.config, args.release, args.preservation,
            args.release_commit, args.expect_revision,
            _load_object(args.spec, "allowed-authors update spec"),
        ))
    if args.command == "recover-allowed-authors":
        return dict(recover_allowed_authors_pending(
            args.database, args.config, args.release, args.preservation,
            args.release_commit, args.expect_revision,
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
        spec = _load_object(args.spec, "canary spec")
        feature, implementation, review = parse_canary_spec(spec)
        repository = pathlib.Path(_load_object(args.config, "runner config")["repo"])
        implementation = prepare_ready_package(
            implementation, spec["implementation"]["queue_contract"],
            repository=repository, target_ref="main",
        )
        review = prepare_ready_package(
            review, spec["review"]["queue_contract"],
            repository=repository, target_ref="main",
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
    if args.command == "register-bounded-pilot":
        observed_at = args.observed_at or utc_now()
        preflight(**_preflight_args(args, observed_at=observed_at, require_workers=True))
        spec = _load_object(args.spec, "bounded pilot spec")
        pairs = parse_bounded_pilot_spec(spec)
        repository = pathlib.Path(_load_object(args.config, "runner config")["repo"])
        pairs = tuple((
            feature,
            prepare_ready_package(
                implementation, raw["implementation"]["queue_contract"],
                repository=repository, target_ref="main",
            ),
            prepare_ready_package(
                review, raw["review"]["queue_contract"],
                repository=repository, target_ref="main",
            ),
        ) for (feature, implementation, review), raw in zip(pairs, spec["pairs"]))
        registry = SQLiteRegistry(args.database)
        # Registration is still PAUSED; evaluate the candidate packages before
        # writing so the next activation has a real independent pair path.
        for _feature, implementation, review in pairs:
            canary_worker_gate(
                registry.dispatch_snapshot(observed_at=observed_at), implementation, review,
                observed_at=observed_at, scoped=True,
            )
        revision = registry.register_bounded_pilot(
            pairs, expected_revision=args.expect_revision, recorded_at=observed_at,
        )
        return {
            "kind": "threadline-factory-register-bounded-pilot", "passed": True,
            "package_ids": [package.id for pair in pairs for package in pair[1:]],
            "previous_revision": args.expect_revision, "revision": revision,
        }
    if args.command == "enable-live":
        bounded_run = (
            parse_bounded_run_scope(_load_object(args.bounded_run, "bounded run spec"))
            if args.bounded_run else None
        )
        return dict(enable_live(
            args.database, args.config, args.release, args.preservation,
            args.release_commit, args.expect_revision, args.canary_feature,
            mode=args.mode, dashboard_port=args.dashboard_port,
            bounded_run=bounded_run,
        ))
    if args.command == "register-followup-review":
        observed_at = args.observed_at or utc_now()
        preflight(**_preflight_args(args, observed_at=observed_at, require_workers=True))
        spec = _load_object(args.spec, "follow-up review spec")
        review = parse_followup_review_spec(spec)
        repository = pathlib.Path(_load_object(args.config, "runner config")["repo"])
        review = prepare_ready_package(
            review, spec["review"]["queue_contract"],
            repository=repository, target_ref="main",
        )
        registry = SQLiteRegistry(args.database)
        worker_gate = followup_review_worker_gate(
            registry.dispatch_snapshot(observed_at=observed_at),
            review,
            implementer_worker_id=registry.successful_package_worker(
                review.dependency_ids[0]
            ),
            observed_at=observed_at,
        )
        revision = registry.register_followup_review(
            review,
            expected_revision=args.expect_revision,
            recorded_at=observed_at,
        )
        return {
            "kind": "threadline-factory-register-followup-review",
            "passed": True,
            "review_package_id": review.id,
            "target_package_id": review.dependency_ids[0],
            "previous_revision": args.expect_revision,
            "revision": revision,
            "worker_gate": worker_gate,
        }
    if args.command == "record-review-input":
        review_input = parse_review_input_spec(_load_object(args.spec, "review input spec"))
        preflight(**_preflight_args(args, observed_at=review_input.recorded_at, require_workers=False))
        registry = SQLiteRegistry(args.database)
        revision = registry.record_operator_review_input(
            review_input, expected_revision=args.expect_revision
        )
        return {"kind": "threadline-factory-record-review-input", "passed": True,
                "review_package_id": review_input.review_package_id, "review_input_id": review_input.id,
                "revision": revision}
    if args.command == "record-external-integration-review-input":
        return dict(record_external_integration_review_input(
            args.database, args.config, args.release, args.preservation,
            args.release_commit, args.expect_revision,
            _load_object(args.spec, "external integration review spec"),
        ))
    if args.command == "bind-legacy-source":
        observed_at = args.observed_at or utc_now()
        preflight(**_preflight_args(args, observed_at=observed_at, require_workers=False))
        contract = _load_object(args.queue_contract, "legacy queue contract")
        revision = SQLiteRegistry(args.database).bind_legacy_package_source(
            args.package, github_issue=args.issue, queue_contract=contract,
            expected_revision=args.expect_revision, recorded_at=observed_at,
        )
        return {"kind": "threadline-factory-bind-legacy-source", "passed": True,
                "package_id": args.package, "github_issue": args.issue,
                "previous_revision": args.expect_revision, "revision": revision}
    if args.command == "reconcile-historical-package":
        return dict(reconcile_historical_package(
            args.database, args.config, args.release, args.preservation,
            args.release_commit, args.expect_revision,
            _load_object(args.spec, "historical reconciliation spec"),
        ))
    if args.command == "stop":
        return dict(stop(args.database, args.reason, expected_run_id=args.run_id))
    if args.command == "reconcile":
        preflight(**_preflight_args(
            args,
            allowed_modes=("STOPPING",),
            require_empty_ownership=False,
            require_workers=False,
            allow_stopping_ownership_reconciliation=True,
        ))
        result = dict(reconcile(args.database, expected_revision=args.expect_revision))
        # The transient allowance ends as soon as ownership has been drained.
        preflight(**_preflight_args(
            args,
            expected_revision=result["control"]["revision"],
            allowed_modes=("STOPPING",),
            require_workers=False,
        ))
        return result
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
    if args.command == "record-review-outcome":
        return dict(record_review_decision(
            args.database,
            args.config,
            args.release,
            args.preservation,
            args.release_commit,
            args.expect_revision,
            _load_object(args.spec, "review outcome spec"),
        ))
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
