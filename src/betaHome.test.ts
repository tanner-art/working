import { describe, expect, it } from 'vitest'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import type { AppState, ThoughtObject } from './domain'
import { BetaHome } from './BetaHome'
import { isPersistedState, legacyUiProjection, migrateLegacyState, reconcileLegacyUi } from './migration'
import { eventProposal, recordTemporalDecision } from './temporalConfirmation'
import { buildBetaHomeSnapshot, previewStartView } from './betaHomeState'
import { confirmObject } from './objectWorkflow'
import { makeObject } from './store'

const thought = (kind: ThoughtObject['kind'], status: ThoughtObject['status'], context?: string) => {
  const item = makeObject({ kind, source: 'text', originalContent: `${kind} source`, confidence: .9,
    interpretation: { summary: `${kind} summary`, rationale: 'test', suggestedKind: kind } })
  return { ...item, status, context }
}

describe('beta home preview', () => {
  it('is opt-in and leaves the configured production start page unchanged', () => {
    expect(previewStartView('', 'today')).toBe('today')
    expect(previewStartView('?preview=anything-else', 'capture')).toBe('capture')
    expect(previewStartView('?preview=home', 'canvas')).toBe('beta-home')
  })

  it('derives every count and digest section from existing state', () => {
    const reviewed = confirmObject(thought('idea', 'review', 'Personal'))
    const waiting = thought('action', 'review')
    const state: AppState = {
      objects: [reviewed, waiting],
      canvas: [
        { id: 'block', type: 'text', x: 0, y: 0, text: 'A block' },
        { id: 'group', type: 'container', x: 0, y: 0, text: 'A group' },
        { id: 'arrow', type: 'arrow', x: 0, y: 0, fromId: 'block', toId: 'group' },
      ],
    }
    const before = structuredClone(state)
    const result = buildBetaHomeSnapshot(state, new Date('2026-09-23T10:00:00'))
    expect(result).toMatchObject({ capturedCount: 2, reviewCount: 1, bankCount: 1, canvasBlockCount: 2 })
    expect(result.digest.needsReview).toHaveLength(1)
    expect(state).toEqual(before)
  })

  it('counts current Canvas Bank documents instead of the frozen legacy mirror', () => {
    const state: AppState = {
      objects: [],
      canvas: [{ id: 'legacy', type: 'text', x: 0, y: 0, text: 'Frozen recovery copy' }],
      canvasBank: { canvases: [{
        id: 'canvas:current', title: 'Current', createdAt: '2026-09-23T09:00:00Z', updatedAt: '2026-09-23T09:00:00Z',
        viewport: { x: 0, y: 0, scale: 1 },
        elements: [
          { id: 'one', type: 'text', x: 0, y: 0, text: 'One' },
          { id: 'two', type: 'container', x: 20, y: 20, text: 'Two' },
          { id: 'link', type: 'arrow', x: 0, y: 0, fromId: 'one', toId: 'two' },
        ],
      }] },
    }
    expect(buildBetaHomeSnapshot(state, new Date('2026-09-23T10:00:00Z')).canvasBlockCount).toBe(2)
  })

  it('renders canonical project signals, linked commitments, and classic-digest navigation', () => {
    const commitment = thought('commitment', 'review')
    const project = confirmObject(thought('project', 'review'))
    const projectState = legacyUiProjection(migrateLegacyState({ objects: [project], canvas: [] }))
    let eventState = legacyUiProjection(migrateLegacyState({ objects: [commitment], canvas: [] }))
    eventState.objects[0] = confirmObject(eventState.objects[0])
    const eventModel = reconcileLegacyUi(eventState)
    eventModel.calendarEvents.push({ id: 'meeting', title: 'Launch meeting', startsAt: '2026-09-23T10:00:00Z', temporalContext: 'UTC', status: 'scheduled', objectIds: [commitment.id], captureIds: [eventModel.captures[0].id] })
    expect(isPersistedState(eventModel)).toBe(true)
    eventState = { ...eventState, model: eventModel }
    eventState = recordTemporalDecision(eventState, eventModel, eventProposal(eventModel, 'meeting')!)
    const projectHtml = renderToStaticMarkup(createElement(BetaHome, { state: projectState, displayName: 'A'.repeat(80), now: new Date('2026-09-23T10:00:00Z'), onNavigate: () => undefined }))
    const eventHtml = renderToStaticMarkup(createElement(BetaHome, { state: eventState, displayName: '', now: new Date('2026-09-23T10:00:00Z'), onNavigate: () => undefined }))
    expect(projectHtml).toContain('Open classic digest')
    expect(projectHtml).toContain('Projects and objectives')
    expect(projectHtml).toContain('project summary')
    expect(eventHtml).toContain('Obligation: commitment summary')
  })
})
