import { describe, expect, it } from 'vitest'
import { factoryControlFixture } from './factoryControl.fixture'
import { actualSoakCanaryProjectionFixture, preservedCanaryProjectionFixture } from './factoryControl.canary.fixture'
import { capacitySummary, effectiveWorkerHealth, emptyQueueFilters, filterFactoryFeatures, packageIndex, visibleAttention, visibleReviews } from './buildDashboard'

describe('Factory Control Center view helpers', () => {
  it('filters packages while retaining feature-level organization', () => {
    const result = filterFactoryFeatures(factoryControlFixture.features, { ...emptyQueueFilters, state: 'READY' })
    expect(result).toHaveLength(1)
    expect(result[0].id).toBe('CONTROL-001')
    expect(result[0].packages.map(item => item.id)).toEqual(['CONTROL-ASSURANCE'])
  })

  it('supports worker and human-readable blocked reason filters', () => {
    expect(filterFactoryFeatures(factoryControlFixture.features, { ...emptyQueueFilters, worker: 'agent-b' })[0].packages).toHaveLength(1)
    expect(filterFactoryFeatures(factoryControlFixture.features, { ...emptyQueueFilters, blockedReason: 'raw lease' })[0].id).toBe('SOAK-001')
  })

  it('indexes packages and distinguishes capacity observation sources', () => {
    expect(packageIndex(factoryControlFixture.features).get('CONTROL-UI')?.title).toContain('dashboard')
    expect(capacitySummary(factoryControlFixture.capacity[1])).toContain('provider reported')
    expect(capacitySummary(factoryControlFixture.capacity[2])).toContain('measured over 24h')
  })

  it('keeps VERIFY / REVIEW packages visible when structured review rows are absent', () => {
    const reviews = visibleReviews(preservedCanaryProjectionFixture)
    expect(reviews.find(review => review.packageId === 'SOAK-001-A')).toMatchObject({
      state: 'changes_requested', source: 'package_state',
      changesRequested: ['Raw lease and mutation evidence is incomplete.'],
    })
  })

  it('keeps rejected canary packages in attention when structured failure rows are absent', () => {
    const attention = visibleAttention(preservedCanaryProjectionFixture)
    expect(attention.find(item => item.packageId === 'SOAK-001-A')).toMatchObject({
      code: 'REVIEW_FAILURE', source: 'package_state', occurredAt: null,
      detail: 'Raw lease and mutation evidence is incomplete.',
    })
  })

  it('flags an unrecorded review outcome from typed evidence without interpreting its label', () => {
    const snapshot = structuredClone(actualSoakCanaryProjectionFixture)
    const soak = snapshot.features.find(feature => feature.id === 'SOAK-001')?.packages.find(item => item.id === 'SOAK-001-A')
    if (!soak) throw new Error('SOAK-001-A fixture package is missing')
    soak.evidence[0].label = 'This arbitrary label must not determine approve or reject'

    expect(visibleReviews(snapshot).find(review => review.packageId === 'SOAK-001-A')).toMatchObject({
      state: 'unrecorded', source: 'package_state',
    })

    expect(visibleAttention(snapshot).find(item => item.packageId === 'SOAK-001-A')).toMatchObject({
      code: 'REVIEW_STATE_UNRECORDED',
      title: 'Review outcome is not recorded',
      detail: 'Review evidence exists for this VERIFY / REVIEW package, but this Registry revision has no structured review outcome or failure.',
      source: 'package_state',
    })

    soak.evidence[0].kind = 'artifact'
    soak.evidence[0].label = 'Rejected review according to unstructured human text'
    expect(visibleAttention(snapshot).find(item => item.packageId === 'SOAK-001-A')).toBeUndefined()
  })

  it('does not duplicate package-state fallbacks when structured rows are present', () => {
    expect(visibleReviews(factoryControlFixture).filter(review => review.packageId === 'SOAK-001-A')).toHaveLength(1)
    expect(visibleAttention(factoryControlFixture).filter(item => item.packageId === 'SOAK-001-A' && item.code === 'REVIEW_FAILURE')).toHaveLength(1)
  })

  it('excludes resolved structured failures from current attention', () => {
    const snapshot = structuredClone(factoryControlFixture)
    snapshot.failures[0].requiresHuman = false
    expect(visibleAttention(snapshot).some(item => item.id === snapshot.failures[0].id)).toBe(false)
    expect(visibleAttention(snapshot).some(item => item.packageId === snapshot.failures[0].packageId)).toBe(false)
  })

  it('does not display stale, future, missing, or unknown worker evidence as healthy', () => {
    const base = factoryControlFixture.workers[0]
    const generatedAt = factoryControlFixture.generatedAt
    expect(effectiveWorkerHealth({ ...base, serviceState: 'unknown' }, generatedAt)).toMatchObject({ state: 'constrained', reason: 'Service state is unknown.' })
    expect(effectiveWorkerHealth({ ...base, authenticationState: 'unknown' }, generatedAt)).toMatchObject({ state: 'constrained', reason: 'Authentication state is unknown.' })
    expect(effectiveWorkerHealth({ ...base, heartbeatAt: null }, generatedAt)).toMatchObject({ state: 'constrained', reason: 'Heartbeat evidence is missing.' })
    expect(effectiveWorkerHealth({ ...base, heartbeatAt: '2026-09-24T18:20:00Z' }, generatedAt)).toMatchObject({ state: 'constrained', reason: 'Heartbeat evidence is stale (600s old).' })
    expect(effectiveWorkerHealth({ ...base, heartbeatAt: '2026-09-24T18:31:00Z' }, generatedAt)).toMatchObject({ state: 'constrained', reason: 'Heartbeat timestamp is in the future.' })
    expect(effectiveWorkerHealth(base, generatedAt).state).toBe('healthy')
  })
})
