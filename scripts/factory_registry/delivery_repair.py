"""Carry rejected implementation code into a clean correction worktree.

The coordinator supplies a Registry-bound rejection and exact path ownership.
This adapter reads the previous immutable commits, applies their binary diff to
the current integration base, and leaves staged changes for the implementation
worker. It never commits, changes branches, pushes, or edits historical objects.
Conflict worktrees remain intact for reconciliation and diagnostic evidence.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Mapping, Sequence


class CorrectionError(RuntimeError):
    def __init__(self, code: str, evidence: Mapping[str, Any] | None = None):
        super().__init__(code)
        self.code = code
        self.evidence = dict(evidence or {})


_SHA = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
_PATH = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_./-]*")
_BINDING_FIELDS = {"previous_package_id", "review_id", "outcome_id", "implementation_commit",
                   "base_commit", "paths", "changes_requested"}
_MAX_PATCH_BYTES = 16 * 1024 * 1024


def _git(repo: Path, *args: str, input_bytes: bytes | None = None) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            ["git", "--no-replace-objects", "-c", "core.hooksPath=/dev/null", "-C", str(repo), *args],
            input=input_bytes, capture_output=True, check=False, timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise CorrectionError("REPAIR_GIT_UNAVAILABLE", {"operation": args[0], "error": str(error)}) from error


def _read(repo: Path, *args: str) -> bytes:
    result = _git(repo, *args)
    if result.returncode:
        raise CorrectionError("REPAIR_GIT_READ_FAILED", {
            "operation": args[0], "stderr": result.stderr.decode("utf-8", errors="replace")[-4000:],
        })
    return result.stdout


def _paths(value: Any, label: str) -> tuple[str, ...]:
    if (not isinstance(value, (list, tuple)) or not value or len(value) > 100
            or any(not isinstance(path, str) or not _PATH.fullmatch(path)
                   or any(part in {"", ".", ".."} or part.startswith(".") for part in path.split("/"))
                   for path in value)
            or len(set(value)) != len(value)):
        raise CorrectionError("REPAIR_PATHS_INVALID", {"field": label})
    return tuple(value)


def _exact_commit(repo: Path, value: Any) -> str:
    if not isinstance(value, str) or not _SHA.fullmatch(value):
        raise CorrectionError("REPAIR_EXACT_COMMIT_REQUIRED")
    actual = _read(repo, "rev-parse", "--verify", value + "^{commit}").decode().strip()
    if actual != value:
        raise CorrectionError("REPAIR_EXACT_COMMIT_REQUIRED")
    return actual


def _tree_modes(repo: Path, commit: str) -> dict[str, str]:
    result = {}
    for entry in _read(repo, "ls-tree", "-r", "-t", "-z", commit).split(b"\0"):
        if entry:
            metadata, path = entry.split(b"\t", 1)
            result[path.decode("utf-8")] = metadata.split(b" ", 1)[0].decode()
    return result


def _safe_tree_paths(repo: Path, commit: str, paths: tuple[str, ...]) -> None:
    modes = _tree_modes(repo, commit)
    for path in paths:
        parts = path.split("/")
        for length in range(1, len(parts)):
            ancestor = "/".join(parts[:length])
            if ancestor in modes and modes[ancestor] != "040000":
                raise CorrectionError("REPAIR_UNSAFE_PATH_ANCESTOR", {"path": ancestor, "commit": commit})
        if path in modes and modes[path] not in {"100644", "100755"}:
            raise CorrectionError("REPAIR_NONREGULAR_PATH", {"path": path, "commit": commit})


def _working_tree_clean(repo: Path) -> None:
    # Ignored destinations are checked separately before apply; normal porcelain
    # must still show no tracked, staged, or untracked work.
    if _read(repo, "status", "--porcelain=v1", "--untracked-files=all").strip():
        raise CorrectionError("REPAIR_WORKTREE_NOT_CLEAN")


def _safe_worktree_destinations(repo: Path, paths: tuple[str, ...]) -> None:
    for path in paths:
        destination = repo / path
        for parent in (*destination.parents, destination):
            if parent == repo:
                continue
            if repo not in parent.parents:
                continue
            if parent.is_symlink():
                raise CorrectionError("REPAIR_UNSAFE_WORKTREE_PATH", {"path": str(parent.relative_to(repo))})
            if parent != destination and parent.exists() and not parent.is_dir():
                raise CorrectionError("REPAIR_UNSAFE_WORKTREE_PATH", {"path": str(parent.relative_to(repo))})
        tracked = _git(repo, "ls-files", "--error-unmatch", "--", path).returncode == 0
        if not tracked and (destination.exists() or destination.is_symlink()):
            raise CorrectionError("REPAIR_UNTRACKED_DESTINATION", {"path": path})


def materialize_correction(repository: str | Path, current_base_sha: str,
                           repair_binding: Mapping[str, Any], allowed_paths: Sequence[str]) -> dict[str, Any]:
    """Apply the rejected patch to an isolated current-base checkout, without commit.

    ``repair_binding`` is trusted Registry data with exactly the seven fields in
    ``_BINDING_FIELDS``. The checkout must be clean and detached or on a non-main
    branch. Replays against the now-dirty checkout fail; callers must checkpoint
    the returned evidence and reconcile interrupted attempts before retrying.
    """
    if not isinstance(repair_binding, Mapping) or set(repair_binding) != _BINDING_FIELDS:
        raise CorrectionError("REPAIR_BINDING_INVALID")
    binding = dict(repair_binding)
    for field in ("previous_package_id", "review_id"):
        if not isinstance(binding[field], str) or not re.fullmatch(r"TASK-[1-9][0-9]*", binding[field]):
            raise CorrectionError("REPAIR_BINDING_INVALID", {"field": field})
    if (binding["previous_package_id"] == binding["review_id"]
            or not isinstance(binding["outcome_id"], str) or not binding["outcome_id"].strip()
            or len(binding["outcome_id"]) > 200
            or not isinstance(binding["changes_requested"], (list, tuple)) or not binding["changes_requested"]
            or len(binding["changes_requested"]) > 100
            or any(not isinstance(item, str) or not item.strip() or len(item) > 12000
                   for item in binding["changes_requested"])):
        raise CorrectionError("REPAIR_REJECTION_REQUIRED")
    original_paths = _paths(binding["paths"], "repair_binding.paths")
    allowed = _paths(allowed_paths, "allowed_paths")
    repo = Path(repository).resolve()
    top = Path(_read(repo, "rev-parse", "--show-toplevel").decode().strip()).resolve()
    if repo != top:
        raise CorrectionError("REPAIR_WORKTREE_ROOT_REQUIRED")
    current = _exact_commit(repo, current_base_sha)
    previous = _exact_commit(repo, binding["implementation_commit"])
    base = _exact_commit(repo, binding["base_commit"])
    head = _read(repo, "rev-parse", "HEAD").decode().strip()
    if head != current:
        raise CorrectionError("REPAIR_CURRENT_BASE_MISMATCH")
    branch = _git(repo, "symbolic-ref", "--quiet", "--short", "HEAD")
    if branch.returncode not in {0, 1}:
        raise CorrectionError("REPAIR_BRANCH_UNAVAILABLE")
    if branch.returncode == 0 and branch.stdout.decode().strip() in {"main", "master"}:
        raise CorrectionError("REPAIR_MAIN_CHECKOUT_FORBIDDEN")
    parents = _read(repo, "rev-list", "--parents", "-n", "1", previous).decode().split()
    if parents[1:] != [base]:
        raise CorrectionError("REPAIR_IMPLEMENTATION_PARENT_MISMATCH")
    ancestry = _git(repo, "merge-base", "--is-ancestor", base, current)
    if ancestry.returncode != 0:
        raise CorrectionError("REPAIR_BASE_NOT_IN_CURRENT_LINEAGE")
    already_integrated = _git(repo, "merge-base", "--is-ancestor", previous, current)
    if already_integrated.returncode not in {0, 1}:
        raise CorrectionError("REPAIR_ANCESTRY_UNAVAILABLE")
    if already_integrated.returncode == 0:
        raise CorrectionError("REPAIR_IMPLEMENTATION_ALREADY_INTEGRATED")
    _working_tree_clean(repo)
    try:
        changed = tuple(path.decode("utf-8") for path in
                        _read(repo, "diff", "--no-ext-diff", "--no-textconv", "--name-only", "--no-renames", "-z", base, previous, "--").split(b"\0") if path)
    except UnicodeDecodeError as error:
        raise CorrectionError("REPAIR_PATHS_INVALID") from error
    changed = _paths(changed, "implementation_diff")
    if not set(changed).issubset(original_paths) or not set(changed).issubset(allowed):
        raise CorrectionError("REPAIR_PATH_OWNERSHIP_MISMATCH", {"changed_paths": list(changed)})
    for commit in (base, previous, current):
        _safe_tree_paths(repo, commit, changed)
    _safe_worktree_destinations(repo, changed)
    patch = _read(repo, "diff", "--no-ext-diff", "--no-textconv", "--binary", "--full-index", "--no-renames", base, previous, "--")
    if not patch or len(patch) > _MAX_PATCH_BYTES:
        raise CorrectionError("REPAIR_PATCH_SIZE_INVALID")
    evidence = {
        "schema_version": 1, "kind": "factory-correction-materialization",
        "previous_package_id": binding["previous_package_id"], "review_id": binding["review_id"],
        "outcome_id": binding["outcome_id"], "implementation_commit": previous,
        "implementation_base": base, "current_base_commit": current,
        "applied_paths": list(changed), "changes_requested": list(binding["changes_requested"]),
        "patch_sha256": hashlib.sha256(patch).hexdigest(), "workspace": str(repo),
    }
    # The only mutation. Git retains unresolved index entries/conflict files on
    # failure; do not reset or clean them because they are recovery evidence.
    if _read(repo, "rev-parse", "HEAD").decode().strip() != current:
        raise CorrectionError("REPAIR_CURRENT_BASE_MISMATCH")
    _working_tree_clean(repo)
    result = _git(repo, "apply", "--3way", "--index", "--whitespace=nowarn", "-", input_bytes=patch)
    evidence.update(returncode=result.returncode,
                    stdout=result.stdout.decode("utf-8", errors="replace")[-4000:],
                    stderr=result.stderr.decode("utf-8", errors="replace")[-4000:])
    if result.returncode:
        evidence["conflicted_paths"] = [path.decode() for path in
                                       _read(repo, "diff", "--name-only", "--diff-filter=U", "-z").split(b"\0") if path]
        raise CorrectionError("REPAIR_APPLY_CONFLICT", evidence)
    if _read(repo, "rev-parse", "HEAD").decode().strip() != current:
        raise CorrectionError("REPAIR_HEAD_CHANGED", evidence)
    staged = tuple(path.decode() for path in _read(repo, "diff", "--cached", "--name-only", "-z").split(b"\0") if path)
    if not set(staged).issubset(changed):
        raise CorrectionError("REPAIR_APPLIED_PATH_MISMATCH", evidence)
    evidence["staged_paths"] = list(staged)
    evidence["state"] = "APPLIED"
    evidence["evidence_sha256"] = hashlib.sha256(json.dumps(evidence, sort_keys=True, separators=(",", ":"),
                                                          ensure_ascii=False).encode()).hexdigest()
    return evidence
