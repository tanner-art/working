# TASK-161 independent review — A5 review-stage live enable gate

Status: independent ASSURANCE review of a merged change. This document records
review findings only; it does not authorize cutover, restart, launch, claim,
merge, or push, and no product or Factory code was changed to produce it.

## What was reviewed

Per the worktree's git history at review time, TASK-161 corresponds to:

- Implementation commit `af06c7b` — "Fix A5 review-stage live enable gate"
  (branch `codex/a5-review-resume-fix`).
- Merged to `main` via PR #164 (merge commit `b390060`), following PR #160
  (`codex/task-a5-ops-001`, merge `5a6746d`) and its own hardening commits
  `e5b8bac` and `4778b6d`.

## Reviewer tooling limitation

This session had no `git`/shell or GitHub access — only file read/search
tools. The exact PR diff stat, PR description text, and CI/runner log output
for PR #164 could not be independently pulled and inspected line-by-line.
The findings below are therefore based on reading the current merged state of
the affected files and their test coverage, not on a line-by-line diff or a
re-run of the test suite. This is a material limitation on the "exact path
scope" and "successful runner validation" evidence requested for this review
and should be closed by a reviewer with `git log -p` / CI-log access before
this is treated as a complete independent verification.

## What the change does (read from current code)

The fix addresses resuming the A5 canary's live-enable worker gate after the
implementation package has already succeeded and moved to `VERIFY_REVIEW`,
with its paired `REVIEW` package `READY` (`scripts/factory_registry/operator.py`
`_worker_gate`, ~line 1341–1392). In that resumed state:

- The implementer is no longer taken from current worker eligibility
  (`decision.pair_evaluations` against the `PARENT` package, which is stale
  once that package has left `READY`). Instead it is looked up deterministically
  from the actual successful attempt history via the new
  `SQLiteRegistry.review_implementer_worker` (`scripts/factory_registry/sqlite_registry.py:1650-1675`):
  the review package's single declared dependency, then the most recent
  `SUCCEEDED` attempt on that dependency, ordered `ended_at DESC, started_at DESC, id DESC`
  as an explicit deterministic tie-break. Missing provenance raises
  `REGISTRY_CONFLICT: REVIEW_IMPLEMENTER_PROVENANCE_REQUIRED` rather than
  guessing.
- Reviewer eligibility is then restricted to workers who are both currently
  eligible for the review package (`review_pairs`) and independent of that
  specific implementer, so a worker who is generically "eligible" but was not
  the actual implementer cannot be miscounted as the implementer, and the
  actual implementer cannot be selected as their own reviewer.
- The same deterministic lookup is enforced a second time at actual claim
  time in `scripts/runner/registry_control.py` (`pre_claim`, ~line 116-122):
  claiming a `REVIEW` package raises `REVIEW_INDEPENDENCE_REQUIRED` if the
  claiming worker matches `review_implementer_worker`. This gives the
  resume-stage gate two independent enforcement points (operator preflight
  and runner pre-claim) rather than relying on the operator check alone.

## Path scope observed

All code touched by this behavior is confined to the Factory control-plane
lane, not Threadline product code:

- `scripts/factory_registry/operator.py` (`_worker_gate`, `preflight`, `enable_live`)
- `scripts/factory_registry/sqlite_registry.py` (`review_implementer_worker`)
- `scripts/factory_registry/repository.py` (protocol method declaration)
- `scripts/runner/registry_control.py` (`pre_claim` independence check)
- `scripts/factory_registry/test_operator.py` /
  `scripts/runner/test_registry_control.py` (test coverage)

No file under `src/` (Threadline product code) references
`review_implementer_worker` or the resume-stage gate. This is consistent with
[ARCHITECTURE.md](../ARCHITECTURE.md)'s statement that the Factory control
plane is separate from Threadline's product semantic architecture, and with
no product-behavior change being in scope for an A5 canary-gate fix.

## Deterministic evidence content

