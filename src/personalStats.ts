import type { PersistedState, SemanticKind, SemanticObject } from './domain'
import { isPersistedState } from './migration'
import { currentInterpretations } from './morningDigest'

const semanticKinds: SemanticKind[] = ['idea', 'action', 'project', 'commitment', 'person', 'reference', 'objective']

export interface PersonalStats {
  generatedAt: string
  privacy: {
    audience: 'account-owner'
    sharing: 'disabled'
    rankings: 'not-calculated'
  }
  totals: {
    captures: number
    currentObjects: number
    completedObjects: number
    pendingReview: number
    canvasElements: number
  }
  activity: {
    capturesLast7Days: number
    capturesLast30Days: number
  }
  actions: {
    confirmed: number
    completed: number
    completionPercent: number | null
  }
  byKind: Record<SemanticKind, number>
  provenance: {
    schemaVersion: PersistedState['schemaVersion']
    captureIds: string[]
    interpretationIds: string[]
    semanticObjectIds: string[]
  }
}

function acceptedCurrentObjects(model: PersistedState): SemanticObject[] {
  const current = currentInterpretations(model)
  return model.semanticObjects.filter(object => {
    if (object.status === 'archived') return false
    const reading = current.find(item => object.interpretationIds.includes(item.id))
    if (!reading || reading.reviewState !== 'accepted') return false
    return !['action', 'commitment'].includes(object.kind) || reading.confirmation?.transition === object.kind
  })
}

function recentCount(model: PersistedState, generatedAt: Date, days: number): number {
  const lowerBound = generatedAt.getTime() - days * 24 * 60 * 60 * 1000
  return model.captures.filter(capture => {
    const capturedAt = Date.parse(capture.createdAt)
    return Number.isFinite(capturedAt) && capturedAt <= generatedAt.getTime() && capturedAt >= lowerBound
  }).length
}

/**
 * Computes account-owner-only statistics from canonical records. It has no user-comparison,
 * leaderboard or network inputs and never changes persisted state.
 */
export function calculatePersonalStats(model: PersistedState, generatedAt = new Date()): PersonalStats {
  if (!isPersistedState(model) || !Number.isFinite(generatedAt.getTime())) throw Error('Personal statistics require a valid saved model and date.')
  const current = currentInterpretations(model)
  const objects = acceptedCurrentObjects(model)
  const actions = objects.filter(object => object.kind === 'action')
  const completedActions = actions.filter(object => object.status === 'complete')
  const byKind = Object.fromEntries(semanticKinds.map(kind => [kind, objects.filter(object => object.kind === kind).length])) as Record<SemanticKind, number>

  return {
    generatedAt: generatedAt.toISOString(),
    privacy: { audience: 'account-owner', sharing: 'disabled', rankings: 'not-calculated' },
    totals: {
      captures: model.captures.length,
      currentObjects: objects.length,
      completedObjects: objects.filter(object => object.status === 'complete').length,
      pendingReview: current.filter(reading => reading.reviewState === 'review' || reading.proposedReminder?.deliveryState === 'needs-review').length,
      canvasElements: model.canvas.length,
    },
    activity: {
      capturesLast7Days: recentCount(model, generatedAt, 7),
      capturesLast30Days: recentCount(model, generatedAt, 30),
    },
    actions: {
      confirmed: actions.length,
      completed: completedActions.length,
      completionPercent: actions.length === 0 ? null : Math.round(completedActions.length / actions.length * 100),
    },
    byKind,
    provenance: {
      schemaVersion: model.schemaVersion,
      captureIds: model.captures.map(item => item.id),
      interpretationIds: current.map(item => item.id),
      semanticObjectIds: objects.map(item => item.id),
    },
  }
}
