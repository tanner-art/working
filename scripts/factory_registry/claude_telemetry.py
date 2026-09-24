"""Privacy-bounded parsers for Claude Code structured usage observations.

The parsers inspect prompts and responses only as needed to identify explicit
provider limit errors. They never copy ordinary message content into Registry
records.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .models import UsageLedgerEntry, UsageSource


class ClaudeTelemetryError(ValueError):
    """Structured Claude output cannot be ingested without guessing."""


_LIMIT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "RATE_LIMIT",
        re.compile(r"(?:rate[- ]?limit|too many requests|\b429\b)", re.IGNORECASE),
    ),
    (
        "EXHAUSTION",
        re.compile(
            r"(?:usage|subscription|quota|credit)s? (?:limit |quota )?"
            r"(?:reached|exceeded|exhausted)|(?:quota|credits?) exhausted",
            re.IGNORECASE,
        ),
    ),
    (
        "THROTTLING",
        re.compile(r"\bthrottl(?:e|ed|ing)\b", re.IGNORECASE),
    ),
)


def _source_identity(kind: str, raw: bytes) -> str:
    return f"claude:{kind}:sha256:{hashlib.sha256(raw).hexdigest()}"


def _timestamp(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise ClaudeTelemetryError("a timezone-aware observation timestamp is required")
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as error:
        raise ClaudeTelemetryError("invalid observation timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ClaudeTelemetryError("observation timestamp must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _number(mapping: Mapping[str, Any], key: str, *, integer: bool = True) -> int | float | None:
    value = mapping.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise ClaudeTelemetryError(f"{key} must be a non-negative number or null")
    if integer:
        if int(value) != value:
            raise ClaudeTelemetryError(f"{key} must be an integer")
        return int(value)
    return float(value)


def classify_limit_signal(raw_error: str) -> str | None:
    """Return a signal only for an explicit provider limit/throttle phrase."""
    for signal, pattern in _LIMIT_PATTERNS:
        if pattern.search(raw_error):
            return signal
    return None


def _model_diagnostic(payload: Mapping[str, Any], explicit_model: str | None) -> str | None:
    if explicit_model:
        return explicit_model
    model_usage = payload.get("modelUsage")
    if isinstance(model_usage, Mapping) and model_usage:
        return ",".join(sorted(str(model) for model in model_usage))
    model = payload.get("model")
    return str(model) if isinstance(model, str) and model else None


def _reset_at(payload: Mapping[str, Any]) -> str | None:
    candidates: list[Any] = [payload.get("reset_at"), payload.get("resetAt")]
    error = payload.get("error")
    if isinstance(error, Mapping):
        candidates.extend((error.get("reset_at"), error.get("resetAt")))
    for value in candidates:
        if isinstance(value, str) and value:
            return _timestamp(value)
    return None


def _retry_metadata(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    metadata: dict[str, Any] = {}
    error = payload.get("error")
    mappings = [payload, error] if isinstance(error, Mapping) else [payload]
    for mapping in mappings:
        for key in ("retry_after", "retryAfter"):
            value = mapping.get(key)
            if isinstance(value, (int, float, str)) and not isinstance(value, bool):
                metadata["provider_retry_after"] = value
                return metadata
    return metadata


def _entry_id(provider: str, worker_id: str, account_id: str, invocation_id: str) -> str:
    return str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"factory-usage:{provider}:{worker_id}:{account_id}:{invocation_id}",
        )
    )


def parse_claude_json(
    raw: bytes,
    *,
    worker_id: str,
    account_id: str,
    observed_at: str,
    invocation_id: str | None = None,
    package_id: str | None = None,
    attempt_id: str | None = None,
    model: str | None = None,
    cli_version: str | None = None,
    task_completed: bool = False,
    review_completed: bool = False,
) -> UsageLedgerEntry:
    """Parse one ``claude -p --output-format json`` result."""
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ClaudeTelemetryError("Claude JSON output is not valid UTF-8 JSON") from error
    if not isinstance(payload, Mapping) or payload.get("type") != "result":
        raise ClaudeTelemetryError("Claude JSON output must be a result object")
    session_id = payload.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        raise ClaudeTelemetryError("Claude result has no session_id")
    invocation = invocation_id or session_id
    usage = payload.get("usage")
    if not isinstance(usage, Mapping):
        usage = {}
    raw_result = payload.get("result")
    result_text = raw_result if isinstance(raw_result, str) else ""
    error_value = payload.get("error")
    error_text = (
        error_value
        if isinstance(error_value, str)
        else json.dumps(error_value, separators=(",", ":"), sort_keys=True)
        if isinstance(error_value, Mapping)
        else ""
    )
    raw_error = "\n".join(part for part in (result_text, error_text) if part)
    api_status = payload.get("api_error_status")
    signal = (
        "RATE_LIMIT"
        if payload.get("is_error") and str(api_status) == "429"
        else classify_limit_signal(raw_error) if payload.get("is_error") else None
    )
    outcome = "LIMITED" if signal else "FAILED" if payload.get("is_error") else "SUCCEEDED"
    source_identity = _source_identity("cli-json", raw)
    model_usage = payload.get("modelUsage")
    models = sorted(str(key) for key in model_usage) if isinstance(model_usage, Mapping) else []
    structured_metadata = {
        key: payload.get(key)
        for key in (
            "duration_api_ms",
            "num_turns",
            "stop_reason",
            "total_cost_usd",
            "fast_mode_disabled_reason",
            "fast_mode_state",
            "queued_turn_count",
            "is_error",
        )
        if key in payload
    }
    usage_metadata = {
        str(key): value
        for key, value in usage.items()
        if key
        not in {
            "input_tokens",
            "output_tokens",
            "cache_read_input_tokens",
            "cache_creation_input_tokens",
        }
    }
    return UsageLedgerEntry(
        id=_entry_id("anthropic", worker_id, account_id, invocation),
        provider="anthropic",
        worker_id=worker_id,
        account_id=account_id,
        invocation_id=invocation,
        session_id=session_id,
        package_id=package_id,
        attempt_id=attempt_id,
        observed_at=_timestamp(observed_at),
        model_diagnostic=_model_diagnostic(payload, model),
        input_tokens=_number(usage, "input_tokens"),
        output_tokens=_number(usage, "output_tokens"),
        cache_read_input_tokens=_number(usage, "cache_read_input_tokens"),
        cache_creation_input_tokens=_number(usage, "cache_creation_input_tokens"),
        duration_ms=_number(payload, "duration_ms", integer=False),
        outcome=outcome,
        task_completed=task_completed,
        review_completed=review_completed,
        limit_signal=signal,
        limit_reset_at=_reset_at(payload),
        limit_raw_error=raw_error if signal else None,
        calibration_metadata=_retry_metadata(payload) if signal else {},
        source_type=UsageSource.CLI_JSON,
        source_identity=source_identity,
        source_metadata={
            "format": "json",
            "cli_version": cli_version,
            "result_uuid": payload.get("uuid"),
            "result_index": payload.get("result_index"),
            "subtype": payload.get("subtype"),
            "terminal_reason": payload.get("terminal_reason"),
            "api_error_status": payload.get("api_error_status"),
            "usage_fields": sorted(str(key) for key in usage),
            "model_usage_models": models,
            "result_metadata": structured_metadata,
            "usage_metadata": usage_metadata,
            "model_usage": model_usage if isinstance(model_usage, Mapping) else {},
            "permission_denial_count": (
                len(payload["permission_denials"])
                if isinstance(payload.get("permission_denials"), list)
                else None
            ),
            "subagent_stats": (
                payload["subagent_stats"]
                if isinstance(payload.get("subagent_stats"), Mapping)
                else {}
            ),
        },
    )


def _json_lines(raw: bytes) -> list[Mapping[str, Any]]:
    records: list[Mapping[str, Any]] = []
    for line_number, line in enumerate(raw.splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ClaudeTelemetryError(f"invalid JSONL record at line {line_number}") from error
        if not isinstance(record, Mapping):
            raise ClaudeTelemetryError(f"JSONL record {line_number} is not an object")
        records.append(record)
    if not records:
        raise ClaudeTelemetryError("structured Claude output is empty")
    return records


def parse_claude_stream_json(raw: bytes, **kwargs: Any) -> UsageLedgerEntry:
    """Parse ``stream-json``, preferring its final aggregate result record."""
    records = _json_lines(raw)
    result_records = [record for record in records if record.get("type") == "result"]
    if len(result_records) != 1:
        raise ClaudeTelemetryError("Claude stream must contain exactly one final result")
    result = dict(result_records[0])
    entry = parse_claude_json(
        json.dumps(result, separators=(",", ":"), sort_keys=True).encode(), **kwargs
    )
    return UsageLedgerEntry(
        **{
            **entry.__dict__,
            "source_type": UsageSource.CLI_STREAM_JSON,
            "source_identity": _source_identity("cli-stream-json", raw),
            "source_metadata": {
                **entry.source_metadata,
                "format": "stream-json",
                "record_count": len(records),
                "record_types": sorted(
                    {str(record.get("type")) for record in records if record.get("type")}
                ),
            },
        }
    )


def _sum_usage(records: Sequence[Mapping[str, Any]]) -> Mapping[str, int | None]:
    fields = (
        "input_tokens",
        "output_tokens",
        "cache_read_input_tokens",
        "cache_creation_input_tokens",
    )
    totals: dict[str, int | None] = {}
    for field in fields:
        values = [_number(record, field) for record in records]
        present = [int(value) for value in values if value is not None]
        totals[field] = sum(present) if present else None
    return totals


def _content_text(content: Any) -> Iterable[str]:
    if isinstance(content, str):
        yield content
    elif isinstance(content, list):
        for block in content:
            if isinstance(block, Mapping) and isinstance(block.get("text"), str):
                yield block["text"]


def parse_claude_transcript(
    path: Path,
    *,
    transcript_root: Path,
    worker_id: str,
    account_id: str,
    invocation_id: str | None = None,
    package_id: str | None = None,
    attempt_id: str | None = None,
    task_completed: bool = False,
    review_completed: bool = False,
) -> UsageLedgerEntry:
    """Aggregate one completed, verified Claude Code transcript session.

    Repeated assistant records sharing a provider message ID are one response;
    current Claude Code transcripts repeat identical usage on every content
    block, so counting each JSONL line would overstate consumption.
    """
    resolved_root = transcript_root.expanduser().resolve(strict=True)
    resolved_path = path.expanduser().resolve(strict=True)
    try:
        resolved_path.relative_to(resolved_root)
    except ValueError as error:
        raise ClaudeTelemetryError("transcript path is outside the verified root") from error
    if resolved_path.suffix != ".jsonl":
        raise ClaudeTelemetryError("Claude transcript must be a .jsonl file")
    raw = resolved_path.read_bytes()
    records = _json_lines(raw)
    terminal_records = [record for record in records if record.get("type") == "cost-state"]
    if len(terminal_records) != 1:
        raise ClaudeTelemetryError(
            "transcript must contain exactly one terminal cost-state record"
        )
    session_ids = {
        str(record["sessionId"])
        for record in records
        if isinstance(record.get("sessionId"), str) and record.get("sessionId")
    }
    if len(session_ids) != 1:
        raise ClaudeTelemetryError("transcript must contain exactly one sessionId")
    session_id = next(iter(session_ids))
    if resolved_path.stem != session_id:
        raise ClaudeTelemetryError("transcript filename does not match sessionId")
    assistants: dict[str, Mapping[str, Any]] = {}
    duplicate_count = 0
    limit_errors: list[str] = []
    models: set[str] = set()
    versions: set[str] = set()
    timestamps: list[str] = []
    for record in records:
        timestamp = record.get("timestamp")
        if isinstance(timestamp, str):
            timestamps.append(_timestamp(timestamp))
        version = record.get("version")
        if isinstance(version, str) and version:
            versions.add(version)
        if record.get("type") != "assistant":
            continue
        message = record.get("message")
        if not isinstance(message, Mapping):
            raise ClaudeTelemetryError("assistant transcript record has no message object")
        usage = message.get("usage")
        if not isinstance(usage, Mapping):
            continue
        identity = message.get("id") or record.get("uuid")
        if not isinstance(identity, str) or not identity:
            raise ClaudeTelemetryError("assistant usage record has no stable identity")
        model = message.get("model")
        if isinstance(model, str) and model:
            models.add(model)
        prior = assistants.get(identity)
        if prior is not None:
            if prior != usage:
                raise ClaudeTelemetryError("repeated assistant identity has conflicting usage")
            duplicate_count += 1
        else:
            assistants[identity] = usage
        if record.get("isApiErrorMessage") is True:
            for text in _content_text(message.get("content")):
                if classify_limit_signal(text):
                    limit_errors.append(text)
    if not assistants:
        raise ClaudeTelemetryError("transcript contains no assistant usage records")
    if not timestamps:
        raise ClaudeTelemetryError("transcript contains no timestamps")
    usage_totals = _sum_usage(list(assistants.values()))
    start = datetime.fromisoformat(min(timestamps).replace("Z", "+00:00"))
    end = datetime.fromisoformat(max(timestamps).replace("Z", "+00:00"))
    raw_error = "\n".join(limit_errors) if limit_errors else None
    signal = classify_limit_signal(raw_error) if raw_error else None
    invocation = invocation_id or session_id
    terminal = terminal_records[0]
    cost_state = {
        str(key): value
        for key, value in terminal.items()
        if key not in {"type", "sessionId"}
    }
    return UsageLedgerEntry(
        id=_entry_id("anthropic", worker_id, account_id, invocation),
        provider="anthropic",
        worker_id=worker_id,
        account_id=account_id,
        invocation_id=invocation,
        session_id=session_id,
        package_id=package_id,
        attempt_id=attempt_id,
        observed_at=max(timestamps),
        model_diagnostic=",".join(sorted(models)) or None,
        input_tokens=usage_totals["input_tokens"],
        output_tokens=usage_totals["output_tokens"],
        cache_read_input_tokens=usage_totals["cache_read_input_tokens"],
        cache_creation_input_tokens=usage_totals["cache_creation_input_tokens"],
        duration_ms=(end - start).total_seconds() * 1000,
        outcome="LIMITED" if signal else "SUCCEEDED",
        task_completed=task_completed,
        review_completed=review_completed,
        limit_signal=signal,
        limit_raw_error=raw_error,
        source_type=UsageSource.TRANSCRIPT,
        source_identity=_source_identity("transcript", raw),
        source_metadata={
            "format": "claude-project-jsonl",
            "transcript_sha256": hashlib.sha256(raw).hexdigest(),
            "record_count": len(records),
            "assistant_record_count": sum(
                record.get("type") == "assistant" for record in records
            ),
            "unique_assistant_messages": len(assistants),
            "duplicate_assistant_records_ignored": duplicate_count,
            "versions": sorted(versions),
            "models": sorted(models),
            "duration_basis": "first_to_last_timestamp",
            "assistant_usage_records": [
                {"message_id": identity, "usage": usage}
                for identity, usage in sorted(assistants.items())
            ],
            "cost_state": cost_state,
        },
    )
