"""Deterministic bounded-session assignment ordering.

This is intentionally a tiny policy layer over the Registry's eligibility
decision.  It never makes blocked work READY and never preempts a lease.
"""

from __future__ import annotations


def ordered_assignments(snapshot, assignments):
    """Return currently eligible assignments in coherent session order.

    Ready reviews win at an idle boundary.  An activated remediation package
    can name its original author in immutable diagnostics and wins next for
    that author; all other eligible work follows the Registry's stable order.
    """
    packages = {item.get("id"): item for item in getattr(snapshot, "work_packages", ())}

    def key(assignment):
        package_id = assignment.package_id
        worker_id = assignment.worker_id
        package = packages.get(package_id, {})
        diagnostics = package.get("provider_diagnostics", {})
        original = diagnostics.get("original_author_worker_id")
        review_ready = package.get("kind") == "REVIEW" and package.get("status") == "READY"
        remediation = bool(diagnostics.get("remediation_slot")) and original == worker_id
        # The remaining terms make ties independent of provider iteration.
        return (0 if review_ready else 1, 0 if remediation else 1,
                package.get("priority", 0), str(package_id), str(worker_id))

    return tuple(sorted(assignments, key=key))
