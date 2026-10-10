import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { createCanvasRecord } from './canvasBank'
import { legacyUiProjection, migrateLegacyState, reconcileLegacyUi } from './migration'
import { confirmObject } from './objectWorkflow'
import { resolveReminderInState } from './reminderWorkflow'
import { GlobalSearchView, searchResultPreview } from './GlobalSearchView'
import { appSurfaceForPath, workspaceSurfaceModuleForPath } from './surfaces'
import type { AppState, ThoughtObject } from './domain'
import type { SearchResult } from './universalSearch'

const at = '2026-10-09T00:00:00.000Z'
const thought = (id: string, kind: ThoughtObject['kind']): ThoughtObject => ({ id, kind, originalContent: `Orchid ${kind} source`, source: 'text', createdAt: at,
  confidence: 1, status: 'review', interpretation: { summary: `Orchid ${kind}`, suggestedKind: kind, rationale: '' },
  metadata: {}, history: [], relationships: [] })
function fixture(): AppState {
  const source: AppState = { canvas: [], objects: [thought('a', 'action'), thought('c', 'commitment'), thought('i', 'idea'), thought('r', 'reminder')] }
  let state = legacyUiProjection(migrateLegacyState(source))
  state = legacyUiProjection(reconcileLegacyUi({ ...state, objects: state.objects.map(item => item.id === 'r' ? item : confirmObject(item)) }))
  state = resolveReminderInState(state, 'r', { targetId: 'i', mode: 'daily-log' })
  return { ...state, canvasBank: { canvases: [{ ...createCanvasRecord(at, 'canvas:orchid'), title: 'Orchid sketchboard' }] } }
}
const state = fixture()

describe('global Search surface', () => {
  it('is registered once and renders conventional results with provenance labels', () => {
    expect(appSurfaceForPath('/search')).toBe('search')
    expect(workspaceSurfaceModuleForPath('/search')).toBeDefined()
    const markup = renderToStaticMarkup(<GlobalSearchView state={state} snapshotToken="current" navigate={() => ({ ok: true })} initialQuery="orchid" />)
    expect(markup).toContain('Search Threadline')
    expect(markup).toContain('9 results')
    expect(markup).toContain('Original capture')
    expect(markup).toContain('Current meaning')
    expect(markup).toContain('Canvas title')
    expect(markup).toContain('Open Capture')
    expect(markup).toContain('Open Action')
    expect(markup).toContain('Open Commitment')
    expect(markup).toContain('Open Reminder')
    expect(markup).toContain('Open Idea')
    expect(markup).toContain('Open Canvas')
  })

  it('displays the matching source, not an unrelated current-meaning field', () => {
    const result: SearchResult = { document: { kind: 'capture', id: 'capture:a', captureIds: ['capture:a'], interpretationIds: [],
      fields: { original: 'Original wording', 'corrected-source': 'Corrected orchid wording' } }, matchedFields: ['corrected-source'] }
    expect(searchResultPreview(result)).toEqual({ text: 'Corrected orchid wording', source: 'Corrected source' })
  })

  it('distinguishes the empty prompt from a genuine no-match result', () => {
    const noQuery = renderToStaticMarkup(<GlobalSearchView state={state} snapshotToken="current" navigate={() => ({ ok: true })} />)
    const noMatch = renderToStaticMarkup(<GlobalSearchView state={state} snapshotToken="current" navigate={() => ({ ok: true })} initialQuery="doesnotexist" />)
    expect(noQuery).toContain('Find captures, actions, commitments, reminders, ideas, and canvases.')
    expect(noMatch).toContain('No matches. Try another word.')
  })
})
