"""Import a read-only preservation snapshot into a new registry database."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from .repository import RegistryConflict
from .sqlite_registry import SQLiteRegistry


def _is_within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _validate_database_target(snapshot: dict, snapshot_path: Path, database_path: Path) -> None:
    source = snapshot_path.resolve(strict=False)
    target = database_path.resolve(strict=False)
    if target == source:
        raise RegistryConflict("UNSAFE_IMPORT_TARGET", "database equals preservation source")
    protected_roots = []
    for worktree in snapshot.get("worktrees", []):
        if isinstance(worktree, dict) and worktree.get("worktree"):
            protected_roots.append(Path(str(worktree["worktree"])).resolve(strict=False))
    canonical = snapshot.get("canonical_repository", {})
    if not isinstance(canonical, dict) or not canonical.get("path"):
        raise RegistryConflict(
            "INVALID_PRESERVATION_SNAPSHOT", "canonical_repository.path required"
        )
    canonical_path = Path(str(canonical["path"]))
    if not canonical_path.is_absolute():
        raise RegistryConflict(
            "INVALID_PRESERVATION_SNAPSHOT", "canonical_repository.path must be absolute"
        )
    protected_roots.append(canonical_path.resolve(strict=False))
    for root in protected_roots:
        if _is_within(target, root):
            raise RegistryConflict("UNSAFE_IMPORT_TARGET", f"database is inside preserved root {root}")


def import_snapshot(snapshot_path: Path, database_path: Path) -> bool:
    before = snapshot_path.read_bytes()
    digest = hashlib.sha256(before).hexdigest()
    snapshot = json.loads(before)
    if not isinstance(snapshot, dict):
        raise RegistryConflict("INVALID_PRESERVATION_SNAPSHOT", "top level must be an object")
    _validate_database_target(snapshot, snapshot_path, database_path)
    registry = SQLiteRegistry(database_path)
    registry.initialize()
    imported = registry.import_preservation_snapshot(
        snapshot,
        source_uri=str(snapshot_path.resolve()),
        source_sha256=digest,
        imported_at=datetime.now(timezone.utc).isoformat(),
    )
    if snapshot_path.read_bytes() != before:
        raise RuntimeError("preservation source changed during import")
    return imported


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Import a Threadline Factory preservation snapshot without modifying its source"
    )
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--database", required=True, type=Path)
    args = parser.parse_args()
    imported = import_snapshot(args.snapshot, args.database)
    print("imported" if imported else "already imported")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
