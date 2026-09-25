import type { FactoryCapacityScope, FactoryControlSnapshot, FactoryEvidence, FactoryFeature, FactoryPackage, FactoryWorker, HealthState, ReviewState } from './factoryControl'

export const WORKER_HEARTBEAT_FRESH_SECONDS = 180

export interface WorkerDisplayHealth {
  state: HealthState
  reason: string
}

export interface WorkerConstraintDetail {
  code: string
  reason: string
  nextAction: string
}

export interface ReviewDisplayItem {
  id: string
  packageId: string
  implementerWorkerId: string | null
  eligibleReviewerIds: string[]
  assignedReviewerId: string | null
  requestedAt: string | null
  state: ReviewState | 'unrecorded'
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

export function workerConstraintDetails(worker: FactoryWorker, generatedAt: string, scopes: FactoryCapacityScope[] = []): WorkerConstraintDetail[] {
  const details: WorkerConstraintDetail[] = []
  const add = (code: string, reason: string, nextAction: string) => details.push({ code, reason, nextAction })
  if (worker.health === 'offline') add('WORKER_OFFLINE', 'Worker reports offline.', 'Reload the worker in PAUSED / DRY-RUN and verify a fresh heartbeat before making it eligible.')
  if (worker.serviceState === 'offline') add('SERVICE_OFFLINE', 'Worker service reports offline.', 'Reload the service in PAUSED / DRY-RUN and verify its launch environment.')
  else if (worker.serviceState === 'degraded') add('SERVICE_DEGRADED', 'Worker service reports degraded.', 'Inspect the service diagnostic and restore a healthy live invocation before dispatch.')
  else if (worker.serviceState === 'unknown') add('SERVICE_UNKNOWN', 'Service state is unknown.', 'Refresh the worker service observation before dispatch.')
  if (worker.authenticationState === 'invalid') add('AUTH_INVALID', 'Authentication is invalid.', 'Repair the worker authentication environment and verify a live invocation from the runner environment.')
  else if (worker.authenticationState === 'unknown') add('AUTH_UNKNOWN', 'Authentication state is unknown.', 'Run a non-destructive authentication probe from the runner environment.')

  if (worker.heartbeatAt === null) add('HEARTBEAT_MISSING', 'Heartbeat evidence is missing.', 'Reload in PAUSED / DRY-RUN and wait for a fresh heartbeat.')
  else {
    const age = (Date.parse(generatedAt) - Date.parse(worker.heartbeatAt)) / 1000
    if (age < 0) add('HEARTBEAT_FUTURE', 'Heartbeat timestamp is in the future.', 'Correct the host clock or heartbeat timestamp before dispatch.')
    else if (age > WORKER_HEARTBEAT_FRESH_SECONDS) add('HEARTBEAT_STALE', `Last heartbeat is ${Math.floor(age)}s old; the limit is ${WORKER_HEARTBEAT_FRESH_SECONDS}s.`, 'Reload in PAUSED / DRY-RUN and refresh the heartbeat.')
  }

  if (worker.capacityState !== 'normal') {
    const latest = [...scopes]
      .filter(scope => scope.observedAt !== null)
      .sort((left, right) => (right.observedAt ?? '').localeCompare(left.observedAt ?? ''))[0]
    const observation = latest
      ? `${latest.label}: ${capacitySummary(latest)}; observed ${latest.observedAt}.`
      : 'No current capacity observation is recorded.'
    const nextAction = worker.capacityState === 'unknown'
      ? 'Refresh the provider or Factory capacity observation before dispatch.'
      : worker.capacityState === 'caution'
        ? 'Avoid a substantial or uncertain new parent; bounded work remains eligible.'
        : worker.capacityState === 'checkpoint'
          ? 'Finish current bounded work to a clean checkpoint, then do not start a substantial parent.'
          : 'Do not dispatch normal work until a fresh healthy capacity observation is recorded.'
    add(`CAPACITY_${worker.capacityState.toUpperCase()}`, observation, nextAction)
  }
  if (!details.length && worker.health === 'constrained') add('WORKER_CONSTRAINED', 'Worker reports constrained without a more specific diagnostic.', 'Refresh worker diagnostics and keep the worker in PAUSED / DRY-RUN.')
  return details
}

export function readinessReason(item: FactoryPackage, packages: Map<string, FactoryPackage>): string {
  if (item.state === 'READY') return 'All recorded prerequisites are satisfied; this package is READY.'
  if (item.state === 'ACTIVE') return 'An active Registry lease owns this package.'
  if (item.state === 'VERIFY_REVIEW') return 'Implementation is waiting for validation or independent review.'
  if (item.state === 'DONE') return 'Registry completion requirements are recorded as satisfied.'
  if (item.blockReason) return item.blockReason
  const incomplete = item.dependencies.filter(id => packages.get(id)?.state !== 'DONE')
  if (incomplete.length) return `Waiting for ${incomplete.map(id => `${id} (${packages.get(id)?.state ?? 'missing'})`).join(', ')}.`
  if (item.state === 'ON_DECK') return 'Proposed / suggested work is recorded in Registry and has not been promoted to READY.'
  return 'Registry records this package as BLOCKED without a human-readable reason.'
}

export function failureClassification(code: string): string {
  if (code.includes('AUTH')) return 'authentication'
  if (code.includes('CAPACITY') || code === 'RATE_LIMIT' || code === 'CONTEXT_EXHAUSTED') return 'capacity'
  if (code.includes('DEPENDENCY')) return 'dependency'
  if (code.includes('REVIEW')) return 'review'
  return 'technical'
}

export function recommendedFailureAction(code: string): string {
  if (code === 'AUTH_FAILURE') return 'Repair authentication in the worker runner environment, then record a successful live invocation.'
  if (code === 'DEPENDENCY_BLOCKED') return 'Complete or explicitly resolve the listed prerequisite before returning the package to READY.'
  if (code === 'REVIEW_FAILURE' || code === 'REVIEW_STATE_UNRECORDED') return 'Record the independent review outcome and address any requested changes.'
  if (code === 'RATE_LIMIT' || code === 'CONTEXT_EXHAUSTED' || code === 'ORCHESTRA_CAPACITY_RISK') return 'Wait for or verify fresh capacity, then retry only when the worker is eligible.'
  if (code === 'CI_FAILURE') return 'Open the referenced attempt or pull request, repair the failed check, and rerun validation.'
  if (code === 'PRESERVATION_MISMATCH') return 'Reconcile every unexplained Registry record before dispatch or restart.'
  return 'Inspect the triggering Registry event and evidence, repair the recorded cause, then retry through the normal lifecycle.'
}

export function visibleReviews(snapshot: FactoryControlSnapshot): ReviewDisplayItem[] {
  const explicit = snapshot.reviews.map(review => ({ ...review, source: 'registry_review' as const }))
  const represented = new Set(explicit.map(review => review.packageId))
  const derived = snapshot.features.flatMap(feature => feature.packages).flatMap(item => {
    if (item.state !== 'VERIFY_REVIEW' || represented.has(item.id)) return []
    const latestAttempt = item.attempts.find(attempt => attempt.number === item.attemptNumber) ?? item.attempts.at(-1)
    const state: ReviewDisplayItem['state'] = item.reviewState ?? 'unrecorded'
    return [{
      id: `package-review-${item.id}`,
      packageId: item.id,
      implementerWorkerId: latestAttempt?.workerId ?? item.ownerWorkerId,
      eligibleReviewerIds: [],
      assignedReviewerId: null,
      requestedAt: null,
      state,
      findings: [],
      changesRequested: item.reviewState === 'changes_requested' && item.blockReason ? [item.blockReason] : [],
      approvalEvidence: item.evidence.filter(evidence => evidence.kind === 'review'),
      source: 'package_state' as const,
    }]
  })
  return [...explicit, ...derived]
}

export function visibleAttention(snapshot: FactoryControlSnapshot): AttentionDisplayItem[] {
  const explicit = snapshot.failures.filter(failure => failure.requiresHuman).map(failure => ({ ...failure, source: 'registry_failure' as const }))
  const represented = new Set(explicit.map(failure => `${failure.packageId ?? ''}:${failure.code}`))
  const structuredFailureKeys = new Set(snapshot.failures.map(failure => `${failure.packageId ?? ''}:${failure.code}`))
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
    if (!code || represented.has(`${item.id}:${code}`) || structuredFailureKeys.has(`${item.id}:${code}`)) return []
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
