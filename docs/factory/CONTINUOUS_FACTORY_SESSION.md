# Continuous Factory queue

The Registry is the persistent work queue. The opt-in `enable-continuous`
operator starts a LIVE dispatch generation without an immutable package
allowlist or a queue-item deadline. A READY package with a valid GitHub source
binding can be proposed when its dependencies, worker capability, capacity,
path ownership, and review-independence gates pass. Unbound READY records stay
visible in the Registry but are not runner proposals or direct lease targets.
Individual leases and provider attempts still have timeouts. The kill switch
and lifecycle operators retain authority over every claim.

Bounded runs remain available for canaries. Their allowlist, deadline, and
parent limit continue to apply only when that mode is selected. Switching
modes requires the normal drained, PAUSED lifecycle and an immutable installed
release; active attempts are never hot-reloaded.

One worker may hold only one active lease. A submitted parent in
`VERIFY_REVIEW` is reviewer-owned waiting work and does not consume the
builder's active coding slot. Active parent leases still count toward the
builder WIP guard and the global active-parent limit. Review-ready work is
ordered before new coding at an idle boundary; running attempts are never
preempted. A review request for changes is not, by itself, authority to
create work. In the opt-in correction loop, one or two same-scope correction
and review pairs must already have been registered while PAUSED and drained.
Only an exact structured rejection releases its linked next pair, to the
original author at their next idle boundary. The old verdict and draft remain
in history; a third rejected draft blocks for owner decision. Without those
pre-authorized slots, legacy review behavior is unchanged.

Between lease claim and provider launch, the runner may revalidate once
after a revision race only while dispatch remains LIVE, the same lease is
active, the package and worker remain eligible, capacity/path checks pass,
and no attempt exists. In bounded mode the original run identity, scope, and
deadline must also remain unchanged. Any failed condition closes the claim.
