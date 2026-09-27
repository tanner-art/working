"""Strict, provider-neutral protocol for independent Factory reviews."""
from __future__ import annotations
import hashlib
import json
import re
from typing import Any, Mapping
from scripts.factory_registry.models import ReviewInput, ReviewOutcomeState, ReviewVerdict
_SHA = re.compile(r"^[0-9a-f]{40,64}$")
REVIEW_VERDICT_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["state", "reviewed_commit", "reviewed_base_commit", "contract_sha256", "findings", "changes_requested"],
    "properties": {
        "state": {"type": "string", "enum": ["APPROVED", "CHANGES_REQUESTED"]},
        "reviewed_commit": {"type": "string", "pattern": "^[0-9a-f]{40,64}$"},
        "reviewed_base_commit": {"type": "string", "pattern": "^[0-9a-f]{40,64}$"},
        "contract_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "findings": {"type": "array", "items": {"type": "string"}},
        "changes_requested": {"type": "array", "items": {"type": "string"}},
    },
}
class ReviewProtocolError(ValueError):
    """The review was blocked, missing required input, or not parseable."""


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ReviewProtocolError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _load_json(value, *, message):
    try:
        return json.loads(value, object_pairs_hook=_unique_object)
    except (TypeError, json.JSONDecodeError) as error:
        raise ReviewProtocolError(message) from error


def _codex_structured_output(value):
    """Extract one successful final agent message from a Codex JSONL stream.

    ``codex exec --json`` deliberately emits progress records as well as its
    final message.  Progress, a clean process exit, or an error record cannot
    stand in for a review verdict.
    """
    if not isinstance(value, str):
        raise ReviewProtocolError("Codex review output is unparseable")
    events = [_load_json(line, message="Codex review event is unparseable")
              for line in value.splitlines() if line.strip()]
    if not events or not all(isinstance(event, Mapping) for event in events):
        raise ReviewProtocolError("Codex review event is invalid")
    failed_types = {"error", "turn.failed", "turn.cancelled"}
    if any(event.get("type") in failed_types
           or str(event.get("type", "")).endswith(".error")
           for event in events):
        raise ReviewProtocolError("Codex review provider result was not successful")
    messages = [event["item"]["text"] for event in events
                if event.get("type") == "item.completed"
                and isinstance(event.get("item"), Mapping)
                and event["item"].get("type") == "agent_message"
                and isinstance(event["item"].get("text"), str)]
    terminals = [event for event in events if event.get("type") == "turn.completed"]
    if (len(messages) != 1 or len(terminals) != 1
            or events[-1] is not terminals[0]
            or terminals[0].get("status") not in (None, "completed", "success")):
        raise ReviewProtocolError("Codex review output lacks one successful final verdict")
    return _load_json(messages[0], message="Codex structured output is not verdict JSON")
def contract_digest(contract: Mapping[str, Any]) -> str:
    if not isinstance(contract, Mapping): raise ReviewProtocolError("review contract must be an object")
    return hashlib.sha256(json.dumps(dict(contract), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()
def validate_review_input(value: ReviewInput) -> ReviewInput:
    required = {"id": value.id, "review_package_id": value.review_package_id, "target_package_id": value.target_package_id, "implementation_attempt_id": value.implementation_attempt_id, "pr_url": value.pr_url, "contract_sha256": value.contract_sha256, "recorded_at": value.recorded_at}
    if any(not isinstance(item, str) or not item for item in required.values()): raise ReviewProtocolError("review input fields are required")
    if not _SHA.fullmatch(value.implementation_commit) or not _SHA.fullmatch(value.base_commit): raise ReviewProtocolError("implementation commits must be exact SHAs")
    if not re.fullmatch(r"[0-9a-f]{64}", value.contract_sha256): raise ReviewProtocolError("contract sha256 is invalid")
    if contract_digest(value.contract) != value.contract_sha256: raise ReviewProtocolError("review contract digest does not match")
    if not isinstance(value.validation_evidence, Mapping) or not value.validation_evidence: raise ReviewProtocolError("review validation evidence is required")
    return value
def review_handoff(value: ReviewInput, *, reviewer_worker_id: str, review_attempt_id: str) -> str:
    validate_review_input(value)
    if not reviewer_worker_id or not review_attempt_id: raise ReviewProtocolError("reviewer and review attempt are required")
    expected_verdict_identity = {
        "reviewed_commit": value.implementation_commit,
        "reviewed_base_commit": value.base_commit,
        "contract_sha256": value.contract_sha256,
    }
    return json.dumps({"review_input_id": value.id, "target_package_id": value.target_package_id, "implementation_attempt_id": value.implementation_attempt_id, "implementation_commit": value.implementation_commit, "base_commit": value.base_commit, "pr_url": value.pr_url, "contract_sha256": value.contract_sha256, "expected_verdict_identity": expected_verdict_identity, "contract": dict(value.contract), "validation_evidence": dict(value.validation_evidence), "reviewer_worker_id": reviewer_worker_id, "review_attempt_id": review_attempt_id}, sort_keys=True, indent=2, ensure_ascii=False)
def parse_review_verdict(output: str, review_input: ReviewInput, *,
                         provider: str | None = None) -> ReviewVerdict:
    validate_review_input(review_input)
    # A configured provider is an input-integrity boundary.  In particular,
    # Codex's JSONL transcript must never fall back to accepting a convenient
    # bare JSON object or a Claude-shaped envelope.
    if provider == "openai":
        raw = _codex_structured_output(output)
    elif provider == "anthropic":
        raw = _load_json(output, message="review verdict is unparseable")
    elif provider is None:
        # Explicit legacy/API compatibility only.  The production caller
        # supplies provider identity and therefore never takes this branch.
        try:
            raw = _load_json(output, message="review verdict is unparseable")
        except ReviewProtocolError:
            raw = _codex_structured_output(output)
    else:
        raise ReviewProtocolError("review provider is unsupported")
    # Claude's JSON mode wraps the model result.  Only accept its documented,
    # successful result envelope; accepting arbitrary wrappers would make an
    # error payload or a transcript look like a review decision.
    if isinstance(raw, Mapping) and "type" in raw:
        if (raw.get("type") != "result" or raw.get("is_error") is not False
                or raw.get("subtype") not in (None, "success")
                or "error" in raw):
            raise ReviewProtocolError("review provider result was not successful")
        if "structured_output" in raw:
            # Claude --json-schema owns this field. Its human result prose is
            # never searched, stripped of fences, or converted into a verdict.
            raw = raw["structured_output"]
            if not isinstance(raw, Mapping):
                raise ReviewProtocolError("review structured output is not verdict JSON")
        else:
            result = raw.get("result")
            if not isinstance(result, str):
                raise ReviewProtocolError("review provider result is not verdict JSON")
            raw = _load_json(result, message="review provider result is not verdict JSON")
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
