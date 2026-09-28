import type { AppState, CommitmentSetupAudit, SemanticObject, ThoughtObject } from './domain'
import { confirmObject, setObjectKind } from './objectWorkflow'
import { reconcileLegacyUi } from './migration'

export interface CommitmentDetails {
  title: string
  date?: string
  time?: string
  dependencyIds: readonly string[]
}

export type CommitmentRetrieval =
  | { status: 'found'; object: SemanticObject; routeId: string }
  | { status: 'stale'; message: string }

const validDate = (value: string) => /^\d{4}-\d{2}-\d{2}$/.test(value) && Number.isFinite(Date.parse(value)) && new Date(value).toISOString().slice(0, 10) === value
const validTime = (value: string) => /^\d{2}:\d{2}$/.test(value) && Number(value.slice(0, 2)) < 24 && Number(value.slice(3, 5)) < 60

function setup(details: CommitmentDetails): CommitmentSetupAudit {
  const title = details.title.trim()
  const date = details.date?.trim() || undefined
  const time = details.time?.trim() || undefined
  const dependencyIds = [...new Set(details.dependencyIds)]
  if (!title) throw new Error('Enter a commitment title.')
  if (date && !validDate(date)) throw new Error('Choose a valid commitment date.')
  if (time && !validTime(time)) throw new Error('Choose a valid commitment time.')
  if (time && !date) throw new Error('A commitment time needs a date; it does not create a CalendarEvent by itself.')
  if (dependencyIds.some(id => !id.trim())) throw new Error('A selected dependency is no longer valid.')
  return { title, ...(date ? { date } : {}), ...(time ? { time } : {}), dependencyIds, source: 'review-commitment-resolution' }
}

/** Resolves the obligation only; it deliberately does not create a CalendarEvent. */
export function resolveCommitment(object: ThoughtObject, details: CommitmentDetails, at = new Date().toISOString()): ThoughtObject {
  if (object.status !== 'review') throw new Error('This capture is no longer awaiting Commitment setup. Refresh Review and try again.')
  const choice = setup(details)
  const commitment = object.kind === 'commitment' ? object : setObjectKind(object, 'commitment')
  const dependencyIds = choice.dependencyIds.filter(id => id !== commitment.id)
  if (dependencyIds.length !== choice.dependencyIds.length) throw new Error('A commitment cannot depend on itself.')
  const { deadline: _priorDeadline, ...otherMetadata } = commitment.metadata
  const { suggestedDate: _priorSuggestedDate, ...otherInterpretation } = commitment.interpretation
  const prepared: ThoughtObject = { ...commitment, interpretation: { ...otherInterpretation, summary: choice.title, suggestedKind: 'commitment' },
    metadata: { ...otherMetadata, ...(choice.date ? { deadline: choice.date } : {}) },
    relationships: dependencyIds.map(targetId => ({ targetId, type: 'depends_on' })),
    history: [...commitment.history, { at, event: 'Set Commitment details', commitmentSetup: { ...choice, dependencyIds } }] }
  return confirmObject(prepared)
}

/** Stable, opaque navigation identity. Callers must not infer object existence from it. */
export function commitmentRouteId(objectId: string): string { return `commitment:${encodeURIComponent(objectId)}` }

export function retrieveCommitment(state: AppState, routeId: string): CommitmentRetrieval {
  const prefix = 'commitment:'
  if (!routeId.startsWith(prefix)) return { status: 'stale', message: 'This commitment link is invalid. Return to Calendar and try again.' }
  let objectId: string
  try { objectId = decodeURIComponent(routeId.slice(prefix.length)) } catch { return { status: 'stale', message: 'This commitment link is invalid. Return to Calendar and try again.' } }
  if (!objectId) return { status: 'stale', message: 'This commitment link is invalid. Return to Calendar and try again.' }
  try {
    const object = reconcileLegacyUi(state).semanticObjects.find(item => item.id === objectId && item.kind === 'commitment')
    return object ? { status: 'found', object, routeId: commitmentRouteId(objectId) } : { status: 'stale', message: 'This commitment is no longer available. Refresh Calendar and try again.' }
  } catch { return { status: 'stale', message: 'This commitment is no longer available. Refresh Calendar and try again.' } }
}
