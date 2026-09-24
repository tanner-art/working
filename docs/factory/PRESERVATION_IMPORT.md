# Preservation import

## Purpose

The preservation importer records pre-migration reality without repairing, renaming, rebasing, cleaning, consolidating, or deleting it. The source snapshot remains immutable evidence.

## Safety properties

- Reads one JSON snapshot and verifies its SHA-256 digest.
- Writes only to a newly selected registry database.
- Rejects a database target equal to the snapshot or located inside the canonical repository or any preserved worktree, including resolved symlink aliases.
- Checks the source bytes again after import.
- Stores the complete source JSON and digest.
- Imports worktrees and branches as preserved artifacts.
- Imports legacy workers as diagnostic records with no approved lane or capabilities.
- Imports legacy tasks with their source issue identity and visible status.
- Assigns no lane to imported work, preventing accidental claims.
- Re-importing the same digest is a no-op.
- Rejects duplicate or malformed task and artifact identities instead of silently omitting them.
- Does not run Git, GitHub, service, or filesystem mutation commands.

## Command

```bash
python3 -m scripts.factory_registry.preservation_import \
  --snapshot /absolute/path/to/snapshot.json \
  --database /absolute/path/to/new-registry.sqlite3
```

The command does not make the resulting database live. A separate reconciliation report and explicit cutover are required.

## Reconciliation requirements

Before live-state migration, compare:

- source snapshot digest;
- canonical and remote commit identities;
- every worktree path and dirty flag;
- every unmerged branch;
- every open task, issue, commit, and pull request;
- every known worker and heartbeat;
- every usage observation with its observation time;
- counts of imported artifacts and unexplained source records.

Any unexplained omission blocks scheduler cutover.
