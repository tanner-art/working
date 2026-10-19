import { renderToStaticMarkup } from 'react-dom/server'
import { createElement } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { CommitmentResolution } from './CommitmentResolution'
import { Review } from './App'
import { commitmentRouteId, resolveCommitment, retrieveCommitment } from './commitmentWorkflow'
import type { ThoughtObject } from './domain'
import { isPersistedState, legacyUiProjection, migrateLegacyState, reconcileLegacyUi } from './migration'
import { resolveReviewCapture } from './reviewResolution'
import { loadStateResult, saveState, serializeState } from './store'
import { stageAction } from './actionStaging'
import { reverseObject } from './objectWorkflow'
import { MorningDigest } from './DigestPanel'

const review = (patch: Partial<ThoughtObject> = {}): ThoughtObject => ({ id: 'commitment/one', kind: 'idea', status: 'review', originalContent: 'Deliver the draft', source: 'text', createdAt: '2026-10-01T08:00:00.000Z', confidence: .6, interpretation: { summary: 'Deliver the draft', suggestedKind: 'commitment', rationale: 'Promise inferred' }, metadata: {}, relationships: [], history: [{ at: '2026-10-01T08:00:00.000Z', event: 'Captured' }], ...patch })

describe('Commitment Review workflow', () => {
  afterEach(() => vi.unstubAllGlobals())

  it.each(['welcome', 'capture-date', 'idea', 'action'] as const)('preserves proposal evidence through %s resolution, render, save, reload, and reversal', scenario => {
    const proposal = review({ kind: scenario === 'action' ? 'action' : scenario === 'idea' ? 'idea' : 'commitment',
      interpretation: { summary: 'Original proposal', suggestedKind: scenario === 'idea' ? 'idea' : scenario === 'action' ? 'action' : 'commitment',
        rationale: 'Original inference', ...(scenario === 'capture-date' ? { suggestedDate: '2026-10-21' } : {}) } })
    const sibling = review({ id: 'staged-sibling', kind: 'action' })
    let raw: string | null = scenario === 'welcome' ? null : JSON.stringify({ objects: [sibling, proposal], canvas: [] })
    vi.stubGlobal('localStorage', { getItem: () => raw, setItem: (_key: string, value: string) => { raw = value } })
    const loaded = loadStateResult()
    expect(loaded.error).toBeUndefined()
    let state = loaded.state
    const targetId = scenario === 'welcome' ? 'welcome-commitment' : proposal.id
    const siblingId = scenario === 'welcome' ? 'welcome-action' : sibling.id
    expect(saveState(state)).toBeUndefined()
    state = { ...state, objects: state.objects.map(object => object.id === siblingId ? stageAction(object) : object) }
    expect(saveState(state)).toBeUndefined()
    const captures = structuredClone(serializeState(state).captures)
    const original = state.objects.find(object => object.id === targetId)!
    const resolved = resolveCommitment(original, { title: 'Dentist appointment', date: '2026-10-22', time: '14:00', dependencyIds: [] })
    expect(resolved.interpretation).toEqual({ ...original.interpretation, summary: 'Dentist appointment' })
    expect(original.interpretation.summary).not.toBe('Dentist appointment')
    state = { ...state, objects: state.objects.map(object => object.id === targetId ? resolved : object) }
    const model = reconcileLegacyUi(state)
    expect(isPersistedState(model)).toBe(true)
    expect(model.captures).toEqual(captures)
    expect(model.calendarEvents).toEqual([])
    expect(model.temporalHistory ?? []).toEqual([])
    expect(model.semanticObjects.find(object => object.id === targetId)).toMatchObject({ kind: 'commitment', status: 'confirmed', metadata: {} })
    expect(model.stagedActions).toMatchObject([{ objectId: siblingId, status: 'staged' }])
    expect(() => renderToStaticMarkup(createElement(MorningDigest, { state, visible: true, onShow: () => undefined }))).not.toThrow()
    expect(saveState(state)).toBeUndefined()
    const reloaded = loadStateResult()
    expect(reloaded.error).toBeUndefined()
    expect(isPersistedState(reloaded.state.model)).toBe(true)
    expect(reloaded.state.objects.find(object => object.id === targetId)).toEqual(resolved)
    expect(retrieveCommitment(reloaded.state, commitmentRouteId(targetId))).toMatchObject({ status: 'found', object: { id: targetId } })
    const reversed = { ...reloaded.state, objects: reloaded.state.objects.map(object => object.id === targetId ? reverseObject(object) : object) }
    expect(saveState(reversed)).toBeUndefined()
    const afterReversal = loadStateResult()
    expect(afterReversal.error).toBeUndefined()
    expect(afterReversal.state.model?.captures).toEqual(captures)
    expect(afterReversal.state.objects.find(object => object.id === targetId)?.status).toBe('review')
  })

  it('still rejects arbitrary edits to immutable proposal fields without overwriting storage', () => {
    let raw = JSON.stringify({ objects: [review()], canvas: [] })
    vi.stubGlobal('localStorage', { getItem: () => raw, setItem: (_key: string, value: string) => { raw = value } })
    const state = loadStateResult().state
    const preserved = raw
    const tampered = { ...state, objects: state.objects.map(object => ({ ...object, interpretation: { ...object.interpretation, rationale: 'Rewritten inference' } })) }
    expect(() => reconcileLegacyUi(tampered)).toThrow('invalid or ambiguous')
    expect(saveState(tampered)).toBeDefined()
    expect(raw).toBe(preserved)
  })

  it('keeps Review reachable through the Commitment choice and exposes only the primary setup fields', async () => {
    const pending = await resolveReviewCapture(review(), 'commitment')
    expect(pending).toMatchObject({ status: 'needs-input' })
    const reviewMarkup = renderToStaticMarkup(createElement(Review, { objects: [review()], onResolve: () => undefined, onReject: () => undefined, onOpen: () => undefined }))
    expect(reviewMarkup).toContain('>Commitment</button>')
    const markup = renderToStaticMarkup(createElement(CommitmentResolution, { object: review(), dependencies: [], onResolve: () => undefined }))
    for (const field of ['Title', 'Date', 'Time', 'Dependencies', 'Save commitment']) expect(markup).toContain(field)
    expect(markup).toContain('CalendarEvent requires a separate confirmation')
  })

  it('confirms only the obligation, validates details, and rejects duplicate or self dependencies', () => {
    expect(() => resolveCommitment(review(), { title: ' ', dependencyIds: [] })).toThrow('Enter a commitment title')
    expect(() => resolveCommitment(review(), { title: 'Draft', time: '09:00', dependencyIds: [] })).toThrow('needs a date')
    expect(() => resolveCommitment(review(), { title: 'Draft', date: '2026-02-30', dependencyIds: [] })).toThrow('valid commitment date')
    expect(() => resolveCommitment(review(), { title: 'Draft', dependencyIds: ['a', 'a'] })).toThrow('only once')
    expect(() => resolveCommitment(review(), { title: 'Draft', dependencyIds: ['commitment/one'] })).toThrow('cannot depend on itself')
    expect(() => resolveCommitment(review({ status: 'confirmed' }), { title: 'Draft', dependencyIds: [] })).toThrow('no longer awaiting')
    const resolved = resolveCommitment(review(), { title: 'Deliver final draft', date: '2026-10-02', time: '09:30', dependencyIds: ['other'] }, '2026-10-01T08:05:00.000Z')
    expect(resolved).toMatchObject({ kind: 'commitment', status: 'confirmed', metadata: { deadline: '2026-10-02' }, relationships: [{ targetId: 'other', type: 'depends_on' }] })
    expect(resolved.history.find(entry => entry.commitmentSetup)?.commitmentSetup).toMatchObject({ title: 'Deliver final draft', time: '09:30' })
    expect(resolved.history.some(entry => entry.commitmentSchedule)).toBe(false)
  })

  it('retrieves a persisted commitment through its stable opaque route identity', () => {
    const resolved = resolveCommitment(review(), { title: 'Deliver draft', dependencyIds: [] })
    const baseline = legacyUiProjection(migrateLegacyState({ objects: [review()], canvas: [] }))
    const state = { ...baseline, objects: [resolved] }
    const route = commitmentRouteId(resolved.id)
    expect(route).toBe('commitment:commitment%2Fone')
    expect(retrieveCommitment(state, route)).toMatchObject({ status: 'found', routeId: route, object: { id: resolved.id, kind: 'commitment' } })
    expect(retrieveCommitment(state, 'action:commitment%2Fone')).toMatchObject({ status: 'stale' })
  })
})
