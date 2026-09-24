import { describe, expect, it } from 'vitest'
import { factoryControlFixture } from './factoryControl.fixture'
import { capacitySummary, emptyQueueFilters, filterFactoryFeatures, packageIndex } from './buildDashboard'

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
})
