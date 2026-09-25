export const FACTORY_SNAPSHOT_SCHEMA_VERSION = 2 as const

export type FactoryState = 'ON_DECK' | 'READY' | 'ACTIVE' | 'VERIFY_REVIEW' | 'BLOCKED' | 'DONE'
export type HealthState = 'healthy' | 'constrained' | 'offline'
export type ServiceState = 'healthy' | 'degraded' | 'offline' | 'unknown'
export type AuthenticationState = 'valid' | 'invalid' | 'unknown'
export type CapacityState = 'normal' | 'caution' | 'checkpoint' | 'hard_stop' | 'limited' | 'unknown'
export type CapacitySource = 'provider_reported' | 'factory_measured' | 'inferred' | 'unknown'
export type ReviewState = 'waiting' | 'assigned' | 'changes_requested' | 'approved'
export type EventKind = 'READY' | 'CLAIMED' | 'LAUNCHED' | 'HEARTBEAT' | 'VALIDATION' | 'REVIEW' | 'FAILURE' | 'RETRY' | 'DONE' | 'LEASE_RELEASED' | 'LEASE_EXPIRED'

export interface FactoryEvidence {
  id: string
  kind: 'commit' | 'check' | 'test' | 'review' | 'artifact' | 'screenshot'
  label: string
  url: string | null
  recordedAt: string
}

export interface FactoryLease {
  id: string
  workerId: string
  acquiredAt: string
  expiresAt: string
}

export interface FactoryAttempt {
  id: string
  number: number
  workerId: string | null
  startedAt: string
  endedAt: string | null
  outcome: 'active' | 'succeeded' | 'failed' | 'blocked' | 'cancelled' | 'unknown'
  branch: string | null
  commitSha: string | null
  pullRequestUrl: string | null
  evidence: FactoryEvidence[]
}

export interface FactoryPackage {
  id: string
  featureId: string
  title: string
  kind: 'PARENT' | 'TEST' | 'REVIEW' | 'EVALUATION'
  priority: number
  lane: string | null
  state: FactoryState
  dependencies: string[]
  requiredCapabilities: string[]
  ownerWorkerId: string | null
  currentLease: FactoryLease | null
  attemptNumber: number
  elapsedRuntimeSeconds: number
  branch: string | null
  pullRequestUrl: string | null
  reviewState: ReviewState | null
  failureCode: string | null
  blockReason: string | null
  acceptanceCriteria: string[]
  evidence: FactoryEvidence[]
  attempts: FactoryAttempt[]
}

export interface FactoryFeature {
  id: string
  title: string
  description: string
  priority: number
  state: FactoryState
  packages: FactoryPackage[]
}

export interface FactoryWorker {
  id: string
  displayName: string
  role: 'ORCHESTRA' | 'IMPLEMENTER' | 'REVIEWER'
  provider: string | null
  model: string | null
  health: HealthState
  serviceState: ServiceState
  authenticationState: AuthenticationState
  heartbeatAt: string | null
  currentPackageId: string | null
  activeLease: FactoryLease | null
  currentAttempt: number | null
  approvedCapabilities: string[]
  approvedLanes: string[]
  productiveRuntimeSeconds: number
  idleSeconds: number
  blockedSeconds: number
  recentTaskIds: string[]
  recentFailureIds: string[]
  capacityState: CapacityState
}

export interface FactoryReview {
  id: string
  packageId: string
  implementerWorkerId: string
  eligibleReviewerIds: string[]
  assignedReviewerId: string | null
  requestedAt: string
  state: ReviewState
  findings: string[]
  changesRequested: string[]
  approvalEvidence: FactoryEvidence[]
}

export interface CapacityMeasurement {
  inputTokens: number | null
  outputTokens: number | null
  cacheReadTokens: number | null
  cacheWriteTokens: number | null
  requestCount: number
  durationSeconds: number
  completedTasks: number
}

