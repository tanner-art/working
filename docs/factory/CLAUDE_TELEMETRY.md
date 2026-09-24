# Claude consumption telemetry

## Purpose and authority boundary

Claude remains eligible from observable health: valid authentication, fresh
heartbeat, successful live invocation, and no explicit rate-limit,
exhaustion, or repeated throttling signal. Factory-measured tokens and runtime
are operational consumption metrics. They are not an Anthropic quota
percentage and do not create a capacity ceiling.

The telemetry writer appends to the Factory Registry through the `Registry`
contract. The SQLite tables are the migration adapter; no telemetry-side
database or JSON authority exists. This package does not change dispatch or
the installed runner's capacity policy.

## Machine observations (2026-09-24)

The installed binary is `/opt/homebrew/bin/claude`, Claude Code `2.1.278`.
Its help reports these supported programmatic modes:

- `claude -p ... --output-format json` for one result object;
- `claude -p ... --output-format stream-json` for a JSONL event stream;
- `--no-session-persistence` when a caller does not need a resumable local
  transcript.

The single-result shape observed from this installed binary contained:

- `type`, `subtype`, `is_error`, `session_id`, `uuid`, and `result_index`;
- `duration_ms`, `duration_api_ms`, `num_turns`, `stop_reason`, and
  `terminal_reason`;
- `modelUsage` and `usage`;
- within `usage`: `input_tokens`, `output_tokens`,
  `cache_read_input_tokens`, `cache_creation_input_tokens`,
  `cache_creation`, `iterations`, `service_tier`, `speed`, and tool-use
  diagnostics.

These are observations, not a promise that every field is always present.
The parser treats measurements as optional and rejects malformed numeric
values rather than treating them as zero.

Alongside normalized totals, source provenance retains typed, explicitly
allowlisted content-free metadata: API duration, turn count, stop state, cost,
fast-mode state, queue depth, error flag, known per-model counters, known cache
and server-tool counters, permission-denial count, and a subagent count. Unknown
keys and nested values are not copied. The ordinary `result` text,
permission-denial payloads, raw subagent structures, unknown model/usage
members, and unknown cost-state members are excluded because they can contain
conversation or tool-input data. Present allowlisted fields with the wrong type
fail ingestion instead of being serialized.

The live probe in the current shell returned exit status 1 with a structured
result whose `is_error` was true, `terminal_reason` was `api_error`, and error
text reported that the CLI was not logged in. `claude auth status` also
reported `loggedIn: false` for this shell. A separate fresh local transcript
from minutes earlier contained a successful `claude-sonnet-5` turn. This is
evidence of context-dependent authentication, not evidence that Claude is
globally offline or globally healthy. The runner must evaluate authentication
and invocation success in its own launch environment.

The parser successfully processed that completed `2.1.278` transcript and
measured 2 uncached input tokens, 18 output tokens, 16,788 cache-read input
tokens, 23,484 cache-creation input tokens, and 3.409 seconds from the first to
last transcript timestamp. A content-free scan of the available assistant API
error records found no actual rate-limit, exhaustion, or throttling event.

An unusual installed-CLI detail is that the failed result still used
`subtype: success`; consumers must use `is_error` and the terminal fields for
outcome, not `subtype` alone.

## Transcript discovery and observed format

`claude auth status` resolved the projects directory to the current user's
`~/.claude/projects` directory on this machine. Actual sessions were found at:

`<projects-directory>/<encoded-working-directory>/<session-id>.jsonl`

The ingestion command requires this verified projects directory through
`--transcript-root`; the parser does not assume the home-directory layout and
rejects paths outside that root. It also requires the filename stem to match
the transcript `sessionId` and a terminal `cost-state` record, preventing
partial-session accounting.

Observed assistant records use top-level `type`, `sessionId`, `timestamp`,
`uuid`, `version`, and `message`. `message` supplies `id`, `model`, `role`,
`stop_reason`, and `usage`. Assistant usage records observed on this host came
from Claude Code `2.1.270` and `2.1.278` and shared the token fields listed
above.

One provider message commonly appears as several assistant JSONL records, one
per content block. Those records have the same `message.id` and identical
usage. Transcript ingestion therefore counts one usage object per unique
provider message ID and rejects conflicting usage for a repeated ID. Counting
each line would materially overstate consumption.

The transcript parser does not retain user prompts, normal assistant content,
attachments, tool inputs, file paths, or rendered context. It reads text only
on records explicitly marked `isApiErrorMessage`, and retains that text only
when it contains an explicit rate-limit, exhaustion, or throttling signal.
Source metadata contains format/version/model sets, counts, a SHA-256 digest,
the measurement basis, per-message normalized token counters keyed by hashed
message identity, and explicitly allowlisted terminal cost-state counters.

