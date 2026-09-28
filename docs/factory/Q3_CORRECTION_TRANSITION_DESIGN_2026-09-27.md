# Q3 correction activation — opt-in implementation awaiting independent review

The first proposed code change was rejected because it would have granted every review outcome broad authority to change any ON_DECK package to READY. The replacement implementation is opt-in and only activates the exact pre-registered correction pair linked to the verified review outcome. It is not installed in the live Factory; no live Registry state was touched.

A narrower design requires a dedicated, opt-in correction transition whose guard proves all of the following within one Registry writer transaction:

1. An exact structured `CHANGES_REQUESTED` review outcome has passed the existing implementer, reviewer, commit, base, contract and evidence checks. Its idempotency receipt is new, not a replay with a different request.
2. The correction package and its paired review are registered while PAUSED and drained, after the first implementation establishes its original author but before the review run begins. Both have unique GitHub source references, normalized contract digests, immutable original root/feature/path/acceptance fingerprints, ordinal slot 1 or 2 and original-author identity.
3. Both package IDs are inside the exact current bounded-run allowlist. The correction is the unique unused slot linked to this specific review package and root. A malformed, duplicate, mismatched or out-of-scope slot fails closed rather than being activated.
4. Only that correction pair transitions ON_DECK to READY, while the reviewed target transitions VERIFY_REVIEW to BLOCKED with the exact outcome and reason recorded. The old review remains DONE with its append-only verdict. A missing slot yields NEEDS_SCOPE; a third request is marked EXHAUSTED. Neither condition creates work.
5. At claim time only the original author can take the correction, and the existing capacity, path, WIP, deadline, kill, lease and pre-provider checks remain binding. An active attempt is never preempted.

Tests must exercise the normal registration, review-outcome, shadow decision, controller and lease paths against disposable Registry state, including replay, mismatched source/author/scope and exhausted slots. A broad global lifecycle permission is not acceptable. Independent review is required before merge/install.

`register-review-corrections` accepts a spec with `target_package_id`, the exact
`original_contract`, and one or two `slots`. Each slot has an `implementation`
and `review` object in the same format as bounded-pilot packages, each with a
`queue_contract` and a distinct `source_ref` for an existing GitHub issue.
The correction implementation contract retains the original owned paths and
acceptance criteria. The review contract depends on its paired implementation
issue. Slots remain `ON_DECK` until the predecessor's structured rejection.
No reviewer prose can create a package or change its contract.

The runner starts a correction from the assigned base and exposes the exact
rejected commit, PR and structured findings to the original author. It opens a
new cumulative PR for that draft; the predecessor PR remains preserved and
must not be merged independently after supersession. Normal checks and exact
commit independent review still apply. After a third rejected draft the item
is `BLOCKED` for owner decision, with no automatic fourth attempt.