export interface FactoryCapacityScope {
  id: string
  workerId: string
  label: string
  source: CapacitySource
  observedAt: string | null
  state: CapacityState
  usedPercent: number | null
  resetAt: string | null
  rolling24Hours: CapacityMeasurement
  rolling7Days: CapacityMeasurement
  averageTokensPerTask: number | null
  outputTokensPerHour: number | null
  productiveRuntimeSeconds: number
  reviewThroughput: number
  inferredCeilingTokens: number | null
  limitHitCount: number
  lastLimitHitAt: string | null
}

export interface FactoryUsageSourceObservation {
  sourceType: 'CLI_JSON' | 'CLI_STREAM_JSON' | 'TRANSCRIPT'
  observedAt: string
}

export interface FactoryUsageInvocation {
  id: string
  workerId: string
  accountLabel: string
  sessionId: string
  packageId: string | null
  attemptId: string | null
  observationClass: 'AUTONOMOUS' | 'DIAGNOSTIC' | 'LEGACY_UNCLASSIFIED'
  observedAt: string
  modelDiagnostic: string | null
  inputTokens: number | null
  outputTokens: number | null
  cacheReadTokens: number | null
  cacheWriteTokens: number | null
  durationSeconds: number | null
  outcome: 'SUCCEEDED' | 'FAILED' | 'LIMITED'
  limitSignal: string | null
  sources: FactoryUsageSourceObservation[]
}

export interface FactoryEvent {
  id: string
  kind: EventKind
  occurredAt: string
  featureId: string | null
  packageId: string | null
  attemptNumber: number | null
  workerId: string | null
  branch: string | null
  commitSha: string | null
  pullRequestUrl: string | null
  evidenceIds: string[]
  summary: string
}

export interface FactoryFailure {
  id: string
  code: string
  title: string
  detail: string
  severity: 'warning' | 'critical'
  occurredAt: string
  workerId: string | null
  packageId: string | null
  requiresHuman: boolean
}

export interface FactoryProjectionPayload {
  schemaVersion: typeof FACTORY_SNAPSHOT_SCHEMA_VERSION
  registryRevision: string
  generatedAt: string
  source: { kind: 'registry-projection'; projectionId: string }
  factory: {
    health: HealthState
    activeParentCount: number
    activeParentLimit: number
    orchestraReservePercent: number | null
    readyCount: number
    verifyReviewCount: number
    blockedCount: number
    attentionCount: number
  }
  reconciliation: {
    status: 'clean' | 'mismatch' | 'unknown'
    worktreeCount: number | null
    dirtyWorktreeCount: number | null
    unmergedBranchCount: number | null
    unexplainedRecordCount: number | null
    activeStaleLeaseCount: number | null
    observedAt: string | null
  }
  features: FactoryFeature[]
  workers: FactoryWorker[]
  reviews: FactoryReview[]
  capacity: FactoryCapacityScope[]
  usageInvocations: FactoryUsageInvocation[]
  events: FactoryEvent[]
  failures: FactoryFailure[]
}

export interface FactoryControlSnapshot extends FactoryProjectionPayload {
  verification: { status: 'verified'; algorithm: 'HMAC-SHA-256'; verifiedAt: string }
}

type JsonObject = Record<string, unknown>

function object(value: unknown, path: string): JsonObject {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error(`${path} must be an object.`)
  return value as JsonObject
}
function string(value: unknown, path: string): string {
  if (typeof value !== 'string') throw new Error(`${path} must be a string.`)
  return value
}
function nullableString(value: unknown, path: string): string | null {
  return value === null ? null : string(value, path)
}
function number(value: unknown, path: string): number {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < 0) throw new Error(`${path} must be a non-negative number.`)
  return value
}
function nullableNumber(value: unknown, path: string): number | null {
  return value === null ? null : number(value, path)
}
function boolean(value: unknown, path: string): boolean {
  if (typeof value !== 'boolean') throw new Error(`${path} must be a boolean.`)
  return value
}
function timestamp(value: unknown, path: string): string {
  const result = string(value, path)
  if (Number.isNaN(Date.parse(result))) throw new Error(`${path} must be an ISO timestamp.`)
  return result
}
function nullableTimestamp(value: unknown, path: string): string | null {
  return value === null ? null : timestamp(value, path)
}
function oneOf<const T extends readonly string[]>(value: unknown, options: T, path: string): T[number] {
  if (typeof value !== 'string' || !options.includes(value)) throw new Error(`${path} has an unsupported value.`)
  return value as T[number]
}
function strings(value: unknown, path: string): string[] {
  if (!Array.isArray(value)) throw new Error(`${path} must be an array.`)
  return value.map((item, index) => string(item, `${path}[${index}]`))
}
function list<T>(value: unknown, path: string, parse: (value: unknown, path: string) => T): T[] {
  if (!Array.isArray(value)) throw new Error(`${path} must be an array.`)
  return value.map((item, index) => parse(item, `${path}[${index}]`))
}

