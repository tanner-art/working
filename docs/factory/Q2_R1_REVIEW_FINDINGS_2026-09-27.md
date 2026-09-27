# Q2/R1 exact-commit review findings — 2026-09-27

Claude independently reviewed PR #352 at implementation commit
`163296706cdcec4d97b2366621d8df53223393b6` and returned
`CHANGES_REQUESTED`. This verdict is preserved; it is not an approval.

The reviewer found two functional gaps:

1. Ready-review ordering happened after the scheduler had already assigned one
   package per worker. It could not prioritize a review competing with an
   implementation for the same idle worker. The mocked controller test assumed
   two assignments to one worker, which the real scheduler never emits.
2. A direct Registry lease caller under a retained bounded run could omit the
   expected revision and claim while dispatch was no longer LIVE or the kill
   switch was engaged.

The follow-up changes move ready-review priority into the scheduler's pair
ordering, retain emergency-recovery precedence, remove the ineffective
post-scheduling queue check, and require LIVE dispatch with kill switch off
for direct bounded-run claims. Real scheduler/controller and direct-claim tests
cover those cases. The new exact head still requires a fresh independent
review and passing CI before it can be treated as approved.
