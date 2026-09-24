import type { FactoryCapacityScope, FactoryFeature, FactoryPackage } from './factoryControl'

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
