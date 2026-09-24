import type { FactoryCapacityScope, FactoryControlSnapshot, FactoryEvidence, FactoryFeature, FactoryPackage, FactoryWorker, HealthState, ReviewState } from './factoryControl'

export const WORKER_HEARTBEAT_FRESH_SECONDS = 180

export interface WorkerDisplayHealth {
  state: HealthState
  reason: string
}

export interface ReviewDisplayItem {
  id: string
  packageId: string
  implementerWorkerId: string | null
  eligibleReviewerIds: string[]
  assignedReviewerId: string | null
  requestedAt: string | null
  state: ReviewState
  findings: string[]
  changesRequested: string[]
  approvalEvidence: FactoryEvidence[]
  source: 'registry_review' | 'package_state'
}

export interface AttentionDisplayItem {
  id: string
  code: string
  title: string
  detail: string
  severity: 'warning' | 'critical'
  occurredAt: string | null
  workerId: string | null
  packageId: string | null
  requiresHuman: boolean
  source: 'registry_failure' | 'package_state'
}

export interface QueueFilters {
  state: string
  lane: string
  worker: string
  priority: string
  feature: string
  blockedReason: string
}

export const emptyQueueFilters: QueueFilters = { state: '', lane: '', worker: '', priority: '', feature: '', blockedReason: '' }

export function filterFactoryFeatures(features: FactoryFeature[], filters: QueueFilters): FactoryFeature[] {
  return features.flatMap(feature => {
    if (filters.feature && feature.id !== filters.feature) return []
    const packages = feature.packages.filter(item => packageMatches(item, filters))
    return packages.length ? [{ ...feature, packages }] : []
  })
}

function packageMatches(item: FactoryPackage, filters: QueueFilters): boolean {
  if (filters.state && item.state !== filters.state) return false
  if (filters.lane && item.lane !== filters.lane) return false
  if (filters.worker && item.ownerWorkerId !== filters.worker) return false
  if (filters.priority && item.priority !== Number(filters.priority)) return false
  if (filters.blockedReason && !`${item.failureCode ?? ''} ${item.blockReason ?? ''}`.toLowerCase().includes(filters.blockedReason.toLowerCase())) return false
  return true
}

export function packageIndex(features: FactoryFeature[]): Map<string, FactoryPackage> {
  return new Map(features.flatMap(feature => feature.packages.map(item => [item.id, item] as const)))
}

export function capacitySummary(scope: FactoryCapacityScope): string {
  if (scope.source === 'provider_reported' && scope.usedPercent !== null) return `${scope.usedPercent}% used · provider reported`
  if (scope.source === 'inferred' && scope.usedPercent !== null) return `${scope.usedPercent}% used · Factory inference`
  if (scope.source === 'factory_measured') return `${scope.rolling24Hours.outputTokens ?? 'Unknown'} output tokens · measured over 24h`
  return 'Capacity value unknown'
}

export function effectiveWorkerHealth(worker: FactoryWorker, generatedAt: string): WorkerDisplayHealth {
  if (worker.health === 'offline') return { state: 'offline', reason: 'Worker reports offline.' }
  if (worker.serviceState === 'offline') return { state: 'offline', reason: 'Service reports offline.' }
  if (worker.authenticationState === 'invalid') return { state: 'constrained', reason: 'Authentication is invalid.' }
  if (worker.serviceState !== 'healthy') return { state: 'constrained', reason: `Service state is ${worker.serviceState}.` }
  if (worker.authenticationState !== 'valid') return { state: 'constrained', reason: `Authentication state is ${worker.authenticationState}.` }
  if (worker.heartbeatAt === null) return { state: 'constrained', reason: 'Heartbeat evidence is missing.' }

  const heartbeatAgeSeconds = (Date.parse(generatedAt) - Date.parse(worker.heartbeatAt)) / 1000
  if (heartbeatAgeSeconds < 0) return { state: 'constrained', reason: 'Heartbeat timestamp is in the future.' }
  if (heartbeatAgeSeconds > WORKER_HEARTBEAT_FRESH_SECONDS) return { state: 'constrained', reason: `Heartbeat evidence is stale (${Math.floor(heartbeatAgeSeconds)}s old).` }
  if (worker.health === 'constrained') return { state: 'constrained', reason: 'Worker reports constrained.' }
  return { state: 'healthy', reason: 'Service, authentication, and heartbeat evidence are current.' }
}

export function visibleReviews(snapshot: FactoryControlSnapshot): ReviewDisplayItem[] {
  const explicit = snapshot.reviews.map(review => ({ ...review, source: 'registry_review' as const }))
  const represented = new Set(explicit.map(review => review.packageId))
  const derived = snapshot.features.flatMap(feature => feature.packages).flatMap(item => {
    if (item.state !== 'VERIFY_REVIEW' || represented.has(item.id)) return []
    const latestAttempt = item.attempts.find(attempt => attempt.number === item.attemptNumber) ?? item.attempts.at(-1)
    return [{
      id: `package-review-${item.id}`,
      packageId: item.id,
      implementerWorkerId: latestAttempt?.workerId ?? item.ownerWorkerId,
      eligibleReviewerIds: [],
      assignedReviewerId: null,
      requestedAt: null,
      state: item.reviewState ?? 'waiting',
      findings: [],
      changesRequested: item.reviewState === 'changes_requested' && item.blockReason ? [item.blockReason] : [],
      approvalEvidence: item.evidence.filter(evidence => evidence.kind === 'review'),
      source: 'package_state' as const,
    }]
  })
  return [...explicit, ...derived]
}

export function visibleAttention(snapshot: FactoryControlSnapshot): AttentionDisplayItem[] {
  const explicit = snapshot.failures.map(failure => ({ ...failure, source: 'registry_failure' as const }))
  const represented = new Set(explicit.map(failure => `${failure.packageId ?? ''}:${failure.code}`))
  const packagesWithStructuredReview = new Set(snapshot.reviews.map(review => review.packageId))
  const packagesWithStructuredFailure = new Set(snapshot.failures.flatMap(failure => failure.packageId === null ? [] : [failure.packageId]))
  const derived = snapshot.features.flatMap(feature => feature.packages).flatMap(item => {
    const reviewStateUnrecorded = item.state === 'VERIFY_REVIEW'
      && item.reviewState === null
      && item.evidence.some(evidence => evidence.kind === 'review')
      && !packagesWithStructuredReview.has(item.id)
      && !packagesWithStructuredFailure.has(item.id)
    const code = item.failureCode
      ?? (item.reviewState === 'changes_requested' ? 'REVIEW_FAILURE' : null)
      ?? (reviewStateUnrecorded ? 'REVIEW_STATE_UNRECORDED' : null)
    if (!code || represented.has(`${item.id}:${code}`)) return []
    const missingReviewState = code === 'REVIEW_STATE_UNRECORDED'
    return [{
      id: `package-attention-${item.id}-${code}`,
      code,
      title: missingReviewState ? 'Review outcome is not recorded' : item.reviewState === 'changes_requested' ? 'Review remediation required' : 'Package requires attention',
      detail: missingReviewState
        ? 'Review evidence exists for this VERIFY / REVIEW package, but this Registry revision has no structured review outcome or failure.'
        : item.blockReason ?? 'The Registry package state records a failure without a structured failure detail.',
      severity: 'warning' as const,
      occurredAt: null,
      workerId: item.ownerWorkerId,
      packageId: item.id,
      requiresHuman: false,
      source: 'package_state' as const,
    }]
  })
  return [...explicit, ...derived]
}