const factoryStates = ['ON_DECK', 'READY', 'ACTIVE', 'VERIFY_REVIEW', 'BLOCKED', 'DONE'] as const
const healthStates = ['healthy', 'constrained', 'offline'] as const
const capacityStates = ['normal', 'caution', 'checkpoint', 'hard_stop', 'limited', 'unknown'] as const

function parseEvidence(value: unknown, path: string): FactoryEvidence {
  const v = object(value, path)
  return { id: string(v.id, `${path}.id`), kind: oneOf(v.kind, ['commit', 'check', 'test', 'review', 'artifact', 'screenshot'] as const, `${path}.kind`), label: string(v.label, `${path}.label`), url: nullableString(v.url, `${path}.url`), recordedAt: timestamp(v.recordedAt, `${path}.recordedAt`) }
}
function parseLease(value: unknown, path: string): FactoryLease {
  const v = object(value, path)
  return { id: string(v.id, `${path}.id`), workerId: string(v.workerId, `${path}.workerId`), acquiredAt: timestamp(v.acquiredAt, `${path}.acquiredAt`), expiresAt: timestamp(v.expiresAt, `${path}.expiresAt`) }
}
function parseNullableLease(value: unknown, path: string): FactoryLease | null { return value === null ? null : parseLease(value, path) }
function parseAttempt(value: unknown, path: string): FactoryAttempt {
  const v = object(value, path)
  return { id: string(v.id, `${path}.id`), number: number(v.number, `${path}.number`), workerId: nullableString(v.workerId, `${path}.workerId`), startedAt: timestamp(v.startedAt, `${path}.startedAt`), endedAt: nullableTimestamp(v.endedAt, `${path}.endedAt`), outcome: oneOf(v.outcome, ['active', 'succeeded', 'failed', 'blocked', 'cancelled', 'unknown'] as const, `${path}.outcome`), branch: nullableString(v.branch, `${path}.branch`), commitSha: nullableString(v.commitSha, `${path}.commitSha`), pullRequestUrl: nullableString(v.pullRequestUrl, `${path}.pullRequestUrl`), evidence: list(v.evidence, `${path}.evidence`, parseEvidence) }
}
function parsePackage(value: unknown, path: string): FactoryPackage {
  const v = object(value, path)
  return {
    id: string(v.id, `${path}.id`), featureId: string(v.featureId, `${path}.featureId`), title: string(v.title, `${path}.title`), kind: oneOf(v.kind, ['PARENT', 'TEST', 'REVIEW', 'EVALUATION'] as const, `${path}.kind`), priority: number(v.priority, `${path}.priority`), lane: nullableString(v.lane, `${path}.lane`), state: oneOf(v.state, factoryStates, `${path}.state`), dependencies: strings(v.dependencies, `${path}.dependencies`), requiredCapabilities: strings(v.requiredCapabilities, `${path}.requiredCapabilities`), ownerWorkerId: nullableString(v.ownerWorkerId, `${path}.ownerWorkerId`), currentLease: parseNullableLease(v.currentLease, `${path}.currentLease`), attemptNumber: number(v.attemptNumber, `${path}.attemptNumber`), elapsedRuntimeSeconds: number(v.elapsedRuntimeSeconds, `${path}.elapsedRuntimeSeconds`), branch: nullableString(v.branch, `${path}.branch`), pullRequestUrl: nullableString(v.pullRequestUrl, `${path}.pullRequestUrl`), reviewState: v.reviewState === null ? null : oneOf(v.reviewState, ['waiting', 'assigned', 'changes_requested', 'approved'] as const, `${path}.reviewState`), failureCode: nullableString(v.failureCode, `${path}.failureCode`), blockReason: nullableString(v.blockReason, `${path}.blockReason`), acceptanceCriteria: strings(v.acceptanceCriteria, `${path}.acceptanceCriteria`), evidence: list(v.evidence, `${path}.evidence`, parseEvidence), attempts: list(v.attempts, `${path}.attempts`, parseAttempt),
  }
}
function parseFeature(value: unknown, path: string): FactoryFeature {
  const v = object(value, path)
  return { id: string(v.id, `${path}.id`), title: string(v.title, `${path}.title`), description: string(v.description, `${path}.description`), priority: number(v.priority, `${path}.priority`), state: oneOf(v.state, factoryStates, `${path}.state`), packages: list(v.packages, `${path}.packages`, parsePackage) }
}
function parseWorker(value: unknown, path: string): FactoryWorker {
  const v = object(value, path)
  return {
    id: string(v.id, `${path}.id`), displayName: string(v.displayName, `${path}.displayName`), role: oneOf(v.role, ['ORCHESTRA', 'IMPLEMENTER', 'REVIEWER'] as const, `${path}.role`), provider: nullableString(v.provider, `${path}.provider`), model: nullableString(v.model, `${path}.model`), health: oneOf(v.health, healthStates, `${path}.health`), serviceState: oneOf(v.serviceState, ['healthy', 'degraded', 'offline', 'unknown'] as const, `${path}.serviceState`), authenticationState: oneOf(v.authenticationState, ['valid', 'invalid', 'unknown'] as const, `${path}.authenticationState`), heartbeatAt: nullableTimestamp(v.heartbeatAt, `${path}.heartbeatAt`), currentPackageId: nullableString(v.currentPackageId, `${path}.currentPackageId`), activeLease: parseNullableLease(v.activeLease, `${path}.activeLease`), currentAttempt: nullableNumber(v.currentAttempt, `${path}.currentAttempt`), approvedCapabilities: strings(v.approvedCapabilities, `${path}.approvedCapabilities`), approvedLanes: strings(v.approvedLanes, `${path}.approvedLanes`), productiveRuntimeSeconds: number(v.productiveRuntimeSeconds, `${path}.productiveRuntimeSeconds`), idleSeconds: number(v.idleSeconds, `${path}.idleSeconds`), blockedSeconds: number(v.blockedSeconds, `${path}.blockedSeconds`), recentTaskIds: strings(v.recentTaskIds, `${path}.recentTaskIds`), recentFailureIds: strings(v.recentFailureIds, `${path}.recentFailureIds`), capacityState: oneOf(v.capacityState, capacityStates, `${path}.capacityState`),
  }
}
function parseReview(value: unknown, path: string): FactoryReview {
  const v = object(value, path)
  return { id: string(v.id, `${path}.id`), packageId: string(v.packageId, `${path}.packageId`), implementerWorkerId: string(v.implementerWorkerId, `${path}.implementerWorkerId`), eligibleReviewerIds: strings(v.eligibleReviewerIds, `${path}.eligibleReviewerIds`), assignedReviewerId: nullableString(v.assignedReviewerId, `${path}.assignedReviewerId`), requestedAt: timestamp(v.requestedAt, `${path}.requestedAt`), state: oneOf(v.state, ['waiting', 'assigned', 'changes_requested', 'approved'] as const, `${path}.state`), findings: strings(v.findings, `${path}.findings`), changesRequested: strings(v.changesRequested, `${path}.changesRequested`), approvalEvidence: list(v.approvalEvidence, `${path}.approvalEvidence`, parseEvidence) }
}
function parseMeasurement(value: unknown, path: string): CapacityMeasurement {
  const v = object(value, path)
  return { inputTokens: nullableNumber(v.inputTokens, `${path}.inputTokens`), outputTokens: nullableNumber(v.outputTokens, `${path}.outputTokens`), cacheReadTokens: nullableNumber(v.cacheReadTokens, `${path}.cacheReadTokens`), cacheWriteTokens: nullableNumber(v.cacheWriteTokens, `${path}.cacheWriteTokens`), requestCount: number(v.requestCount, `${path}.requestCount`), durationSeconds: number(v.durationSeconds, `${path}.durationSeconds`), completedTasks: number(v.completedTasks, `${path}.completedTasks`) }
}
function parseCapacity(value: unknown, path: string): FactoryCapacityScope {
  const v = object(value, path)
  return { id: string(v.id, `${path}.id`), workerId: string(v.workerId, `${path}.workerId`), label: string(v.label, `${path}.label`), source: oneOf(v.source, ['provider_reported', 'factory_measured', 'inferred', 'unknown'] as const, `${path}.source`), observedAt: nullableTimestamp(v.observedAt, `${path}.observedAt`), state: oneOf(v.state, capacityStates, `${path}.state`), usedPercent: nullableNumber(v.usedPercent, `${path}.usedPercent`), resetAt: nullableTimestamp(v.resetAt, `${path}.resetAt`), rolling24Hours: parseMeasurement(v.rolling24Hours, `${path}.rolling24Hours`), rolling7Days: parseMeasurement(v.rolling7Days, `${path}.rolling7Days`), averageTokensPerTask: nullableNumber(v.averageTokensPerTask, `${path}.averageTokensPerTask`), outputTokensPerHour: nullableNumber(v.outputTokensPerHour, `${path}.outputTokensPerHour`), productiveRuntimeSeconds: number(v.productiveRuntimeSeconds, `${path}.productiveRuntimeSeconds`), reviewThroughput: number(v.reviewThroughput, `${path}.reviewThroughput`), inferredCeilingTokens: nullableNumber(v.inferredCeilingTokens, `${path}.inferredCeilingTokens`), limitHitCount: number(v.limitHitCount, `${path}.limitHitCount`), lastLimitHitAt: nullableTimestamp(v.lastLimitHitAt, `${path}.lastLimitHitAt`) }
}
function parseUsageSource(value: unknown, path: string): FactoryUsageSourceObservation {
  const v = object(value, path)
  return { sourceType: oneOf(v.sourceType, ['CLI_JSON', 'CLI_STREAM_JSON', 'TRANSCRIPT'] as const, `${path}.sourceType`), observedAt: timestamp(v.observedAt, `${path}.observedAt`) }
}
function parseUsageInvocation(value: unknown, path: string): FactoryUsageInvocation {
  const v = object(value, path)
  const observationClass = oneOf(v.observationClass, ['AUTONOMOUS', 'DIAGNOSTIC', 'LEGACY_UNCLASSIFIED'] as const, `${path}.observationClass`)
  const packageId = nullableString(v.packageId, `${path}.packageId`)
  const attemptId = nullableString(v.attemptId, `${path}.attemptId`)
  if ((observationClass === 'AUTONOMOUS' && (!packageId || !attemptId)) || (observationClass === 'DIAGNOSTIC' && (packageId !== null || attemptId !== null))) throw new Error(`${path} has invalid provenance.`)
  const sources = list(v.sources, `${path}.sources`, parseUsageSource)
  if (!sources.length) throw new Error(`${path}.sources must contain an observation.`)
  return { id: string(v.id, `${path}.id`), workerId: string(v.workerId, `${path}.workerId`), accountLabel: string(v.accountLabel, `${path}.accountLabel`), sessionId: string(v.sessionId, `${path}.sessionId`), packageId, attemptId, observationClass, observedAt: timestamp(v.observedAt, `${path}.observedAt`), modelDiagnostic: nullableString(v.modelDiagnostic, `${path}.modelDiagnostic`), inputTokens: nullableNumber(v.inputTokens, `${path}.inputTokens`), outputTokens: nullableNumber(v.outputTokens, `${path}.outputTokens`), cacheReadTokens: nullableNumber(v.cacheReadTokens, `${path}.cacheReadTokens`), cacheWriteTokens: nullableNumber(v.cacheWriteTokens, `${path}.cacheWriteTokens`), durationSeconds: nullableNumber(v.durationSeconds, `${path}.durationSeconds`), outcome: oneOf(v.outcome, ['SUCCEEDED', 'FAILED', 'LIMITED'] as const, `${path}.outcome`), limitSignal: nullableString(v.limitSignal, `${path}.limitSignal`), sources }
}
function parseEvent(value: unknown, path: string): FactoryEvent {
  const v = object(value, path)
  return { id: string(v.id, `${path}.id`), kind: oneOf(v.kind, ['READY', 'CLAIMED', 'LAUNCHED', 'HEARTBEAT', 'VALIDATION', 'REVIEW', 'FAILURE', 'RETRY', 'DONE', 'LEASE_RELEASED', 'LEASE_EXPIRED'] as const, `${path}.kind`), occurredAt: timestamp(v.occurredAt, `${path}.occurredAt`), featureId: nullableString(v.featureId, `${path}.featureId`), packageId: nullableString(v.packageId, `${path}.packageId`), attemptNumber: nullableNumber(v.attemptNumber, `${path}.attemptNumber`), workerId: nullableString(v.workerId, `${path}.workerId`), branch: nullableString(v.branch, `${path}.branch`), commitSha: nullableString(v.commitSha, `${path}.commitSha`), pullRequestUrl: nullableString(v.pullRequestUrl, `${path}.pullRequestUrl`), evidenceIds: strings(v.evidenceIds, `${path}.evidenceIds`), summary: string(v.summary, `${path}.summary`) }
}
function parseFailure(value: unknown, path: string): FactoryFailure {
  const v = object(value, path)
  return { id: string(v.id, `${path}.id`), code: string(v.code, `${path}.code`), title: string(v.title, `${path}.title`), detail: string(v.detail, `${path}.detail`), severity: oneOf(v.severity, ['warning', 'critical'] as const, `${path}.severity`), occurredAt: timestamp(v.occurredAt, `${path}.occurredAt`), workerId: nullableString(v.workerId, `${path}.workerId`), packageId: nullableString(v.packageId, `${path}.packageId`), requiresHuman: boolean(v.requiresHuman, `${path}.requiresHuman`) }
}

