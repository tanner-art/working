import type { FactoryControlSnapshot } from './factoryControl'
import { factoryControlFixture } from './factoryControl.fixture'

/**
 * One coherent Registry projection shaped from the preserved SOAK-001 canary.
 * It deliberately reflects the sparse projection that exposed the A1 gaps:
 * package state carries the rejected review while structured review/failure rows
 * are absent, and diagnostic health conflicts with incomplete worker evidence.
 */
export const preservedCanaryProjectionFixture: FactoryControlSnapshot = (() => {
  const snapshot = structuredClone(factoryControlFixture)
  snapshot.registryRevision = 'registry-preserved-soak-001'
  snapshot.source.projectionId = 'projection-preserved-soak-001'
  snapshot.reviews = snapshot.reviews.filter(review => review.packageId !== 'SOAK-001-A')
  snapshot.failures = snapshot.failures.filter(failure => failure.packageId !== 'SOAK-001-A')

  const agentA = snapshot.workers.find(worker => worker.id === 'agent-a')
  if (agentA) {
    agentA.health = 'healthy'
    agentA.serviceState = 'unknown'
  }
  const claude = snapshot.workers.find(worker => worker.id === 'claude')
  if (claude) {
    claude.health = 'healthy'
    claude.authenticationState = 'unknown'
  }
  const orchestra = snapshot.workers.find(worker => worker.id === 'orchestra')
  if (orchestra) {
    orchestra.health = 'healthy'
    orchestra.heartbeatAt = '2026-09-24T18:20:00Z'
  }
  return snapshot
})()

/** Live projection shape observed for SOAK-001: review evidence exists, but its outcome is absent. */
export const actualSoakCanaryProjectionFixture: FactoryControlSnapshot = (() => {
  const snapshot = structuredClone(preservedCanaryProjectionFixture)
  snapshot.registryRevision = 'registry-observed-soak-001'
  snapshot.source.projectionId = 'projection-observed-soak-001'
  snapshot.reviews = snapshot.reviews.filter(review => review.packageId !== 'SOAK-001-A')
  snapshot.failures = snapshot.failures.filter(failure => failure.packageId !== 'SOAK-001-A')

  const soakFeature = snapshot.features.find(feature => feature.id === 'SOAK-001')
  const soakPackage = soakFeature?.packages.find(item => item.id === 'SOAK-001-A')
  if (soakPackage) {
    soakPackage.reviewState = null
    soakPackage.failureCode = null
    soakPackage.blockReason = null
    soakPackage.evidence = [{
      id: 'ev-soak-review',
      kind: 'review',
      label: 'Independent canary review evidence',
      url: 'https://example.test/evidence/soak-001-review',
      recordedAt: '2026-09-24T18:00:00Z',
    }]
  }
  const reviewPackage = soakFeature?.packages.find(item => item.id === 'SOAK-001-REVIEW')
  if (reviewPackage) reviewPackage.reviewState = null
  return snapshot
})()
