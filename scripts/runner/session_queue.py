"""Deterministic ordering over assignments already eligible in the Registry."""

from __future__ import annotations


def ordered_assignments(snapshot, assignments):
    """Prefer a ready independent review without changing Registry eligibility.

    This policy only orders assignments emitted by ``decide_shadow``. It never
    promotes blocked/dependency-waiting work or preempts an active lease.
    """
    packages = {item.get("id"): item for item in getattr(snapshot, "work_packages", ())}

    def key(assignment):
        package = packages.get(assignment.package_id, {})
        ready_review = package.get("kind") == "REVIEW" and package.get("status") == "READY"
        return (0 if ready_review else 1, -int(package.get("priority", 0)),
                str(assignment.package_id), str(assignment.worker_id))

    return tuple(sorted(assignments, key=key))


def ordered_assignments_for_worker(snapshot, assignments, worker_id):
    """Order only the work that competes for one worker's next slot.

    A review assigned to another worker is not a reason to hold this worker's
    independent implementation.  Keeping this filter here makes that
    ownership boundary explicit for controller callers.
    """
    return tuple(
        assignment for assignment in ordered_assignments(snapshot, assignments)
        if assignment.worker_id == worker_id
    )
