# Provider-Backed AI Interpretation (TASK-028, GitHub issue #38)

Status: implemented behind the existing interpretation boundary, opt-in and fail-closed.
This is the precursor slice for TASK-031 (real AI interpretation provider) — it wires a
real server-backed provider call, but does not turn it on by default and does not change
what the browser does today unless explicitly configured.

## What this is

`src/interpretationService.ts`'s public contract (`InterpretationService`, `interpretationService`,
`InterpretationProposal`) is unchanged. `src/aiInterpretation.ts` adds a provider-backed client
that:

1. Stays fully deterministic (`src/interpreter.ts`) unless a client-safe feature flag is
   explicitly set to `enabled`.
2. When enabled, POSTs only the minimal capture evidence to a same-origin Vercel Edge
   Function, `api/interpret.ts`.
3. Validates the response strictly and forces `reviewState: 'review'` regardless of what the
   response contains — the endpoint cannot bypass D-009 confirmation rules by construction
   (see "Confirmation rules are preserved" below).
4. Falls back to the deterministic service on **any** problem: the flag being off, a missing
   server API key, a network failure or timeout, a non-2xx response, or a payload that fails
   validation. A provider outage or misconfiguration never breaks or blocks a capture.

No secret ever reaches the browser. `api/interpret.ts` reads its provider API key from a
server-only environment variable and never forwards it to the client.

## Configuration

| Variable | Where | Purpose |
| --- | --- | --- |
| `VITE_AI_INTERPRETATION_PROVIDER` | Client (Vite `VITE_*`, safe to ship in the bundle) | Feature flag only, no secret. Set to exactly `enabled` to let the browser attempt the provider endpoint. Any other value (including unset) keeps the app fully deterministic and makes zero network calls to `/api/interpret`. |
| `AI_INTERPRETATION_API_KEY` | Server only (Vercel Production/Preview env vars) | The provider API key. Must **never** use a `VITE_` prefix — Vite exposes `VITE_*` vars to the client bundle. If unset, `api/interpret.ts` returns `503 { error: 'not_configured' }` and the client falls back to deterministic interpretation. |
Threadline pins provider calls to Anthropic Haiku (`claude-haiku-4-5-20251001`) in code.
There is no model environment override, so a dashboard change cannot silently move routine
captures to Sonnet or Opus. Changing the model requires a reviewed code change.

Local development and any environment with none of these set behaves exactly as before this
task: deterministic-only, no network call, no setup required.

## Endpoint contract: `POST /api/interpret`

Request body:

```json
{ "capture": { "id": "capture:1", "source": "text", "createdAt": "2026-09-16T00:00:00.000Z",
  "originalContent": "Call Ahmed about the proposal", "context": "Marketing", "evidence": "text-only" } }
```

Only the fields `CaptureRecord` already carries are sent — never canvas state, settings,
other captures, or account data. `originalContent` is capped at 4000 characters and content
type/shape are validated server-side before any provider call is made.

Responses:

- `200` — an `InterpretationProposal`-shaped body (`summary`, `rationale`, `confidence`,
  `proposedKind`, plus `proposedAction`/`proposedReminder`/`suggestedDate` as applicable).
  `reviewState` is always `"review"`; the client re-validates and would force this even if it
  were omitted or different.
- `400 { error: 'invalid_json' | 'invalid_capture' }` — malformed request.
- `405 { error: 'method_not_allowed' }` — non-`POST` request.
- `503 { error: 'not_configured', message }` — `AI_INTERPRETATION_API_KEY` is not set.
- `502 { error: 'provider_error', message }` — the upstream provider call failed, timed out,
  or returned output the server could not use.

## Confirmation rules are preserved (D-009)

The endpoint cannot itself confirm anything:

- `reviewState` in every successful response is the literal `"review"`, set by the server and
  re-forced by the client validator — it is never read from the provider's output.
- `proposedAction.summary` is always set to the same validated `summary` field, never to a
  provider-supplied value, so it cannot desynchronize from what `captureInterpretation.ts`
  requires (`proposedAction.summary === proposal.summary`).