`review_implementer_worker`'s SQL query is deterministic by construction: it
requires exactly one dependency row for the review package (raising
`REVIEW_TARGET_MISMATCH` otherwise) and selects the single most recent
`SUCCEEDED` attempt with an explicit, fully-ordered tie-break
(`ended_at DESC, started_at DESC, id DESC LIMIT 1`), so repeated evaluation of
the same Registry state cannot return different implementers. This matches
the deterministic-reconciliation expectation D-014 sets for evidence that
gates live authority.

## Test coverage found

`scripts/factory_registry/test_operator.py` includes tests that exercise this
exact resume path:

- `test_enable_live_resumes_ready_review_from_verify_review` — drives a
  canary through implementation success into `VERIFY_REVIEW`/`READY`, then
  calls `enable_live` and asserts the resulting `worker_gate.independent_pairs`
  is exactly `[["codex-a", "claude"]]` and dispatch mode reaches `LIVE`.
- `test_worker_gate_preserves_review_separation_during_resume` — gives the
  implementer (`codex-a`) reviewer-shaped capabilities/lane too, and asserts
  `preflight` still raises `"reviewer is not independent"` rather than
  treating the implementer as their own reviewer.
- `test_worker_gate_preserves_review_package_gates_during_resume` — pushes the
  review package's `ready_at` into the future and asserts `preflight` raises
  `"no eligible independent reviewer"`, i.e. package-level readiness gates are
  still enforced during resume.
- `test_review_outcome_is_bound_to_reviewer_attempt_and_evidence` exercises
  `review_implementer_worker` directly against a real attempt history.

These tests read as covering the specific defect class (resume-time reviewer
independence and package-gate bypass) rather than only the happy path.
`scripts/runner/test_registry_control.py` was not read line-by-line in this
review; its presence in the touched-file list above was confirmed but its
assertions were not individually inspected.

## Successful runner validation

Not independently reproduced in this session (see tooling limitation above).
No CI log, `pnpm`/`pytest` run output, or PR evidence artifact for PR #164 was
found committed anywhere in the repository tree (unlike, for example,
RISK-003's inline "Validation record" in
[TASK-RISK-GOVERNANCE-RECONCILIATION.md](TASK-RISK-GOVERNANCE-RECONCILIATION.md)).
This review cannot confirm from repository contents alone that the runner's
automated checks passed for this specific PR; that must come from GitHub
CI status or the runner's own logs, which this session could not query.

## Absence of product-behavior changes

Confirmed by path scope: every file exercising the new logic is under
`scripts/factory_registry/` or `scripts/runner/`. No Threadline product file
(`src/**`) was found referencing the changed functions, and the change is
gated behind the still-unactivated A5 controlled-restart procedure
(`docs/factory/CONTROLLED_RESTART.md`), which continues to state the
installed runner remains the live dispatch authority and that this wiring
requires independent ASSURANCE approval and an owner-approved canary before
any restart. Nothing reviewed here grants that authority.

## Findings

1. **No evidence artifact for TASK-161 exists in the repository.** Unlike
   RISK-003, no `docs/factory/*.md` evidence note documents PR #164's scope,
   validation commands run, or acceptance criteria for TASK-161/TASK-160.
   Proposed follow-up: an ASSURANCE-lane task to add a short evidence note
   for merged A5 gate-hardening PRs (#160, #164) so future review does not
   depend on live GitHub/CI access. This does not block the current review
   and is not implemented here — it is out of this task's scope.
2. **This review could not independently execute the test suite or read
   CI results** due to the tools available in this session (file
   read/search only, no shell or GitHub access). The code-level review above
   is consistent with a correct, deterministic, narrowly-scoped fix, but a
   reviewer with `git`/CI access should confirm the actual PR #164 diff
   matches exactly the files listed above and that its CI run was green,
   before this is relied on as a complete independent sign-off.

## Verdict

Based on the current merged code and its dedicated tests, the A5
review-stage live-enable resume fix (TASK-161) appears correctly scoped to
Factory control-plane code, deterministic in its evidence source, and
directly tested against the reviewer-independence and package-gate defects
it targets, with no observable product-behavior change. This is a
**conditional pass**: the conclusion is sound on the evidence obtainable in
this session, but full independent verification of exact PR diff scope and
CI/runner validation status is outstanding and should be completed by a
reviewer with git/CI access per finding 2 above.