export function parseFactoryProjection(value: unknown): FactoryProjectionPayload {
  const v = object(value, 'snapshot')
  if (v.schemaVersion !== FACTORY_SNAPSHOT_SCHEMA_VERSION) throw new Error('snapshot.schemaVersion is unsupported.')
  const source = object(v.source, 'snapshot.source')
  const factory = object(v.factory, 'snapshot.factory')
  const reconciliation = object(v.reconciliation, 'snapshot.reconciliation')
  const projection: FactoryProjectionPayload = {
    schemaVersion: FACTORY_SNAPSHOT_SCHEMA_VERSION,
    registryRevision: string(v.registryRevision, 'snapshot.registryRevision'),
    generatedAt: timestamp(v.generatedAt, 'snapshot.generatedAt'),
    source: { kind: oneOf(source.kind, ['registry-projection'] as const, 'snapshot.source.kind'), projectionId: string(source.projectionId, 'snapshot.source.projectionId') },
    factory: { health: oneOf(factory.health, healthStates, 'snapshot.factory.health'), activeParentCount: number(factory.activeParentCount, 'snapshot.factory.activeParentCount'), activeParentLimit: number(factory.activeParentLimit, 'snapshot.factory.activeParentLimit'), orchestraReservePercent: nullableNumber(factory.orchestraReservePercent, 'snapshot.factory.orchestraReservePercent'), readyCount: number(factory.readyCount, 'snapshot.factory.readyCount'), verifyReviewCount: number(factory.verifyReviewCount, 'snapshot.factory.verifyReviewCount'), blockedCount: number(factory.blockedCount, 'snapshot.factory.blockedCount'), attentionCount: number(factory.attentionCount, 'snapshot.factory.attentionCount') },
    reconciliation: { status: oneOf(reconciliation.status, ['clean', 'mismatch', 'unknown'] as const, 'snapshot.reconciliation.status'), worktreeCount: nullableNumber(reconciliation.worktreeCount, 'snapshot.reconciliation.worktreeCount'), dirtyWorktreeCount: nullableNumber(reconciliation.dirtyWorktreeCount, 'snapshot.reconciliation.dirtyWorktreeCount'), unmergedBranchCount: nullableNumber(reconciliation.unmergedBranchCount, 'snapshot.reconciliation.unmergedBranchCount'), unexplainedRecordCount: nullableNumber(reconciliation.unexplainedRecordCount, 'snapshot.reconciliation.unexplainedRecordCount'), activeStaleLeaseCount: nullableNumber(reconciliation.activeStaleLeaseCount, 'snapshot.reconciliation.activeStaleLeaseCount'), observedAt: nullableTimestamp(reconciliation.observedAt, 'snapshot.reconciliation.observedAt') },
    features: list(v.features, 'snapshot.features', parseFeature), workers: list(v.workers, 'snapshot.workers', parseWorker), reviews: list(v.reviews, 'snapshot.reviews', parseReview), capacity: list(v.capacity, 'snapshot.capacity', parseCapacity), usageInvocations: list(v.usageInvocations, 'snapshot.usageInvocations', parseUsageInvocation), events: list(v.events, 'snapshot.events', parseEvent), failures: list(v.failures, 'snapshot.failures', parseFailure),
  }
  const workers = new Set(projection.workers.map(worker => worker.id))
  if (workers.size !== projection.workers.length) throw new Error('snapshot worker IDs must be unique.')
  const featureIds = new Set<string>()
  const packageIds = new Set<string>()
  const attemptsByPackage = new Map<string, Map<string, string | null>>()
  for (const feature of projection.features) {
    if (featureIds.has(feature.id)) throw new Error(`snapshot Feature ID ${feature.id} is duplicated.`)
    featureIds.add(feature.id)
    for (const item of feature.packages) {
      if (item.featureId !== feature.id) throw new Error(`snapshot package ${item.id} has invalid Feature provenance.`)
      if (packageIds.has(item.id)) throw new Error(`snapshot package ID ${item.id} is duplicated.`)
      packageIds.add(item.id)
      attemptsByPackage.set(item.id, new Map(item.attempts.map(attempt => [attempt.id, attempt.workerId])))
    }
  }
  const packages = projection.features.flatMap(feature => feature.packages)
  for (const item of packages) {
    for (const dependency of item.dependencies) if (!packageIds.has(dependency)) throw new Error(`snapshot package ${item.id} references unknown dependency ${dependency}.`)
    if (item.ownerWorkerId !== null && !workers.has(item.ownerWorkerId)) throw new Error(`snapshot package ${item.id} references an unknown owner.`)
    if (item.currentLease !== null && !workers.has(item.currentLease.workerId)) throw new Error(`snapshot package ${item.id} lease references an unknown worker.`)
  }
  for (const worker of projection.workers) {
    if (worker.currentPackageId !== null && !packageIds.has(worker.currentPackageId)) throw new Error(`snapshot worker ${worker.id} references an unknown package.`)
  }
  for (const review of projection.reviews) {
    if (!packageIds.has(review.packageId)) throw new Error(`snapshot review ${review.id} references an unknown package.`)
    if (!workers.has(review.implementerWorkerId) || (review.assignedReviewerId !== null && !workers.has(review.assignedReviewerId)) || review.eligibleReviewerIds.some(id => !workers.has(id))) throw new Error(`snapshot review ${review.id} references an unknown worker.`)
    if (review.assignedReviewerId === review.implementerWorkerId) throw new Error(`snapshot review ${review.id} violates review independence.`)
    if (review.state === 'approved' && (review.assignedReviewerId === null || review.approvalEvidence.length === 0)) throw new Error(`snapshot review ${review.id} is missing approval evidence.`)
    if (review.state === 'changes_requested' && review.changesRequested.length === 0) throw new Error(`snapshot review ${review.id} is missing requested changes.`)
  }
  for (const scope of projection.capacity) if (!workers.has(scope.workerId)) throw new Error(`snapshot capacity scope ${scope.id} references an unknown worker.`)
  for (const failure of projection.failures) {
    if (failure.packageId !== null && !packageIds.has(failure.packageId)) throw new Error(`snapshot failure ${failure.id} references an unknown package.`)
    if (failure.workerId !== null && !workers.has(failure.workerId)) throw new Error(`snapshot failure ${failure.id} references an unknown worker.`)
  }
  const count = (state: FactoryState) => packages.filter(item => item.state === state).length
  if (projection.factory.activeParentCount !== packages.filter(item => item.kind === 'PARENT' && item.state === 'ACTIVE').length) throw new Error('snapshot.factory.activeParentCount does not match this Registry revision.')
  if (projection.factory.readyCount !== count('READY')) throw new Error('snapshot.factory.readyCount does not match this Registry revision.')
  if (projection.factory.verifyReviewCount !== count('VERIFY_REVIEW')) throw new Error('snapshot.factory.verifyReviewCount does not match this Registry revision.')
  if (projection.factory.blockedCount !== count('BLOCKED')) throw new Error('snapshot.factory.blockedCount does not match this Registry revision.')
  if (projection.factory.attentionCount !== projection.failures.filter(failure => failure.requiresHuman).length) throw new Error('snapshot.factory.attentionCount does not match this Registry revision.')
  for (const invocation of projection.usageInvocations) {
    if (!workers.has(invocation.workerId)) throw new Error(`snapshot usage invocation ${invocation.id} references an unknown worker.`)
    if (invocation.observationClass === 'AUTONOMOUS') {
      const attemptWorkerId = attemptsByPackage.get(invocation.packageId!)?.get(invocation.attemptId!)
      if (attemptWorkerId === undefined) throw new Error(`snapshot usage invocation ${invocation.id} references an unknown package attempt.`)
      if (attemptWorkerId !== null && attemptWorkerId !== invocation.workerId) throw new Error(`snapshot usage invocation ${invocation.id} does not match the attempt worker.`)
    }
  }
  return projection
}

