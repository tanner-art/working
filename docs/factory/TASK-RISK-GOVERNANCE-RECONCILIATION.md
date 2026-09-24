# RISK-003 — Factory governance reconciliation

Status: implemented on `codex/risk-governance-reconciliation`; awaiting independent review before push

Lane: ASSURANCE

## Objective

Reconcile the active task ledger, decision log, and architecture documentation with the system merged on `main` through `e62afe89b8cb7b16094447fcd4a66d3325ccae69` (PR #152), without changing product behavior or Factory authority.

## Bounded scope

This package may change only:

- `TASKS.md`;
- `docs/ARCHITECTURE.md`;
- `docs/DECISIONS.md`; and
- this task/evidence note.

It must not modify application or Factory code, live configuration, persisted state, branches, worktrees, queues, services, leases, or dashboards. It must not enable cutover, restart, launch, claim, merge, or push.

## Reconciliation evidence

The baseline is the first-parent `origin/main` history at `e62afe8`:

- PRs #75–83 shipped the first Calendar Week/Day and subsequent canvas slices that the September 22 task log still called “next”.
- PR #143 consolidated beta-readiness foundations.
- PR #144 added provider-controlled child review lanes to the installed runner.
- PR #145 updated the hosted build-dashboard projection.
- PR #150 added the preservation importer, backend-neutral registry boundary, SQLite/WAL adapter, lease invariants, lane playbooks, and shadow criteria.
- PR #151 added pure capability shadow dispatch with no live or mutation authority.
- PR #152 added the read-only live-observation adapter and immutable evidence boundary.

The merged code and Factory documents show that the installed runner remains the live dispatch authority. The registry, shadow scheduler, and observer are foundations only; no controlled restart or canary has granted them live authority.

## Documentation drift found

1. `TASKS.md` stopped at September 22, still presented already-merged PR #75–83 work as future work, and used time-sensitive runner statements as current state.
2. `docs/DECISIONS.md` contained no record of the Factory registry boundary, central lease/cap authority, capability-based dispatch, preservation/shadow cutover gates, or risk ordering.
3. `docs/ARCHITECTURE.md` described only the product semantic architecture. Its statement that product database and service topology remain undecided could be misread as covering the separate Factory SQLite migration adapter.
4. Merged implementation enforced material behavior that had operational documentation but no canonical decision record: transactional activation and the three-parent cap; provider-neutral eligibility; fail-closed usage and the Orchestra reserve; preservation-only import; no-side-effect shadow comparison; read-only dashboard projection; and independent review before cutover.

## Code behavior and decision status

The material invariants in item 4 are now recorded in D-012 through D-014. The dispatch ordering rule is recorded in D-015.

The earlier 70/80 fallback behavior was superseded by the owner-ratified staged
capacity policy in [CAPACITY_POLICY.md](CAPACITY_POLICY.md). Source mappings and
freshness values remain explicit configuration; missing percentage scopes stay
constrained, provider-signal workers require observed health, and the 20%
Orchestra reserve remains authoritative.

The registry also reserves normalized failure codes, while [REGISTRY.md](REGISTRY.md) explicitly defers their transition rules and telemetry integration. Proposed follow-up: define and review that bounded failure-policy package before live cutover relies on the taxonomy. It does not block this documentation reconciliation, but the reserved list must not be represented as a complete enforced failure policy.

## Disposition

- The stale product sequence is retained as a dated historical plan and annotated with shipped slices rather than deleted.
- Current main milestones and authority boundaries are added to the task ledger.
- D-012 through D-015 record the accepted Factory decisions without changing their behavior.
- OD-008 through OD-011 make remaining owner choices visible in the canonical decision log and link back to the more detailed [owner approval ledger](OWNER_APPROVALS.md).
- The architecture now separates the engineering Factory control plane from Threadline's product data architecture and distinguishes current live authority from the post-cutover target.

## Dispatch rule

**A known production-relevant risk with a small, bounded remediation outranks speculative platform expansion.**

This rule prioritizes already-scoped packages. It does not let an agent create scope, override dependencies, or bypass an owner decision.

## Acceptance evidence

- [x] Historical task and status statements are preserved with dates and reconciled annotations.
- [x] Current main milestones through PR #152 are represented.
- [x] Factory decisions are appended; D-001 through D-011 and OD-003 through OD-007 are unchanged.
- [x] Product architecture and Factory control-plane architecture are explicitly separated.
- [x] The installed runner remains documented as current live authority.
- [x] Owner-pending policy is not presented as approved live-dispatch policy.
- [x] No product or Factory implementation file is changed.
- [ ] Independent ASSURANCE review approves the diff.
- [ ] Push occurs only after that review.

## Owner decisions still required

The unresolved decisions are OD-008 through OD-011 in [DECISIONS.md](../DECISIONS.md), with operational detail in [OWNER_APPROVALS.md](OWNER_APPROVALS.md):

- exact registry cutover moment, archive visibility, and retention periods;
- dashboard administrators and their write permissions;
- initial worker capability/lane configuration and any change to main-merge authority; and
- provider/account capacity-scope mapping, reserve interpretation, economy eligibility, and live freshness thresholds.

## Validation record

Validation completed before commit:

- all local Markdown targets in the four changed files resolve;
- `git diff --check` passes;
- the changed-path scope is limited to the four files named above;
- all 59 Factory registry, shadow-dispatch, and live-observation tests pass; and
- `pnpm run check` passes: 52 test files / 649 tests, the production build, and the API TypeScript check. The build retains its existing advisory that one minified chunk exceeds 500 kB.

The complete diff was inspected before commit. Record the resulting commit SHA in the reviewer handoff; do not push it until independent review.
