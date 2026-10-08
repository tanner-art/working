import { renderToStaticMarkup } from 'react-dom/server'
import { createElement } from 'react'
import { describe, expect, it } from 'vitest'
import { CommitmentResolution } from './CommitmentResolution'
import { Review } from './App'
import { commitmentRouteId, resolveCommitment, retrieveCommitment } from './commitmentWorkflow'
import type { ThoughtObject } from './domain'
import { legacyUiProjection, migrateLegacyState } from './migration'
import { resolveReviewCapture } from './reviewResolution'

const review = (patch: Partial<ThoughtObject> = {}): ThoughtObject => ({ id: 'commitment/one', kind: 'idea', status: 'review', originalContent: 'Deliver the draft', source: 'text', createdAt: '2026-10-01T08:00:00.000Z', confidence: .6, interpretation: { summary: 'Deliver the draft', suggestedKind: 'commitment', rationale: 'Promise inferred' }, metadata: {}, relationships: [], history: [{ at: '2026-10-01T08:00:00.000Z', event: 'Captured' }], ...patch })

describe('Commitment Review workflow', () => {
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
