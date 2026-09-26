"""Central lifecycle policy for authoritative Factory state changes.

Storage adapters and runners may perform a transition only through one of the
named authorities below.  This keeps status vocabulary small while preventing
callers from inventing locally-valid but globally-impossible transitions.
"""

from __future__ import annotations

from enum import Enum

from .models import TaskStatus
from .repository import RegistryConflict


class TransitionAuthority(str, Enum):
    DIRECT = "DIRECT"
    LEASE_ACQUIRE = "LEASE_ACQUIRE"
    LEASE_RELEASE = "LEASE_RELEASE"
    ATTEMPT_FINISH = "ATTEMPT_FINISH"
    REVIEW_OUTCOME = "REVIEW_OUTCOME"
    RECOVERY = "RECOVERY"


LEGAL_DISPATCH_TRANSITIONS = {
    "PAUSED": frozenset({"LIVE", "STOPPING"}),
    "LIVE": frozenset({"STOPPING"}),
    "STOPPING": frozenset({"PAUSED", "RECOVERY_REQUIRED"}),
    "RECOVERY_REQUIRED": frozenset({"PAUSED", "STOPPING"}),
}


_PACKAGE_TRANSITIONS = {
    TransitionAuthority.DIRECT: {
        (TaskStatus.ON_DECK, TaskStatus.READY),
        (TaskStatus.ON_DECK, TaskStatus.BLOCKED),
        (TaskStatus.READY, TaskStatus.ON_DECK),
        (TaskStatus.READY, TaskStatus.BLOCKED),
        (TaskStatus.VERIFY_REVIEW, TaskStatus.READY),
        (TaskStatus.VERIFY_REVIEW, TaskStatus.BLOCKED),
        (TaskStatus.BLOCKED, TaskStatus.READY),
        (TaskStatus.BLOCKED, TaskStatus.ON_DECK),
    },
    TransitionAuthority.LEASE_ACQUIRE: {
        (TaskStatus.READY, TaskStatus.ACTIVE),
    },
    TransitionAuthority.LEASE_RELEASE: {
        (TaskStatus.ACTIVE, TaskStatus.READY),
        (TaskStatus.ACTIVE, TaskStatus.BLOCKED),
        (TaskStatus.ACTIVE, TaskStatus.VERIFY_REVIEW),
    },
    TransitionAuthority.ATTEMPT_FINISH: {
        (TaskStatus.ACTIVE, TaskStatus.READY),
        (TaskStatus.ACTIVE, TaskStatus.BLOCKED),
        (TaskStatus.ACTIVE, TaskStatus.VERIFY_REVIEW),
    },
    TransitionAuthority.REVIEW_OUTCOME: {
        (TaskStatus.VERIFY_REVIEW, TaskStatus.DONE),
    },
    TransitionAuthority.RECOVERY: {
        (TaskStatus.ACTIVE, TaskStatus.BLOCKED),
        (TaskStatus.READY, TaskStatus.BLOCKED),
        (TaskStatus.VERIFY_REVIEW, TaskStatus.BLOCKED),
    },
}


_ATTEMPT_RESULTS = {
    "SUCCEEDED": frozenset({TaskStatus.VERIFY_REVIEW}),
    "FAILED": frozenset({TaskStatus.BLOCKED}),
    "BLOCKED": frozenset({TaskStatus.BLOCKED}),
    "CANCELLED": frozenset({TaskStatus.BLOCKED, TaskStatus.READY}),
}


def validate_dispatch_transition(current: str, target: str) -> None:
    if current not in LEGAL_DISPATCH_TRANSITIONS:
        raise RegistryConflict("INVALID_DISPATCH_MODE", current)
    if target not in LEGAL_DISPATCH_TRANSITIONS[current]:
        raise RegistryConflict("INVALID_DISPATCH_TRANSITION", f"{current}->{target}")


def validate_package_transition(
    current: TaskStatus,
    target: TaskStatus,
    *,
    authority: TransitionAuthority,
) -> None:
    if (current, target) not in _PACKAGE_TRANSITIONS[authority]:
        raise RegistryConflict(
            "INVALID_PACKAGE_TRANSITION",
            f"{authority.value}:{current.value}->{target.value}",
        )


def validate_attempt_completion(outcome: str, target: TaskStatus) -> None:
    allowed = _ATTEMPT_RESULTS.get(outcome)
    if allowed is None:
        raise RegistryConflict("INVALID_ATTEMPT_OUTCOME", outcome)
    if target not in allowed:
        raise RegistryConflict("ATTEMPT_OUTCOME_STATUS_MISMATCH")
    validate_package_transition(
        TaskStatus.ACTIVE,
        target,
        authority=TransitionAuthority.ATTEMPT_FINISH,
    )
