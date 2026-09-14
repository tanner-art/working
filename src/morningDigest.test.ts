import { describe, expect, it } from 'vitest'
import type { CalendarEvent, Interpretation, PersistedState, SemanticObject } from './domain'
import { buildMorningDigest, localDateKey } from './morningDigest'
import { migrateLegacyState, reconcileLegacyUi, legacyUiProjection } from './migration'
import { makeObject } from './store'
import { confirmObject } from './objectWorkflow'

const object = (id: string, kind: SemanticObject['kind'], metadata = {}): SemanticObject => ({
  id, kind, metadata, summary: id, status: 'confirmed', captureIds: [], interpretationIds: [id], reminders: []
})
function model(objects: SemanticObject[] = [], events: CalendarEvent[] = []): PersistedState {
  return { schemaVersion: 2, captures: [], semanticObjects: objects, calendarEvents: events, relationships: [], canvas: [], legacyUiIds: [],
    interpretations: objects.map(o => ({ id: o.id, recordedAt: '2026-09-14', reviewState: 'accepted',
      confirmation: { transition: o.kind, at: '2026-09-14' } } as Interpretation)) }
}
const event = (id: string, startsAt: string, objectIds: string[] = []): CalendarEvent => ({ id, startsAt, objectIds,
  title: id, temporalContext: 'UTC', captureIds: [], status: 'scheduled' })
const now = new Date(2026, 8, 14, 7)

describe('canonical morning digest', () => {
  it('excludes unconfirmed event scheduling and deadlines without hiding confirmed obligations or mutating data', () => {
    const promise = object('promise', 'commitment')
    const due = object('due', 'commitment', { deadline: '2026-09-15' })
    const idea = object('idea', 'idea')
    idea.reminders = [{ id: 'r', trigger: { kind: 'unresolved', wording: 'tomorrow' }, deliveryState: 'needs-review', captureIds: [] }]
    const state = model([promise, due, idea], [event('meeting', now.toISOString(), ['promise']), event('independent', now.toISOString())])
    const before = JSON.stringify(state)
    const digest = buildMorningDigest(state, now)
    expect(digest.fixedToday).toEqual([])
    expect(digest.upcoming).toEqual([])
    expect(digest.unscheduledCommitments).toEqual([due, promise])
    expect(digest.recommended).toEqual([])
    expect(JSON.stringify(state)).toBe(before)
  })
  it('excludes cancelled/invalid events and retains unscheduled obligations', () => {
    const state = model([object('promise', 'commitment')], [{ ...event('cancelled', now.toISOString(), ['promise']), status: 'cancelled' }, event('bad', 'Tuesday'), event('floating', '2026-09-14T07:00:00')])
    const digest = buildMorningDigest(state, now)
    expect(digest.fixedToday).toEqual([])
    expect(digest.unscheduledCommitments.map(o => o.id)).toEqual(['promise'])
  })
  it('does not promote date metadata on any object kind into confirmed deadlines', () => {
    const kinds: SemanticObject['kind'][] = ['action', 'commitment', 'idea', 'project', 'objective', 'reference']
    for (const deadline of ['2026-09-13', '2026-09-14', '2026-09-16', 'Tuesday', '2026-09-31']) {
      const state = model(kinds.map(kind => object(kind, kind, { deadline })))
      const digest = buildMorningDigest(state, now)
      expect(digest.upcoming).toEqual([])
      expect(digest.unscheduledCommitments.map(o => o.id)).toEqual(['commitment'])
      expect(digest.recommended.map(o => o.id)).toEqual(['action'])
      expect(digest.projectSignals.map(o => o.id)).toEqual(['objective', 'project'])
    }
  })
  it('uses local dates for the live digest but never treats event instants as confirmed schedules', () => {
    const midnight = new Date(2026, 8, 14, 0, 5)
    const state = model([], [event('today', midnight.toISOString()), event('yesterday', new Date(2026, 8, 13, 23, 59).toISOString())])
    expect(localDateKey(midnight)).toBe('2026-09-14')
    expect(buildMorningDigest(state, midnight).day).toBe('2026-09-14')
    expect(buildMorningDigest(state, midnight).fixedToday).toEqual([])
  })
  it('does not treat commitment status alone as obligation confirmation', () => {
    const state = model([object('unconfirmed', 'commitment', { deadline: '2026-09-14' })])
    state.interpretations[0] = { ...state.interpretations[0], confirmation: undefined }
    expect(buildMorningDigest(state, now).unscheduledCommitments).toEqual([])
    expect(buildMorningDigest(state, now).upcoming).toEqual([])
  })
  it('requires confirmation and excludes terminal actions and unfinished/missing dependencies', () => {
    const state = model(['ready', 'blocked', 'unconfirmed', 'complete', 'archived'].map(id => object(id, 'action')))
    state.semanticObjects[3].status = 'complete'
    state.semanticObjects[4].status = 'archived'
    state.interpretations[2] = { ...state.interpretations[2], confirmation: undefined }
    state.relationships = [{ id: 'r', sourceId: 'blocked', targetId: 'missing', type: 'depends_on', scope: 'semantic', provenance: { interpretationId: 'blocked', evidence: 'legacy-unverified' } }]
    expect(buildMorningDigest(state, now).recommended.map(o => o.id)).toEqual(['ready'])
  })
  it('caps deterministic selections and ignores superseded review interpretations', () => {
    const state = model(Array.from({ length: 7 }, (_, i) => object(String(i), 'project')))
    state.interpretations = Array.from({ length: 7 }, (_, i) => ({ id: String(i), recordedAt: '2026-09-14', reviewState: 'review' } as Interpretation))
    state.interpretations.push({ id: 'new', previousId: '0', recordedAt: '2026-09-14', reviewState: 'accepted' } as Interpretation)
    const digest = buildMorningDigest(state, now)
    expect(digest.needsReview.map(i => i.id)).toEqual(['1', '2', '3', '4', '5'])
    expect(digest.projectSignals).toHaveLength(3)
  })
  it('reflects actual compatibility confirmation without promoting proposed work or legacy timing', () => {
    const item = makeObject({ kind: 'action', source: 'text', originalContent: 'Call Sam', confidence: .99,
      interpretation: { summary: 'Call Sam', rationale: 'test', suggestedKind: 'action', suggestedDate: '2026-09-14' } })
    const initial = migrateLegacyState({ objects: [item], canvas: [] })
    expect(buildMorningDigest(initial, now).recommended).toEqual([])
    expect(buildMorningDigest(initial, now).needsReview).toHaveLength(1)
    const ui = legacyUiProjection(initial)
    ui.objects[0] = confirmObject(ui.objects[0])
    const digest = buildMorningDigest(reconcileLegacyUi(ui), now)
    expect(digest.recommended.map(o => o.id)).toEqual([item.id])
    expect(digest.needsReview).toEqual([])
    expect(digest.upcoming).toEqual([])
  })
})
