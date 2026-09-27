# Continuous Factory session

An approved bounded session has an immutable allowlist and a distinct active
parent WIP limit. The allowlist can contain more independently reviewed pairs
than can run simultaneously; the Registry remains the authority for leases,
deadlines, capacity, paths, reviewer independence, and the kill switch.

At an idle boundary, a READY independent review is ordered before an eligible
parent. Waiting and BLOCKED packages remain in their recorded state: they are
not promoted to make a session appear runnable. Activation may retain a
dependency-waiting pair only when a capable implementer and an independent
capable reviewer are registered for that exact pair.

Between lease claim and provider launch, the runner may revalidate once after a
revision race only if dispatch is still LIVE, the run deadline remains valid,
the same package/worker lease remains active, the package remains ACTIVE, and
no attempt exists. A stop, kill switch, deadline, lease ownership change, or
existing attempt fails closed.
