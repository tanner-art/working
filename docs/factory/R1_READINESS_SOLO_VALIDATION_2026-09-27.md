# R1 pre-provider task readiness (solo implementation)

Version-2 queue contracts opt in to a fail-closed read-only check at the actual runner pre-claim boundary. The check compares the normalized contract digest already stored by the operator, the exact GitHub issue binding, explicit base commit and run lineage, planning and existing integration/test files in that Git tree, declared new paths, dependency kinds and Registry edges, and active exclusive-path ownership. No provider is started on a failed check.

Legacy sparse packets are classified `NEEDS_PREPARATION` by the checker rather than retroactively invalidated. The read-only inventory command is `python3 -m scripts.runner.task_readiness --database <disposable-or-authoritative-registry-path>`; it reports status groups without changing history or treating `DONE` or a recorded evidence label as integration proof.

The version-2 readiness object contains `base_commit`, `planning_paths`, `existing_paths`, `new_paths`, `integration_paths`, `test_paths`, and `dependency_kinds`. `paths` must be the disjoint union of existing and new paths. `depends_on` identifiers are GitHub issue numbers, resolved to `TASK-<number>` for Registry edge comparison. Semantic completeness and release acceptance still require independent judgment.

Validation: `python3 -m unittest discover -s scripts/runner` includes disposable Git-tree and real SQLite Registry pre-claim/claim tests. Full Registry tests and `pnpm check` are required before review. No live Registry state is changed by this implementation.
