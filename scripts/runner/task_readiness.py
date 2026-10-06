"""Read-only, versioned pre-provider checks for complete Factory packets.

Legacy packets are reported as needing preparation; they are not retroactively
invalidated. Version 2 packets opt in to a complete, fail-closed contract.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import sqlite3
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping


_KINDS = {"coding", "integration", "device"}
_SHA = re.compile(r"[0-9a-f]{40}")


@dataclass(frozen=True)
class Readiness:
    state: str
    reasons: tuple[str, ...]
    base_commit: str | None = None


def _safe_path(value: Any) -> bool:
    if not isinstance(value, str) or not value or "\\" in value:
        return False
    path = pathlib.PurePosixPath(value)
    return not path.is_absolute() and all(part not in {"", ".", ".."} for part in value.split("/"))


def _git(repo: pathlib.Path, *args: str) -> bool:
    return subprocess.run(
        ["git", "-C", str(repo), *args], stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, check=False,
    ).returncode == 0


def _git_commit(repo: pathlib.Path, ref: str) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--verify", f"{ref}^{{commit}}"],
        capture_output=True, text=True, check=False,
    )
    commit = result.stdout.strip()
    return commit if result.returncode == 0 and _SHA.fullmatch(commit) else None


def _regular_git_blob(repo: pathlib.Path, commit: str, path: str) -> bool:
    result = subprocess.run(
        ["git", "-C", str(repo), "ls-tree", commit, "--", path],
        capture_output=True, text=True, check=False, timeout=10,
    )
    if result.returncode != 0:
        return False
    rows = result.stdout.splitlines()
    if len(rows) != 1 or not rows[0].endswith("\t" + path):
        return False
    return rows[0].split(" ", 1)[0] in {"100644", "100755"}


def registration_proof(
    contract: Mapping[str, Any], *, repository: pathlib.Path,
    target_ref: str, acceptance_criteria: tuple[str, ...],
) -> Mapping[str, Any]:
    """Resolve the immutable version-2 planning tree before Registry READY."""
    if contract.get("schema_version") != 2:
        return {}
    reasons = list(contract_shape_reasons(contract))
    if (not isinstance(target_ref, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*", target_ref)
            or ".." in target_ref or target_ref.endswith("/")):
        reasons.append("TARGET_REF_INVALID")
    if not acceptance_criteria or any(
        not isinstance(item, str) or not item.strip() for item in acceptance_criteria
    ):
        reasons.append("ACCEPTANCE_CRITERIA_MISSING")
    if not isinstance(contract.get("instructions"), str) or not contract["instructions"].strip():
        reasons.append("CONTRACT_UNREADABLE")
    if not repository.is_dir() or not _git(repository, "rev-parse", "--is-inside-work-tree"):
        reasons.append("REPOSITORY_UNAVAILABLE")
    declared = contract.get("readiness")
    base = declared.get("base_commit") if isinstance(declared, Mapping) else None
    if isinstance(base, str) and _SHA.fullmatch(base) and "REPOSITORY_UNAVAILABLE" not in reasons:
        if not _git(repository, "cat-file", "-e", f"{base}^{{commit}}"):
            reasons.append("BASE_COMMIT_MISSING")
        elif "TARGET_REF_INVALID" not in reasons and _git_commit(repository, target_ref) != base:
            reasons.append("BASE_REF_CHANGED")
    if reasons:
        raise ValueError(",".join(sorted(set(reasons))))
    assert isinstance(declared, Mapping) and isinstance(base, str)
    planning_hashes: dict[str, str] = {}
    for path in sorted(set(declared["planning_paths"])):
        if not _regular_git_blob(repository, base, path):
            reasons.append(f"PLANNING_CONTRACT_UNREADABLE:{path}")
            continue
        result = subprocess.run(
            ["git", "-C", str(repository), "show", f"{base}:{path}"],
            capture_output=True, check=False, timeout=10,
        )
        if result.returncode != 0 or not result.stdout:
            reasons.append(f"PLANNING_CONTRACT_UNREADABLE:{path}")
        else:
            planning_hashes[path] = hashlib.sha256(result.stdout).hexdigest()
    for path in sorted(set(declared["existing_paths"]) | set(declared["integration_paths"])
                       | set(declared["test_paths"])):
        if path not in set(declared["new_paths"]) and not _regular_git_blob(
            repository, base, path
        ):
            reasons.append(f"EXISTING_PATH_MISSING:{path}")
    for path in declared["new_paths"]:
        if _git(repository, "cat-file", "-e", f"{base}:{path}"):
            reasons.append(f"NEW_PATH_ALREADY_EXISTS:{path}")
    if reasons:
        raise ValueError(",".join(sorted(set(reasons))))
    encoded = json.dumps(contract, separators=(",", ":"), sort_keys=True,
                         ensure_ascii=False).encode("utf-8")
    criteria = json.dumps(acceptance_criteria, separators=(",", ":"),
                          ensure_ascii=False).encode("utf-8")
    return {
        "base_commit": base, "target_ref": target_ref,
        "queue_contract_sha256": hashlib.sha256(encoded).hexdigest(),
        "acceptance_sha256": hashlib.sha256(criteria).hexdigest(),
        "planning_sha256": planning_hashes,
    }


def contract_shape_reasons(contract: Mapping[str, Any]) -> tuple[str, ...]:
    """Pure registration-time checks; Git and Registry facts are checked again at claim."""
    if contract.get("schema_version") != 2:
        return ()
    declared = contract.get("readiness")
    if not isinstance(declared, Mapping):
        return ("READINESS_CONTRACT_MISSING",)
    reasons: list[str] = []
    if not isinstance(declared.get("base_commit"), str) or not _SHA.fullmatch(declared["base_commit"]):
        reasons.append("BASE_COMMIT_INVALID")
    names = ("planning_paths", "existing_paths", "new_paths", "integration_paths", "test_paths")
    lists = {}
    for name in names:
        value = declared.get(name)
        if (not isinstance(value, list) or (name in {"planning_paths", "integration_paths", "test_paths"} and not value)
                or any(not _safe_path(path) for path in value)
                or len(value) != len(set(value))):
            reasons.append(f"{name.upper()}_INVALID")
            lists[name] = []
        else:
            lists[name] = value
    paths = contract.get("paths")
    existing = set(lists["existing_paths"])
    new = set(lists["new_paths"])
    if (not isinstance(paths, list) or any(not _safe_path(path) for path in paths)
            or len(paths) != len(set(paths)) or not (existing | new)
            or set(paths) != existing | new or existing & new):
        reasons.append("PATH_DECLARATION_MISMATCH")
    if not set(lists["integration_paths"] + lists["test_paths"]).issubset(existing | new):
        reasons.append("INTEGRATION_OR_TEST_UNOWNED")
    dependencies = contract.get("depends_on")
    expected = ({f"TASK-{item}" if str(item).isdigit() else str(item) for item in dependencies}
                if isinstance(dependencies, list) else None)
    kinds = declared.get("dependency_kinds")
    if (expected is None or not isinstance(kinds, Mapping) or set(kinds) != expected
            or any(value not in _KINDS for value in kinds.values())):
        reasons.append("DEPENDENCY_KIND_MISMATCH")
    return tuple(sorted(set(reasons)))


def check_packet(
    contract: Mapping[str, Any], *, repository: pathlib.Path | None,
    run_base: str, package: Mapping[str, Any], snapshot: Any,
    github_issue: int | None,
) -> Readiness:
    """Check exact source, base tree, paths, tests and active path ownership."""
    if contract.get("schema_version") != 2:
        return Readiness("NEEDS_PREPARATION", ("LEGACY_SPARSE_CONTRACT",))
    reasons: list[str] = []
    if (package.get("source_system") != "github_issue"
            or not str(package.get("source_ref") or "").isdigit()
            or github_issue != int(package["source_ref"])):
        reasons.append("SOURCE_BINDING_MISMATCH")
    declared = contract.get("readiness")
    if not isinstance(declared, Mapping):
        return Readiness("BLOCKED", tuple(sorted(reasons + ["READINESS_CONTRACT_MISSING"])))
    base_commit = declared.get("base_commit")
    if not isinstance(base_commit, str) or not _SHA.fullmatch(base_commit):
        reasons.append("BASE_COMMIT_INVALID")
        base_commit = None
    if repository is None or not repository.is_dir() or not _git(repository, "rev-parse", "--is-inside-work-tree"):
        reasons.append("REPOSITORY_UNAVAILABLE")
    elif base_commit is not None:
        if not _git(repository, "cat-file", "-e", f"{base_commit}^{{commit}}"):
            reasons.append("BASE_COMMIT_MISSING")
        elif _git_commit(repository, run_base) != base_commit:
            # A mutable branch may advance after run activation. The packet
            # names one exact tree, not merely an ancestor of current main.
            reasons.append("BASE_REF_CHANGED")
    names = ("planning_paths", "existing_paths", "new_paths", "integration_paths", "test_paths")
    path_lists: dict[str, list[str]] = {}
    required_nonempty = {"planning_paths", "integration_paths", "test_paths"}
    for name in names:
        value = declared.get(name)
        if (not isinstance(value, list) or (name in required_nonempty and not value)
                or any(not _safe_path(path) for path in value)
                or len(value) != len(set(value))):
            reasons.append(f"{name.upper()}_INVALID")
            path_lists[name] = []
        else:
            path_lists[name] = value
    existing = set(path_lists["existing_paths"])
    new = set(path_lists["new_paths"])
    paths = contract.get("paths")
    if (not isinstance(paths, list) or any(not _safe_path(path) for path in paths)
            or len(paths) != len(set(paths)) or not (existing | new)
            or set(paths) != existing | new or existing & new):
        reasons.append("PATH_DECLARATION_MISMATCH")
        paths = []
    if not set(path_lists["integration_paths"] + path_lists["test_paths"]).issubset(existing | new):
        reasons.append("INTEGRATION_OR_TEST_UNOWNED")
    if repository is not None and base_commit is not None and _git(repository, "cat-file", "-e", f"{base_commit}^{{commit}}"):
        for path in sorted(existing | set(path_lists["planning_paths"])
                           | set(path_lists["integration_paths"])
                           | set(path_lists["test_paths"])):
            if path in new:
                continue
            if not _git(repository, "cat-file", "-e", f"{base_commit}:{path}"):
                reasons.append(f"EXISTING_PATH_MISSING:{path}")
        for path in sorted(new):
            if _git(repository, "cat-file", "-e", f"{base_commit}:{path}"):
                reasons.append(f"NEW_PATH_ALREADY_EXISTS:{path}")
    kinds = declared.get("dependency_kinds")
    dependencies = contract.get("depends_on", ())
    expected_dependencies = ({f"TASK-{value}" if str(value).isdigit() else str(value)
                              for value in dependencies}
                             if isinstance(dependencies, (list, tuple)) else set())
    if (not isinstance(kinds, Mapping) or set(kinds) != expected_dependencies
            or any(value not in _KINDS for value in kinds.values())):
        reasons.append("DEPENDENCY_KIND_MISMATCH")
    registry_dependencies = {str(edge["dependency_id"]) for edge in snapshot.dependencies
                             if edge["package_id"] == package.get("id")}
    if registry_dependencies != expected_dependencies:
        reasons.append("DEPENDENCY_REGISTRY_MISMATCH")
    by_id = {str(item.get("id")): item for item in snapshot.work_packages}
    for dependency_id in sorted(expected_dependencies):
        dependency = by_id.get(dependency_id)
        if dependency is None:
            reasons.append(f"DEPENDENCY_MISSING:{dependency_id}")
        elif dependency.get("status") != "DONE" and not (
            package.get("kind") == "REVIEW" and dependency.get("status") == "VERIFY_REVIEW"
        ):
            reasons.append(f"DEPENDENCY_UNMET:{dependency_id}")
    active = {str(lease.get("package_id")) for lease in snapshot.active_leases}
    for other in snapshot.work_packages:
        if other.get("id") == package.get("id") or other.get("id") not in active:
            continue
        other_paths = (other.get("provider_diagnostics") or {}).get("exclusive_paths")
        if not isinstance(other_paths, list):
            reasons.append(f"ACTIVE_PATH_OWNERSHIP_UNKNOWN:{other.get('id')}")
        elif set(paths or ()) & set(other_paths):
            reasons.append(f"EXCLUSIVE_PATH_COLLISION:{other.get('id')}")
    if contract.get("schema_version") == 2:
        diagnostics = package.get("provider_diagnostics") or {}
        proof = diagnostics.get("readiness_proof") if isinstance(diagnostics, Mapping) else None
        if not isinstance(proof, Mapping):
            reasons.append("REGISTRATION_PROOF_MISSING")
        elif (repository is not None
              and _git_commit(repository, str(proof.get("target_ref")))
              != _git_commit(repository, run_base)):
            reasons.append("REGISTRATION_TARGET_REF_MISMATCH")
        elif repository is not None:
            try:
                actual_proof = registration_proof(
                    contract, repository=repository,
                    target_ref=str(proof.get("target_ref")),
                    acceptance_criteria=tuple(package.get("acceptance_criteria") or ()),
                )
            except (ValueError, OSError, subprocess.TimeoutExpired) as error:
                reasons.append(f"REGISTRATION_PROOF_INVALID:{error}")
            else:
                if dict(proof) != actual_proof:
                    reasons.append("REGISTRATION_PROOF_CHANGED")
    return Readiness("READY" if not reasons else "BLOCKED", tuple(sorted(set(reasons))), base_commit)


def inventory(snapshot: Any, *, outcomes=(), evidence=()) -> list[dict[str, Any]]:
    """Non-destructive queue inventory; never infer integration from DONE."""
    latest_outcome = {}
    for outcome in sorted(outcomes, key=lambda item: (item["decided_at"], item["id"])):
        latest_outcome[outcome["target_package_id"]] = outcome
    integrated = {item["package_id"] for item in evidence
                  if item["kind"] == "integration-acceptance"}
    by_id = {str(item.get("id")): item for item in snapshot.work_packages}
    items = []
    for package in snapshot.work_packages:
        status = str(package.get("status"))
        diagnostics = package.get("provider_diagnostics") or {}
        dependencies = [edge["dependency_id"] for edge in snapshot.dependencies
                        if edge["package_id"] == package.get("id")]
        blocked_dependencies = [item for item in dependencies
                                if by_id.get(item, {}).get("status") != "DONE"]
        last_review = latest_outcome.get(package.get("id"))
        if diagnostics.get("superseded_by") in by_id:
            group = "SUPERSEDED_WITH_LINEAGE"
        elif package.get("id") in integrated and status == "DONE":
            group = "RECORDED_INTEGRATION_EVIDENCE_UNVERIFIED"
        elif last_review is not None and last_review["state"] == "CHANGES_REQUESTED":
            group = "CHANGES_REQUESTED"
        elif last_review is not None and last_review["state"] == "APPROVED":
            group = "APPROVED_INTEGRATION_UNVERIFIED"
        elif diagnostics.get("device_gate") is True:
            group = "PHYSICAL_DEVICE_GATE"
        elif blocked_dependencies:
            group = "BLOCKED_DEPENDENCY"
        elif status == "BLOCKED":
            group = "BLOCKED"
        elif status == "VERIFY_REVIEW":
            group = "AWAITING_REVIEW_OR_INTEGRATION"
        elif status == "DONE":
            group = "RECORDED_DONE_INTEGRATION_UNVERIFIED"
        elif status in {"READY", "ACTIVE"} and diagnostics.get("readiness_schema_version") == 2:
            group = "CANDIDATE_REQUIRES_LIVE_CHECK"
        elif status in {"READY", "ACTIVE"}:
            group = "NEEDS_PREPARATION"
        else:
            group = "ON_DECK_OR_UNKNOWN"
        items.append({"id": package.get("id"), "status": status, "group": group,
                      "source_ref": package.get("source_ref"),
                      "dependencies": dependencies, "blocked_dependencies": blocked_dependencies,
                      "review_outcome_id": last_review["id"] if last_review else None})
    return items


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only Factory queue inventory")
    parser.add_argument("--database", type=pathlib.Path, required=True)
    args = parser.parse_args()
    from scripts.factory_registry.sqlite_registry import SQLiteRegistry
    registry = SQLiteRegistry(args.database)
    snapshot = registry.dispatch_snapshot(observed_at=datetime.now(timezone.utc).isoformat())
    with sqlite3.connect(args.database.as_uri() + "?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        outcomes = [dict(item) for item in connection.execute(
            "SELECT id,target_package_id,state,decided_at FROM review_outcomes"
        )]
        evidence = [dict(item) for item in connection.execute(
            "SELECT package_id,kind FROM evidence WHERE kind='integration-acceptance'"
        )]
    if registry.dispatch_control()["revision"] != snapshot.revision:
        raise SystemExit("Registry changed while collecting inventory; retry")
    print(json.dumps({"revision": snapshot.revision,
                      "items": inventory(snapshot, outcomes=outcomes, evidence=evidence)}, indent=2))


if __name__ == "__main__":
    main()
