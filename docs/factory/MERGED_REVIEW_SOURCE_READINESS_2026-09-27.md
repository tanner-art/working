# Merged Review Source Readiness — 2026-09-27

## Observed mismatch

TASK-296's immutable ReviewInput records implementation commit
`22e7ec1db487a598554154d838cae832535c98a8` from PR #292, based on
`4310b83`. PR #292 was merged, which advanced its GitHub `headRefOid` to
`1789bec...`. The previous runner gate accepted only a PR whose current head
exactly equalled the recorded implementation commit. It therefore deferred the
otherwise complete review packet as `REVIEW_SOURCE_OR_CI_NOT_GREEN`, despite
the merged tree matching the reviewed PR source and the canonical main CI
succeeding for the exact merge commit.

## Repair and boundary

The original exact-PR-head path remains valid and still requires the PR's
passing `verify` checks. A separate merged path is fail-closed. It requires:

- PR state `MERGED` and `mergeCommit.oid` exactly equal to the immutable
  `implementation_commit`;
- the original PR's passing required `verify` checks;
- a successful completed `Validate app` workflow on `main` whose `headSha` is
  exactly that merge commit; and
- GitHub Git tree IDs for the original PR head and merge commit to be equal.

Missing, malformed, or failed GitHub observations defer review. The repair does
not accept a changed tree, an open PR, an arbitrary commit, a matching commit
message, or inferred CI. It does not change the TASK-296 ReviewInput or write
to the Registry.

## Rollback

Revert the merged-source branch in `review_source_is_green` while retaining the
existing exact-PR-head and PR-`verify` logic. This restores the prior conservative
behavior: merged review inputs defer until their PR head exactly matches the
recorded implementation commit again. No Registry data migration or cleanup is
needed because the repair reads GitHub only.