export function parseFactoryControlSnapshot(value: unknown): FactoryControlSnapshot {
  const v = object(value, 'snapshot')
  const verification = object(v.verification, 'snapshot.verification')
  return { ...parseFactoryProjection(v), verification: { status: oneOf(verification.status, ['verified'] as const, 'snapshot.verification.status'), algorithm: oneOf(verification.algorithm, ['HMAC-SHA-256'] as const, 'snapshot.verification.algorithm'), verifiedAt: timestamp(verification.verifiedAt, 'snapshot.verification.verifiedAt') } }
}

export function formatFactoryState(state: FactoryState): string {
  return state === 'VERIFY_REVIEW' ? 'VERIFY / REVIEW' : state.replace('_', ' ')
}

export function formatDuration(seconds: number): string {
  if (seconds < 60) return `${Math.floor(seconds)}s`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`
  const hours = Math.floor(seconds / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  return minutes ? `${hours}h ${minutes}m` : `${hours}h`
}

export function formatRelativeTime(iso: string | null, now = new Date()): string {
  if (!iso) return 'Unknown'
  const seconds = Math.max(0, Math.floor((now.getTime() - Date.parse(iso)) / 1000))
  if (seconds < 60) return `${seconds}s ago`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`
  if (seconds < 172800) return `${Math.floor(seconds / 3600)}h ago`
  return `${Math.floor(seconds / 86400)}d ago`
}

export function safeExternalUrl(value: string): string | null {
  try {
    const url = new URL(value)
    if ((url.protocol !== 'http:' && url.protocol !== 'https:') || url.username || url.password) return null
    return url.toString()
  } catch {
    return null
  }
}
