# Q3 correction activation — safety design, not implementation

The first proposed code change was rejected because it would have granted every review outcome broad authority to change any ON_DECK package to READY. No such lifecycle change was committed. Q3 remains unimplemented and no live Registry state was touched.

The names `NEEDS_SCOPE` and `EXHAUSTED`, original-author-only correction
assignment, and a two-attempt remediation budget below are conditional design
terms, not current Registry statuses, runner behavior, or approved TASK-353
behavior. Neither TASK-353 (`f36b7ced604dfe87635cf4789184d89a69894a60`) nor
the later PR #352 repairs implemented a correction transition.

A narrower design requires a dedicated, opt-in correction transition whose guard proves all of the following within one Registry writer transaction:

1. An exact structured `CHANGES_REQUESTED` review outcome has passed the existing implementer, reviewer, commit, base, contract and evidence checks. Its idempotency receipt is new, not a replay with a different request.
2. The correction package and its paired review were registered while PAUSED and drained, before the bounded run began. Both have unique GitHub source references, normalized contract digests, immutable original root/feature/path/acceptance fingerprints, ordinal slot 1 or 2 and original-author identity.
3. Both package IDs are inside the exact current bounded-run allowlist. The correction is the unique unused slot linked to this specific review package and root. A malformed, duplicate, mismatched or out-of-scope slot fails closed rather than being activated.
4. Only that correction pair transitions ON_DECK to READY, while the reviewed target transitions VERIFY_REVIEW to BLOCKED with the exact outcome and reason recorded. The old review remains DONE with its append-only verdict. A missing slot yields NEEDS_SCOPE; a third request is marked EXHAUSTED. Neither condition creates work.
5. At claim time only the original author can take the correction, and the existing capacity, path, WIP, deadline, kill, lease and pre-provider checks remain binding. An active attempt is never preempted.

Tests must exercise the normal registration, review-outcome, shadow decision, controller and lease paths against disposable Registry state, including replay, mismatched source/author/scope and exhausted slots. A broad global lifecycle permission is not acceptable. Independent review is required before merge/install.
