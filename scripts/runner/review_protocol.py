"""Strict, provider-neutral protocol for independent Factory reviews."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any


class ReviewProtocolError(ValueError):
    """The reviewer did not produce an authoritative structured verdict."""


class ReviewBlockedError(ReviewProtocolError):
    """The reviewer explicitly could not inspect the assigned target."""


@dataclass(frozen=True)
class StructuredReviewVerdict:
    decision: str
    findings: tuple[str, ...]
    changes_requested: tuple[str, ...]
    reviewed_commit: str
    review_input_evidence_id: str


def review_input_mapping(review_input: Any) -> dict[str, Any]:
    value = asdict(review_input)
    value["validation_evidence_ids"] = list(value["validation_evidence_ids"])
    value["contract_content"] = dict(value["contract_content"])
    return value


def build_review_prompt(issue_number: int, review_input: Any, packet_path: str) -> str:
    return f"""Independently review GitHub issue #{issue_number}.
The assigned worktree is detached at the exact implementation commit. Do not edit any file.
Read the complete immutable assignment at {packet_path}. It includes the target package,
implementation attempt and commit, base commit, PR, exact planning contract and hash,
validation evidence, reviewer identity, and this review attempt.

Return exactly one JSON object and no markdown or surrounding prose, with this schema:
{{"schema_version":1,"decision":"APPROVED|CHANGES_REQUESTED","findings":["..."],"changes_requested":["..."],"reviewed_commit":"{review_input.implementation_commit}","review_input_evidence_id":"{review_input.evidence_id}"}}

APPROVED requires an empty changes_requested array. CHANGES_REQUESTED requires at least one
specific code or contract change. If the commit, contract, evidence, workspace, or access is
missing or does not match, return exactly this separate non-verdict schema instead:
{{"schema_version":1,"attempt_outcome":"BLOCKED","detail":"exact blocker"}}
Never reconstruct the target from another worktree, branch, or unstated shell history.
"""


def parse_review_verdict(output: str, review_input: Any) -> StructuredReviewVerdict:
    try:
        value = json.loads(output)
    except (TypeError, json.JSONDecodeError) as error:
        raise ReviewProtocolError("review verdict is not one JSON object") from error
    if not isinstance(value, dict):
        raise ReviewProtocolError("review verdict must be a JSON object")
    if set(value) == {"schema_version", "attempt_outcome", "detail"}:
        if (
            value.get("schema_version") == 1
            and value.get("attempt_outcome") == "BLOCKED"
            and isinstance(value.get("detail"), str)
            and value["detail"].strip()
        ):
            raise ReviewBlockedError(value["detail"].strip())
        raise ReviewProtocolError("blocked review outcome schema is invalid")
    expected_keys = {
        "schema_version", "decision", "findings", "changes_requested",
        "reviewed_commit", "review_input_evidence_id",
    }
    if set(value) != expected_keys or value.get("schema_version") != 1:
        raise ReviewProtocolError("review verdict schema is invalid")
    decision = value.get("decision")
    if decision not in {"APPROVED", "CHANGES_REQUESTED"}:
        raise ReviewProtocolError("review decision is invalid")
    findings = _string_list(value.get("findings"), "findings")
    changes = _string_list(value.get("changes_requested"), "changes_requested")
    if decision == "APPROVED" and changes:
        raise ReviewProtocolError("approved review cannot request changes")
    if decision == "CHANGES_REQUESTED" and not changes:
        raise ReviewProtocolError("changes-requested review requires a specific change")
    if value.get("reviewed_commit") != review_input.implementation_commit:
        raise ReviewProtocolError("review verdict targets the wrong commit")
    if value.get("review_input_evidence_id") != review_input.evidence_id:
        raise ReviewProtocolError("review verdict targets the wrong review input")
    return StructuredReviewVerdict(
        decision=decision,
        findings=findings,
        changes_requested=changes,
        reviewed_commit=value["reviewed_commit"],
        review_input_evidence_id=value["review_input_evidence_id"],
    )


def _string_list(value: Any, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise ReviewProtocolError(f"{field} must be an array of non-empty strings")
    return tuple(item.strip() for item in value)
