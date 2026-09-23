import type { CaptureRecord } from './domain'
import type { InterpretationProposal, InterpretationService } from './interpretationService'
import { deterministicInterpretationService } from './interpreter'
import { supabase } from './auth'

/** Only the capture evidence needed to interpret one thought; never account, canvas,
 * or persisted-state data. Mirrors CaptureRecord so the server cannot request more. */
export interface InterpretRequestBody {
  capture: Pick<CaptureRecord, 'id' | 'source' | 'createdAt' | 'originalContent' | 'context' | 'evidence'>
}

export type ProviderConfig = { status: 'enabled' } | { status: 'disabled' }
export interface ProviderStatus { label: string; description: string; enabled: boolean }

/** Explicit opt-in only: the browser stays fully deterministic unless this is exactly
 * "enabled". Client-safe — carries no secret, only a feature toggle. */
export function readProviderConfig(env: { VITE_AI_INTERPRETATION_PROVIDER?: string }): ProviderConfig {
  return env.VITE_AI_INTERPRETATION_PROVIDER?.trim() === 'enabled' ? { status: 'enabled' } : { status: 'disabled' }
}

export function providerStatus(config: ProviderConfig): ProviderStatus {
  return config.status === 'enabled'
    ? { enabled: true, label: 'Provider attempts enabled', description: 'Signed-in captures may ask the server provider for proposed meaning. Threadline falls back to built-in rules if the provider is unavailable. Review confirmation is still required.' }
    : { enabled: false, label: 'Built-in rules only', description: 'Captures are organized by deterministic rules built into the app. No provider request is made unless the client feature flag is enabled.' }
}

const DEFAULT_ENDPOINT = '/api/interpret'
const DEFAULT_TIMEOUT_MS = 12_000
const RESOLVED_KINDS = new Set(['idea', 'project', 'commitment', 'person', 'reference', 'objective'])

function isConfidence(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= 1
}

/** Defense in depth: never trust a remote payload. Forces reviewState to "review" and
 * derives proposedAction/proposedReminder from the capture itself (never the provider's
 * free-form fields), so a misbehaving or compromised endpoint cannot bypass D-009
 * confirmation or desynchronize proposedAction.summary/proposedReminder.trigger.wording
 * from what captureInterpretation.ts requires. */
export function validateInterpretationProposal(capture: CaptureRecord, value: unknown): InterpretationProposal {
  if (!value || typeof value !== 'object') throw new Error('Provider response is not an object.')
  const candidate = value as Record<string, unknown>
  const { summary, rationale, confidence, proposedKind } = candidate
  if (typeof summary !== 'string' || !summary.trim()) throw new Error('Provider response is missing a summary.')
  if (typeof rationale !== 'string' || !rationale.trim()) throw new Error('Provider response is missing a rationale.')
  if (!isConfidence(confidence)) throw new Error('Provider response has an invalid confidence.')
  const suggestedDate = typeof candidate.suggestedDate === 'string' && candidate.suggestedDate.trim() ? candidate.suggestedDate : undefined
  const base = { summary, rationale, confidence, reviewState: 'review' as const, suggestedDate }
  if (proposedKind === 'unresolved') {
    return { ...base, proposedKind: 'unresolved', proposedReminder: {
      captureIds: [capture.id], deliveryState: 'needs-review',
      trigger: { kind: 'unresolved', wording: capture.originalContent, legacyDate: suggestedDate },
    } }
  }
  if (proposedKind === 'action') return { ...base, proposedKind: 'action', proposedAction: { summary } }
  if (typeof proposedKind === 'string' && RESOLVED_KINDS.has(proposedKind)) {
    return { ...base, proposedKind: proposedKind as Exclude<InterpretationProposal['proposedKind'], 'unresolved' | 'action'> }
  }
  throw new Error(`Provider response has an unsupported proposedKind: ${String(proposedKind)}`)
}

export interface ProviderCallOptions {
  endpoint?: string
  fetchImpl?: typeof fetch
  timeoutMs?: number
  getAccessToken?: () => Promise<string | undefined>
}

async function currentAccessToken(): Promise<string | undefined> {
  if (!supabase) return undefined
  const { data, error } = await supabase.auth.getSession()
  if (error) throw error
  return data.session?.access_token
}

async function callInterpretEndpoint(capture: CaptureRecord, options: ProviderCallOptions): Promise<unknown> {
  const endpoint = options.endpoint ?? DEFAULT_ENDPOINT
  const fetchImpl = options.fetchImpl ?? fetch
  const accessToken = await (options.getAccessToken ?? currentAccessToken)()
  if (!accessToken) throw new Error('Sign in before using provider-backed interpretation.')
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), options.timeoutMs ?? DEFAULT_TIMEOUT_MS)
  try {
    const response = await fetchImpl(endpoint, {
      method: 'POST',
      headers: { 'content-type': 'application/json', 'authorization': `Bearer ${accessToken}` },
      body: JSON.stringify({ capture: {
        id: capture.id, source: capture.source, createdAt: capture.createdAt,
        originalContent: capture.originalContent, context: capture.context, evidence: capture.evidence,
      } } satisfies InterpretRequestBody),
      signal: controller.signal,
    })
    if (!response.ok) throw new Error(`Provider endpoint responded with status ${response.status}.`)
    return await response.json()
  } finally { clearTimeout(timeout) }
}

/** Raw provider-backed service: propagates any network, validation, or provider error.
 * Composable on its own (e.g. for direct testing); the exported default service below
 * wraps this with the required fail-closed fallback. */
export function createProviderInterpretationService(options: ProviderCallOptions = {}): InterpretationService {
  return { async interpret(capture) {
    const raw = await callInterpretEndpoint(capture, options)
    return validateInterpretationProposal(capture, raw)
  } }
}

/** Fails closed to the deterministic heuristics on any provider problem: disabled
 * configuration, missing server env, network failure, timeout, a non-2xx response, or a
 * malformed/invalid payload. A provider outage never surfaces as a broken capture. */
export function createFailClosedInterpretationService(config: ProviderConfig, options: ProviderCallOptions = {}): InterpretationService {
  if (config.status === 'disabled') return deterministicInterpretationService
  const provider = createProviderInterpretationService(options)
  return { async interpret(capture) {
    try { return await provider.interpret(capture) }
    catch (error) {
      if (typeof console !== 'undefined') console.warn('AI interpretation provider unavailable; using deterministic interpretation.', error)
      return deterministicInterpretationService.interpret(capture)
    }
  } }
}

const providerConfig = readProviderConfig({ VITE_AI_INTERPRETATION_PROVIDER: import.meta.env.VITE_AI_INTERPRETATION_PROVIDER })
/** Composition point consumed by src/interpretationService.ts. See docs/AI_INTERPRETATION.md. */
export const aiInterpretationService: InterpretationService = createFailClosedInterpretationService(providerConfig)
