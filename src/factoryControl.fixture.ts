import type { CapacityMeasurement, FactoryControlSnapshot } from './factoryControl'

const emptyMeasurement: CapacityMeasurement = {
  inputTokens: 0, outputTokens: 0, cacheReadTokens: 0, cacheWriteTokens: 0,
  requestCount: 0, durationSeconds: 0, completedTasks: 0,
}

export const factoryControlFixture: FactoryControlSnapshot = {
  schemaVersion: 1,
  registryRevision: 'registry-1842',
  generatedAt: '2026-09-24T18:30:00Z',
  source: { kind: 'registry-projection', projectionId: 'projection-1842' },
  verification: { status: 'verified', algorithm: 'HMAC-SHA-256', verifiedAt: '2026-09-24T18:30:01Z' },
  factory: { health: 'healthy', activeParentCount: 1, activeParentLimit: 3, orchestraReservePercent: 64, readyCount: 1, verifyReviewCount: 1, blockedCount: 1, attentionCount: 1 },
  reconciliation: { status: 'clean', worktreeCount: 33, dirtyWorktreeCount: 8, unmergedBranchCount: 7, unexplainedRecordCount: 0, activeStaleLeaseCount: 0, observedAt: '2026-09-24T18:29:30Z' },
  features: [
    {
      id: 'CONTROL-001', title: 'Factory Control Center', description: 'One authenticated view of live Factory state.', priority: 100, state: 'ACTIVE',
      packages: [
        { id: 'CONTROL-UI', featureId: 'CONTROL-001', title: 'Read-only operations dashboard', priority: 100, lane: 'FEATURE', state: 'ACTIVE', dependencies: [], requiredCapabilities: ['react', 'accessibility'], ownerWorkerId: 'agent-b', currentLease: { id: 'lease-control-ui', workerId: 'agent-b', acquiredAt: '2026-09-24T18:10:00Z', expiresAt: '2026-09-24T19:10:00Z' }, attemptNumber: 1, elapsedRuntimeSeconds: 1200, branch: 'codex/factory-control-center', pullRequestUrl: null, reviewState: null, failureCode: null, blockReason: null, acceptanceCriteria: ['All required views read from one Registry projection.', 'The dashboard remains read-only.'], evidence: [{ id: 'ev-check', kind: 'check', label: 'Contract tests', url: null, recordedAt: '2026-09-24T18:25:00Z' }] },
        { id: 'CONTROL-ASSURANCE', featureId: 'CONTROL-001', title: 'Independent visibility review', priority: 95, lane: 'ASSURANCE', state: 'READY', dependencies: ['CONTROL-UI'], requiredCapabilities: ['review'], ownerWorkerId: null, currentLease: null, attemptNumber: 0, elapsedRuntimeSeconds: 0, branch: null, pullRequestUrl: null, reviewState: 'waiting', failureCode: null, blockReason: null, acceptanceCriteria: ['Implementer is not the sole reviewer.'], evidence: [] },
      ],
    },
    {
      id: 'SOAK-001', title: 'Controlled Factory canary', description: 'Observe one bounded package through review.', priority: 90, state: 'VERIFY_REVIEW',
      packages: [
        { id: 'SOAK-001-A', featureId: 'SOAK-001', title: 'Registry read-only reconciliation canary', priority: 90, lane: 'ASSURANCE', state: 'VERIFY_REVIEW', dependencies: [], requiredCapabilities: ['registry-read'], ownerWorkerId: null, currentLease: null, attemptNumber: 1, elapsedRuntimeSeconds: 468, branch: 'codex/soak-001', pullRequestUrl: 'https://github.com/example/threadline/pull/156', reviewState: 'changes_requested', failureCode: 'REVIEW_FAILURE', blockReason: 'Raw lease and mutation evidence is incomplete.', acceptanceCriteria: ['Reconcile without mutation.'], evidence: [{ id: 'ev-soak-log', kind: 'artifact', label: 'Canary evidence bundle', url: 'https://example.test/evidence/soak-001', recordedAt: '2026-09-24T17:50:00Z' }] },
      ],
    },
  ],
  workers: [
    { id: 'orchestra', displayName: 'Orchestra', role: 'ORCHESTRA', provider: 'OpenAI', model: 'GPT-5', health: 'healthy', serviceState: 'healthy', authenticationState: 'valid', heartbeatAt: '2026-09-24T18:29:40Z', currentPackageId: null, activeLease: null, currentAttempt: null, approvedCapabilities: ['coordination'], approvedLanes: [], productiveRuntimeSeconds: 4020, idleSeconds: 80, blockedSeconds: 0, recentTaskIds: ['SOAK-001-A'], recentFailureIds: [], capacityState: 'normal' },
    { id: 'agent-a', displayName: 'Agent A', role: 'IMPLEMENTER', provider: 'OpenAI', model: 'Codex', health: 'healthy', serviceState: 'healthy', authenticationState: 'valid', heartbeatAt: '2026-09-24T18:29:35Z', currentPackageId: null, activeLease: null, currentAttempt: null, approvedCapabilities: ['typescript', 'platform'], approvedLanes: ['FEATURE', 'PLATFORM'], productiveRuntimeSeconds: 7210, idleSeconds: 320, blockedSeconds: 0, recentTaskIds: ['RISK-004'], recentFailureIds: [], capacityState: 'normal' },
    { id: 'agent-b', displayName: 'Agent B', role: 'IMPLEMENTER', provider: 'OpenAI', model: 'Codex', health: 'healthy', serviceState: 'healthy', authenticationState: 'valid', heartbeatAt: '2026-09-24T18:29:55Z', currentPackageId: 'CONTROL-UI', activeLease: { id: 'lease-control-ui', workerId: 'agent-b', acquiredAt: '2026-09-24T18:10:00Z', expiresAt: '2026-09-24T19:10:00Z' }, currentAttempt: 1, approvedCapabilities: ['react', 'accessibility'], approvedLanes: ['FEATURE'], productiveRuntimeSeconds: 1200, idleSeconds: 0, blockedSeconds: 0, recentTaskIds: ['CONTROL-UI'], recentFailureIds: [], capacityState: 'normal' },
    { id: 'claude', displayName: 'Claude', role: 'REVIEWER', provider: 'Anthropic', model: 'Claude Code', health: 'healthy', serviceState: 'healthy', authenticationState: 'valid', heartbeatAt: '2026-09-24T18:29:20Z', currentPackageId: null, activeLease: null, currentAttempt: null, approvedCapabilities: ['review', 'assurance'], approvedLanes: ['ASSURANCE'], productiveRuntimeSeconds: 3880, idleSeconds: 240, blockedSeconds: 0, recentTaskIds: ['SOAK-001-A'], recentFailureIds: ['failure-soak-review'], capacityState: 'normal' },
  ],
  reviews: [
    { id: 'review-soak', packageId: 'SOAK-001-A', implementerWorkerId: 'agent-b', eligibleReviewerIds: ['agent-a', 'claude'], assignedReviewerId: 'claude', requestedAt: '2026-09-24T17:55:00Z', state: 'changes_requested', findings: ['The supplied bundle repeats derived lease counts without a raw audit.'], changesRequested: ['Attach the raw lease audit and canary-specific mutation log.'], approvalEvidence: [] },
    { id: 'review-control', packageId: 'CONTROL-ASSURANCE', implementerWorkerId: 'agent-b', eligibleReviewerIds: ['agent-a', 'claude'], assignedReviewerId: null, requestedAt: '2026-09-24T18:20:00Z', state: 'waiting', findings: [], changesRequested: [], approvalEvidence: [] },
  ],
  capacity: [
    { id: 'agent-a-short', workerId: 'agent-a', label: 'Short window', source: 'provider_reported', observedAt: '2026-09-24T18:29:00Z', state: 'normal', usedPercent: 0, resetAt: '2026-09-24T23:00:00Z', rolling24Hours: emptyMeasurement, rolling7Days: emptyMeasurement, averageTokensPerTask: null, outputTokensPerHour: null, productiveRuntimeSeconds: 7210, reviewThroughput: 1, inferredCeilingTokens: null, limitHitCount: 0, lastLimitHitAt: null },
    { id: 'agent-a-weekly', workerId: 'agent-a', label: 'Weekly window', source: 'provider_reported', observedAt: '2026-09-24T18:29:00Z', state: 'normal', usedPercent: 73, resetAt: '2026-09-30T00:00:00Z', rolling24Hours: emptyMeasurement, rolling7Days: emptyMeasurement, averageTokensPerTask: null, outputTokensPerHour: null, productiveRuntimeSeconds: 7210, reviewThroughput: 1, inferredCeilingTokens: null, limitHitCount: 0, lastLimitHitAt: null },
    { id: 'claude-measured', workerId: 'claude', label: 'Factory-measured consumption', source: 'factory_measured', observedAt: '2026-09-24T18:29:00Z', state: 'normal', usedPercent: null, resetAt: null, rolling24Hours: { inputTokens: 12450, outputTokens: 3240, cacheReadTokens: 18100, cacheWriteTokens: 2200, requestCount: 4, durationSeconds: 3880, completedTasks: 2 }, rolling7Days: { inputTokens: 55120, outputTokens: 12600, cacheReadTokens: 74200, cacheWriteTokens: 9080, requestCount: 18, durationSeconds: 15020, completedTasks: 9 }, averageTokensPerTask: 7524, outputTokensPerHour: 3006, productiveRuntimeSeconds: 3880, reviewThroughput: 2, inferredCeilingTokens: null, limitHitCount: 0, lastLimitHitAt: null },
  ],
  events: [
    { id: 'event-1', kind: 'CLAIMED', occurredAt: '2026-09-24T18:10:00Z', featureId: 'CONTROL-001', packageId: 'CONTROL-UI', attemptNumber: 1, workerId: 'agent-b', branch: 'codex/factory-control-center', commitSha: null, pullRequestUrl: null, evidenceIds: [], summary: 'Agent B claimed the dashboard package.' },
    { id: 'event-2', kind: 'REVIEW', occurredAt: '2026-09-24T18:00:00Z', featureId: 'SOAK-001', packageId: 'SOAK-001-A', attemptNumber: 1, workerId: 'claude', branch: 'codex/soak-001', commitSha: null, pullRequestUrl: 'https://github.com/example/threadline/pull/156', evidenceIds: ['ev-soak-log'], summary: 'Independent review requested raw lease and mutation evidence.' },
  ],
  failures: [
    { id: 'failure-soak-review', code: 'REVIEW_FAILURE', title: 'Canary evidence is incomplete', detail: 'Raw lease and mutation evidence must be attached before approval.', severity: 'warning', occurredAt: '2026-09-24T18:00:00Z', workerId: 'claude', packageId: 'SOAK-001-A', requiresHuman: true },
  ],
}
