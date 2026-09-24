# Factory registry foundation work package

## Scope

Create the first reviewable Factory migration unit without changing live dispatch or preserved work:

- a read-only preservation importer;
- a backend-neutral registry API and schema;
- a SQLite/WAL migration adapter;
- FEATURE, PLATFORM, and ASSURANCE lane playbook skeletons;
- shadow-dispatch acceptance criteria;
- a list of product-owner assumptions.

## Lane

PLATFORM: orchestration infrastructure.

## Allowed files

- `scripts/factory_registry/**`
- `docs/factory/**`
- `docs/lanes/**`

## Acceptance criteria

- Importing a preservation snapshot cannot modify its source.
- Re-importing the same snapshot is idempotent.
- Registry callers depend on a storage protocol rather than SQLite APIs.
- Provider/model information is diagnostic metadata only.
- The central registry enforces one active lease per package, one per worker, and no more than three active parent packages.
- Claims enforce dependencies, approved lane, and required capabilities.
- Task events are append-only.
- Imported legacy work receives no capability lane automatically.
- Lane playbooks include the required startup and completion checks.
- Shadow dispatch launches no work and has measurable acceptance criteria.
- No existing worktree, branch, task, service, or dashboard is changed.

## Exclusions

- Live-state cutover.
- Scheduler selection and dispatch.
- Dashboard changes.
- Worker restarts.
- Product feature development.
- Merging to `main`.
