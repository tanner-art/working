# Provider-Backed AI Interpretation (TASK-122, GitHub issue #113)

Status: implemented and migrated to Vercel AI Gateway, behind the existing interpretation boundary, opt-in and fail-closed.
This slice uses a real server-backed provider call via Vercel AI Gateway (not the Anthropic API directly),
but does not turn it on by default and does not change what the browser does today unless explicitly configured.

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
| `AI_INTERPRETATION_PROVIDER` | Server only (set for Preview only during validation) | Server-side safety gate. Set to exactly `enabled` before the endpoint may use any provider credential. Automatic OIDC alone never activates the endpoint. Leave unset in Production until production rollout is explicitly approved. |
| `AI_GATEWAY_API_KEY` | Server only (Vercel Production/Preview env vars) | Bearer token for Vercel AI Gateway. Must **never** use a `VITE_` prefix — Vite exposes `VITE_*` vars to the client bundle. If set, this takes precedence over `VERCEL_OIDC_TOKEN`. |
| Vercel OIDC token | Server only (Vercel automatic) | OIDC fallback for Vercel AI Gateway when `AI_GATEWAY_API_KEY` is not set. The official `@vercel/oidc` helper reads `VERCEL_OIDC_TOKEN` at build/local time or Vercel's trusted request context at function runtime. If no credential is available, `api/interpret.ts` returns `503 { error: 'not_configured' }` and the client falls back to deterministic interpretation. |

Threadline pins provider calls to Anthropic Haiku (`anthropic/claude-haiku-4.5`) in code.
There is no model environment override, so a dashboard change cannot silently move routine
captures to Sonnet or Opus. Changing the model requires a reviewed code change.

Local development and any environment without both enable flags set behaves exactly as before this
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
- `503 { error: 'provider_disabled', message }` — the server-only provider gate is not enabled for this deployment.
- `503 { error: 'not_configured', message }` — the server gate is enabled but neither `AI_GATEWAY_API_KEY` nor `VERCEL_OIDC_TOKEN` is set.
- `502 { error: 'provider_error', message }` — the upstream provider call (to Vercel AI Gateway) failed, timed out,
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

`api/interpret.ts` calls Vercel AI Gateway (`https://ai-gateway.vercel.sh/v1/messages`) over `fetch`
with a forced tool call (`propose_interpretation`, a strict JSON schema) so the response is structured
rather than free text — no provider SDK dependency was added. Vercel AI Gateway provides a unified
interface to Anthropic's Messages API (and future providers) with optional features like token caching
and request routing.

Authentication uses a Bearer token from `AI_GATEWAY_API_KEY` if present, or uses Vercel's official
`getVercelOidcToken()` helper to retrieve the automatic deployment credential when the key is not set.
This design eliminates the need for manual secret management in most Vercel deployments while supporting
explicit API keys where preferred.

No provider SDK dependency was added. This keeps `package.json`/`pnpm-lock.yaml` untouched, avoids
adding a server dependency to a project that previously had none, and sidesteps any need to install
packages to deliver a real, working provider call. Swapping the provider or model later only requires
editing `api/interpret.ts`'s request/response mapping; `src/aiInterpretation.ts` and
`src/interpretationService.ts` do not need to change.

## Limitations and follow-ups

- **Live provider validation is required before enabling in production.** The endpoint and authentication
  paths have been implemented and tested with mocked fetch. Before enabling `VITE_AI_INTERPRETATION_PROVIDER=enabled`
  in any real environment:
  1. Set `AI_INTERPRETATION_PROVIDER=enabled` for Preview only, then ensure either `AI_GATEWAY_API_KEY` is set or rely on automatic `VERCEL_OIDC_TOKEN`.
  2. Deploy to Vercel (Preview or Production) and manually verify a real capture against the live endpoint.
  3. Test success cases, missing-key (503), and induced-failure fallback scenarios.
  4. Confirm the Vercel AI Gateway connection is stable and performant.
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

1. Deploy to Vercel with `AI_INTERPRETATION_PROVIDER=enabled` in Preview only (test with either `AI_GATEWAY_API_KEY` explicitly set or with automatic `VERCEL_OIDC_TOKEN`).
2. Manually validate a real /api/interpret call (success, missing-key 503, and induced-failure fallback).
3. Enable `VITE_AI_INTERPRETATION_PROVIDER=enabled` in Preview only.
4. Proceed with TASK-031's broader evaluation.


## TASK-031 follow-up: safety and visibility hardening

This follow-up keeps provider-backed interpretation disabled unless `VITE_AI_INTERPRETATION_PROVIDER=enabled` is explicitly set. It adds Settings copy that honestly distinguishes deterministic built-in rules from provider attempts, and it reiterates that all proposals remain review-only: the provider cannot confirm actions, commitments, calendar events or notifications.

Additional evaluator coverage now checks uncertain action-like captures, consequential reminder/timing captures, cancellation/change-of-intent language, provider status labels, and provider confidence bounds. `pnpm check` also runs `tsc -p tsconfig.api.json` so the Vercel Edge Function receives dedicated type-check coverage without adding provider keys or calling the live provider.

### Preview Activation Checklist

Before enabling `VITE_AI_INTERPRETATION_PROVIDER=enabled`:

- [ ] Deploy to Vercel with `AI_INTERPRETATION_PROVIDER=enabled` in Preview only and either `AI_GATEWAY_API_KEY` set or automatic `VERCEL_OIDC_TOKEN` available.
- [ ] Call `/api/interpret` manually with a valid capture (curl or Postman) — expect 200 + proposal.
- [ ] In a local or isolated deployment where automatic OIDC is unavailable, unset auth credentials and call `/api/interpret` again — expect 503 with not_configured.
- [ ] Unset `AI_INTERPRETATION_PROVIDER` while OIDC remains available and call `/api/interpret` — expect 503 with provider_disabled and no Gateway request.
- [ ] Intentionally send malformed output mock and verify endpoint returns 502.
- [ ] Verify deterministic fallback activates when provider is unavailable (network error, timeout, etc.).
- [ ] Confirm that `proposedAction.summary` always matches `proposal.summary` (D-009 enforcement).
- [ ] Confirm that `reviewState` is always `"review"` regardless of provider output.
- [ ] Enable `VITE_AI_INTERPRETATION_PROVIDER=enabled` in Preview env vars.
- [ ] Create a test capture in Preview and verify the provider proposal appears in Review.
- [ ] Document that producer can only be enabled for Preview; production rollout requires explicit approval.