- `proposedReminder.trigger.wording`, `.captureIds`, and `.deliveryState` are derived from the
  capture itself, never from the provider's free-form fields — a misbehaving or compromised
  endpoint cannot invent a different capture reference or a resolved delivery state.
- The provider prompt (`api/interpret.ts`) explicitly instructs the model that it only
  proposes, and that "action" and "commitment" require a clear/explicit basis rather than a
  possibility — but the code above is the actual enforcement; the prompt is not trusted alone.

Nothing in this slice creates a confirmed Action or Commitment, schedules a CalendarEvent, or
grants notification-delivery eligibility. All existing Review/confirmation behavior in
`src/objectWorkflow.ts` and `src/captureInterpretation.ts` is untouched.

## Provider call implementation

`api/interpret.ts` calls Anthropic's Messages API directly over `fetch` with a forced tool
call (`propose_interpretation`, a strict JSON schema) so the response is structured rather
than free text — no provider SDK dependency was added. This was a deliberate choice for this
task, not only a fallback: it keeps `package.json`/`pnpm-lock.yaml` untouched, avoids adding a
server dependency to a project that previously had none, and sidesteps any need to install
packages to deliver a real, working provider call. Swapping the provider or model later only
requires editing `api/interpret.ts`'s request/response mapping; `src/aiInterpretation.ts` and
`src/interpretationService.ts` do not need to change.

## Limitations and follow-ups

- **Live provider validation is an open follow-up/blocker.** This session had no shell/network
  access to run `pnpm install`, hit the real Anthropic API, or deploy to Vercel, so the actual
  end-to-end call (`api/interpret.ts` → `api.anthropic.com`) has been reviewed carefully by
  hand but not executed. Before enabling `VITE_AI_INTERPRETATION_PROVIDER=enabled` in any real
  environment: set `AI_INTERPRETATION_API_KEY` in Vercel, deploy, and manually verify a real
  capture against the live endpoint (success, missing-key, and induced-failure cases) before
  relying on it.
- One proposal per capture, matching the existing `InterpretationService` contract's
  documented limitation in `src/interpretationService.ts` — this slice does not change that.
- No retry/backoff or rate limiting is implemented; a provider outage simply falls back to
  deterministic interpretation for each capture independently.
- Settings now shows whether the browser is in deterministic-only mode or whether provider
  attempts are enabled by the client feature flag. This status is configuration-level only;
  individual proposal provenance and provider success/fallback telemetry remain future work.
- `api/interpret.ts` is type-checked by the dedicated `tsconfig.api.json` target, which is
  included in `pnpm check`. It still is not bundled into the Vite SPA and must not import from
  `src/`, because it runs in the Vercel Edge Function runtime.
- The prompt and tool schema are a first pass tuned to this app's existing deterministic
  heuristics' vocabulary; TASK-031 should evaluate real interpretation quality against
  ambiguous/consequential/low-confidence fixtures before wider rollout.

### Exact response to move forward

`Set AI_INTERPRETATION_API_KEY in Vercel Production/Preview, deploy, and manually validate a real /api/interpret call (success, missing-key 503, and induced-failure fallback) before enabling VITE_AI_INTERPRETATION_PROVIDER=enabled anywhere; then proceed with TASK-031's broader evaluation.`


## TASK-031 follow-up: safety and visibility hardening

This follow-up keeps provider-backed interpretation disabled unless `VITE_AI_INTERPRETATION_PROVIDER=enabled` is explicitly set. It adds Settings copy that honestly distinguishes deterministic built-in rules from provider attempts, and it reiterates that all proposals remain review-only: the provider cannot confirm actions, commitments, calendar events or notifications.

Additional evaluator coverage now checks uncertain action-like captures, consequential reminder/timing captures, cancellation/change-of-intent language, provider status labels, and provider confidence bounds. `pnpm check` also runs `tsc -p tsconfig.api.json` so the Vercel Edge Function receives dedicated type-check coverage without adding provider keys or calling the live provider.

### Exact response to move forward
`Set AI_INTERPRETATION_API_KEY only as a server-side Vercel env var, deploy, validate /api/interpret success and failure cases manually, then consider enabling VITE_AI_INTERPRETATION_PROVIDER=enabled in Preview only.`
