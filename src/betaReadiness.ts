export const BETA_READINESS_CHECK_IDS = [
  'sign-in-link',
  'numeric-code',
  'local-data-preservation',
  'tutorial',
  'capture',
  'review-confirmation',
  'calendar',
  'canvas',
  'offline-behavior',
  'installed-app-update',
  'deterministic-ai-fallback',
  'provider-backed-ai-verification',
  'diagnostics',
  'feedback',
  'runbook',
] as const

export type BetaReadinessCheckId = typeof BETA_READINESS_CHECK_IDS[number]
export type BetaReadinessStatus = 'pass' | 'fail' | 'not-tested' | 'blocked'
export type BetaReadinessState = 'ready' | 'conditional' | 'not-ready'

export interface BetaReadinessCheck {
  id: BetaReadinessCheckId
  status: BetaReadinessStatus
  evidence?: string
}

export interface BetaReadinessCounts {
  total: number
  pass: number
  fail: number
  notTested: number
  blocked: number
}

export interface BetaReadinessResult {
  checks: BetaReadinessCheck[]
  counts: BetaReadinessCounts
  blockingCheckIds: BetaReadinessCheckId[]
  overall: BetaReadinessState
  nextActions: BetaReadinessCheckId[]
}

const labels: Record<BetaReadinessCheckId, string> = {
  'sign-in-link': 'sign-in link',
  'numeric-code': 'numeric code',
  'local-data-preservation': 'local-data preservation',
  tutorial: 'tutorial',
  capture: 'capture',
  'review-confirmation': 'review confirmation',
  calendar: 'calendar',
  canvas: 'canvas',
  'offline-behavior': 'offline behavior',
  'installed-app-update': 'installed-app update',
  'deterministic-ai-fallback': 'deterministic AI fallback',
  'provider-backed-ai-verification': 'provider-backed AI verification',
  diagnostics: 'diagnostics',
  feedback: 'feedback',
  runbook: 'runbook',
}

const criticalIds = new Set<BetaReadinessCheckId>([
  'sign-in-link',
  'numeric-code',
  'local-data-preservation',
  'capture',
  'review-confirmation',
  'calendar',
  'canvas',
  'installed-app-update',
])

function isCheckId(value: string): value is BetaReadinessCheckId {
  return (BETA_READINESS_CHECK_IDS as readonly string[]).includes(value)
}

function cloneCheck(check: BetaReadinessCheck): BetaReadinessCheck {
  return check.evidence === undefined
    ? { id: check.id, status: check.status }
    : { id: check.id, status: check.status, evidence: check.evidence }
}

/**
 * Scores caller-supplied, observed beta checks. Missing checks are deliberately
 * represented as not-tested; configuration and defaults never count as evidence.
 */
export function scoreBetaReadiness(input: readonly BetaReadinessCheck[]): BetaReadinessResult {
  const supplied = new Map<BetaReadinessCheckId, BetaReadinessCheck>()

  for (const check of input) {
    if (!check || typeof check !== 'object' || !isCheckId(check.id)) {
      throw new Error(`Unknown beta readiness check ID: ${String(check?.id)}`)
    }
    if (!['pass', 'fail', 'not-tested', 'blocked'].includes(check.status)) {
      throw new Error(`Invalid beta readiness status for ${check.id}`)
    }
    if (check.evidence !== undefined && typeof check.evidence !== 'string') {
      throw new Error(`Evidence for ${check.id} must be text`)
    }
    if (supplied.has(check.id)) throw new Error(`Duplicate beta readiness check ID: ${check.id}`)
    supplied.set(check.id, check)
  }

  const checks = BETA_READINESS_CHECK_IDS.map(id => cloneCheck(supplied.get(id) ?? { id, status: 'not-tested' }))
  const counts = checks.reduce<BetaReadinessCounts>((result, check) => {
    result[check.status === 'not-tested' ? 'notTested' : check.status] += 1
    return result
  }, { total: checks.length, pass: 0, fail: 0, notTested: 0, blocked: 0 })

  const blockingCheckIds = checks
    .filter(check => check.status !== 'pass' && (criticalIds.has(check.id) || check.status === 'fail' || check.status === 'not-tested'))
    .map(check => check.id)
  const nextActions = checks
    .filter(check => check.status !== 'pass')
    .map(check => check.id)

  const providerBlockedOnly = checks.every(check =>
    check.status === 'pass' || check.id === 'provider-backed-ai-verification' && check.status === 'blocked')
  const overall: BetaReadinessState = blockingCheckIds.length > 0
    ? 'not-ready'
    : providerBlockedOnly && checks.some(check => check.id === 'provider-backed-ai-verification' && check.status === 'blocked')
      ? 'conditional'
      : checks.every(check => check.status === 'pass') ? 'ready' : 'conditional'

  return { checks, counts, blockingCheckIds, overall, nextActions }
}

export function betaReadinessCheckLabel(id: BetaReadinessCheckId): string {
  return labels[id]
}
