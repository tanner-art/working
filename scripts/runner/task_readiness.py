"""Read-only, versioned pre-provider checks for complete Factory packets.

Legacy packets are reported as needing preparation; they are not retroactively
invalidated. Version 2 packets opt in to a complete, fail-closed contract.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
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
        elif not _git(repository, "merge-base", "--is-ancestor", base_commit, run_base):
            # A packet may start from this exact commit or an immutable
            # descendant, but never from an unrelated planning tree.
            reasons.append("BASE_NOT_IN_RUN_LINEAGE")
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
    return Readiness("READY" if not reasons else "BLOCKED", tuple(sorted(set(reasons))), base_commit)


def inventory(snapshot: Any) -> list[dict[str, Any]]:
    """Non-destructive queue inventory; never infer integration from DONE."""
    items = []
    for package in snapshot.work_packages:
        status = str(package.get("status"))
        diagnostics = package.get("provider_diagnostics") or {}
        if status == "BLOCKED":
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
                      "dependencies": [edge["dependency_id"] for edge in snapshot.dependencies
                                       if edge["package_id"] == package.get("id")]})
    return items


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only Factory queue inventory")
    parser.add_argument("--database", type=pathlib.Path, required=True)
    args = parser.parse_args()
    from scripts.factory_registry.sqlite_registry import SQLiteRegistry
    snapshot = SQLiteRegistry(args.database).dispatch_snapshot(observed_at=datetime.now(timezone.utc).isoformat())
    print(json.dumps({"revision": snapshot.revision, "items": inventory(snapshot)}, indent=2))


if __name__ == "__main__":
    main()