## Ledger contract

`usage_ledger` is append-only and stores one aggregate per
`(provider, worker, account, invocation_id)`:

- Registry entry ID, provider, worker/account, invocation ID, and session ID;
- an observation class: `AUTONOMOUS` or the separate
  `DIAGNOSTIC` health-probe class;
- mandatory package and attempt references for every autonomous invocation;
- observation timestamp and model diagnostic;
- optional input, output, cache-read, and cache-creation tokens;
- optional duration, outcome, task completion, and review completion;
- explicit limit signal, raw provider error, reset time when supplied, and a
  snapshot of Factory-measured rolling consumption before the limit;
- primary source type, identity, and content-free structural metadata.

`usage_ledger_sources` is also append-only. It records every structured source
that observed an invocation. A runner-generated invocation ID is the preferred
deduplication key: JSON/stream output and later transcript ingestion attach to
one counted ledger row. Canonical reads merge those immutable observations in a
fixed source order, independently of ingestion order. Token/model/identity,
ordinary outcome, and same-basis duration disagreements fail closed; completion facts are monotonic;
an explicit limit signal from any source makes the invocation `LIMITED` and is
never hidden by a transcript observed first. CLI duration wins over the broader
first-to-last transcript duration. Without a runner ID, the Claude session ID
is the conservative fallback. Transcript fallback accepts exactly one terminal
`cost-state`, so it is limited to one completed autonomous invocation per
session. Resumed or multi-invocation sessions must use the per-invocation CLI
JSON/stream result; whole-session transcript segmentation is not implemented.

The Registry validates that each autonomous attempt exists and belongs to its
declared package. Unlinked probes must opt into `DIAGNOSTIC`; diagnostic records
cannot claim package/attempt provenance or task/review completion.

Transcript files should be ingested only after the terminal record appears.
Because the canonical ledger row is immutable, a partial transcript is
rejected rather than inserted and later rewritten.

## Ingestion

The runner should generate an invocation ID before launch, preserve the raw
structured result under its existing restricted telemetry retention policy,
and ingest it after the process exits. For example:

```text
python3 -m scripts.factory_registry.claude_telemetry_cli ingest-json \
  --database /absolute/path/factory.sqlite3 \
  --worker claude --account approved-account \
  --invocation-id runner-generated-id \
  --package-id PACKAGE --attempt-id ATTEMPT \
  --observed-at 2026-09-24T20:00:00Z \
  --cli-version 2.1.278 /absolute/path/result.json
```

Use `ingest-stream-json` for the stream format. Use `ingest-transcript` with an
explicit `--transcript-root` for the completed matching transcript. Repeating
the same source is a no-op. Ingesting a second source for the same invocation
adds provenance without adding consumption.

For a source-free service/authentication probe, omit package and attempt and add
`--diagnostic-health-probe`. Do not use that class for dispatched Factory work.

## Migration and rollback

Registry schema version 3 adds the explicit observation class and autonomous
provenance constraint to the version-2 `usage_ledger` and
`usage_ledger_sources` foundation. Initialization upgrades a version 1 or 2
Registry in place without rewriting existing features, packages, attempts,
usage observations, failures, or events. Rollback is to stop telemetry
ingestion and run the previous Registry reader, which ignores these additive
tables. Do not downgrade the schema version or delete ledger rows: retained
telemetry is provenance and a later adapter migration must copy it losslessly.

## Analytics and capacity semantics

`Registry.usage_analytics` and the CLI `analytics` command expose:

- rolling 24-hour and seven-day token components, invocation counts,
  productive runtime, task completions, and review throughput;
- tasks and reviews completed by day;
- average measured tokens per completed task;
- output tokens per productive hour when both values are measurable;
- explicit limit observations with reset timing and pre-limit rolling
  consumption.

The projection labels these values `FACTORY_MEASURED_CONSUMPTION` and returns
`provider_reported_percent: null` and `inferred_capacity_percent: null`.
Dashboard consumers must display those scopes separately. They must not turn
unknown provider percentage into constrained eligibility.

Transcript duration is measured from the first to last timestamp in the
completed file and is labeled as such. It can include idle gaps. CLI
`duration_ms` is preferable for per-invocation productive runtime.

## Limit calibration

Only explicit provider language is classified: rate limits/HTTP 429,
subscription or quota exhaustion, and throttling. Generic network, service,
authentication, overload, and model errors remain ordinary failures and do
not invent a subscription ceiling. Every classified event preserves the raw
provider error, reset time when present, and the Factory's measured 24-hour
and seven-day consumption immediately before the event. A future soft limit
requires repeated real observations and owner approval.
