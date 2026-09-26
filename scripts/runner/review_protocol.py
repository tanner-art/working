"""Strict, provider-neutral protocol for independent Factory reviews."""
from __future__ import annotations
import hashlib
import json
import re
from typing import Any, Mapping
from scripts.factory_registry.models import ReviewInput, ReviewOutcomeState, ReviewVerdict
_SHA = re.compile(r"^[0-9a-f]{40,64}$")
class ReviewProtocolError(ValueError):
    """The review was blocked, missing required input, or not parseable."""
def contract_digest(contract: Mapping[str, Any]) -> str:
    if not isinstance(contract, Mapping): raise ReviewProtocolError("review contract must be an object")
    return hashlib.sha256(json.dumps(dict(contract), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()
def validate_review_input(value: ReviewInput) -> ReviewInput:
    required = {"id": value.id, "review_package_id": value.review_package_id, "target_package_id": value.target_package_id, "implementation_attempt_id": value.implementation_attempt_id, "pr_url": value.pr_url, "contract_sha256": value.contract_sha256, "recorded_at": value.recorded_at}
    if any(not isinstance(item, str) or not item for item in required.values()): raise ReviewProtocolError("review input fields are required")
    if not _SHA.fullmatch(value.implementation_commit): raise ReviewProtocolError("implementation commit must be an exact SHA")
    if not _SHA.fullmatch(value.base_commit): raise ReviewProtocolError("base commit must be an exact SHA")
    if not re.fullmatch(r"[0-9a-f]{64}", value.contract_sha256): raise ReviewProtocolError("contract sha256 is invalid")
    if contract_digest(value.contract) != value.contract_sha256: raise ReviewProtocolError("review contract digest does not match")
    if not isinstance(value.validation_evidence, Mapping) or not value.validation_evidence: raise ReviewProtocolError("review validation evidence is required")
    return value
def review_handoff(value: ReviewInput, *, reviewer_worker_id: str, review_attempt_id: str) -> str:
    validate_review_input(value)
    if not reviewer_worker_id or not review_attempt_id: raise ReviewProtocolError("reviewer and review attempt are required")
    return json.dumps({"review_input_id": value.id, "target_package_id": value.target_package_id, "implementation_attempt_id": value.implementation_attempt_id, "implementation_commit": value.implementation_commit, "base_commit": value.base_commit, "pr_url": value.pr_url, "contract_sha256": value.contract_sha256, "contract": dict(value.contract), "validation_evidence": dict(value.validation_evidence), "reviewer_worker_id": reviewer_worker_id, "review_attempt_id": review_attempt_id}, sort_keys=True, indent=2)
def parse_review_verdict(output: str, review_input: ReviewInput) -> ReviewVerdict:
    validate_review_input(review_input)
    try: raw = json.loads(output)
    except (TypeError, json.JSONDecodeError) as error: raise ReviewProtocolError("review verdict is unparseable") from error
    if not isinstance(raw, Mapping) or set(raw) != {"state", "reviewed_commit", "reviewed_base_commit", "contract_sha256", "findings", "changes_requested"}: raise ReviewProtocolError("review verdict schema is invalid")
    try: state = ReviewOutcomeState(raw["state"])
    except (KeyError, ValueError) as error: raise ReviewProtocolError("review verdict state is invalid") from error
    findings, changes_requested = raw["findings"], raw["changes_requested"]
    if not isinstance(findings, list) or not isinstance(changes_requested, list) or not all(isinstance(item, str) and item for item in findings + changes_requested): raise ReviewProtocolError("review verdict findings are invalid")
    verdict = ReviewVerdict(state=state, reviewed_commit=raw["reviewed_commit"], reviewed_base_commit=raw["reviewed_base_commit"], contract_sha256=raw["contract_sha256"], findings=tuple(findings), changes_requested=tuple(changes_requested))
    if verdict.reviewed_commit != review_input.implementation_commit or verdict.reviewed_base_commit != review_input.base_commit or verdict.contract_sha256 != review_input.contract_sha256: raise ReviewProtocolError("review verdict targets different implementation input")
    if verdict.state is ReviewOutcomeState.APPROVED and verdict.changes_requested: raise ReviewProtocolError("approved verdict cannot request changes")
    if verdict.state is ReviewOutcomeState.CHANGES_REQUESTED and not verdict.changes_requested: raise ReviewProtocolError("changes-requested verdict requires requested changes")
    return verdict
