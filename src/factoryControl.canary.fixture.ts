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
