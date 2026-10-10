import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { createCanvasRecord } from './canvasBank'
import { legacyUiProjection, migrateLegacyState, reconcileLegacyUi } from './migration'
import { confirmObject } from './objectWorkflow'
import { resolveReminderInState } from './reminderWorkflow'
import { GlobalSearchView, nextVisibleSearchCount, openSearchResult, searchEscapeAction, searchResultPreview } from './GlobalSearchView'
import { appSurfaceForPath, workspaceSurfaceModuleForPath } from './surfaces'
import type { AppState, ThoughtObject } from './domain'
import { createUniversalSearchIndex, searchProjectionFromAppState, type SearchResult } from './universalSearch'

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
    expect(markup).toContain('9 matching items')
    expect(markup).toContain('autofocus=""')
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
    expect(searchResultPreview({ ...result, document: { ...result.document, fields: { 'corrected-source': `${'x'.repeat(200)} orchid ending` } } }, 'orchid').text).toContain('orchid')
  })

  it('distinguishes the empty prompt from a genuine no-match result', () => {
    const noQuery = renderToStaticMarkup(<GlobalSearchView state={state} snapshotToken="current" navigate={() => ({ ok: true })} />)
    const noMatch = renderToStaticMarkup(<GlobalSearchView state={state} snapshotToken="current" navigate={() => ({ ok: true })} initialQuery="doesnotexist" />)
    expect(noQuery).toContain('Find captures, actions, commitments, reminders, ideas, and canvases.')
    expect(noMatch).toContain('No matches. Try another word.')
  })

  it('states incomplete indexing instead of presenting an authoritative zero', () => {
    const broken = null as unknown as AppState
    expect(searchProjectionFromAppState(broken).complete).toBe(false)
    const markup = renderToStaticMarkup(<GlobalSearchView state={broken} snapshotToken="current" navigate={() => ({ ok: true })} initialQuery="orchid" />)
    expect(markup).toContain('results may be incomplete')
    expect(markup).toContain('No indexed matches. Some items could not be searched.')
    expect(markup).not.toContain('Refresh results')
    const duplicate = { kind: 'idea' as const, id: 'same', captureIds: [], interpretationIds: [], fields: { 'current-meaning': 'Orchid' } }
    expect(createUniversalSearchIndex([duplicate, duplicate]).omittedCount).toBe(2)
  })

  it('sends a clicked result with its exact snapshot, and keeps Escape and paging predictable', () => {
    const result: SearchResult = { document: { kind: 'idea', id: 'idea:one', captureIds: ['capture:one'], interpretationIds: ['interpretation:one'], fields: { 'current-meaning': 'Orchid' } }, matchedFields: ['current-meaning'] }
    const requests: unknown[] = []
    const outcome = openSearchResult(result, 'snapshot-a', request => { requests.push(request); return { ok: false, message: 'Stale account' } })
    expect(outcome).toEqual({ ok: false, message: 'Stale account' })
    expect(requests).toEqual([{ type: 'open-search-result', document: result.document, snapshotToken: 'snapshot-a' }])
    expect(searchEscapeAction(true, true)).toBe('ignore')
    expect(searchEscapeAction(false, true)).toBe('clear')
    expect(searchEscapeAction(false, false)).toBe('close')
    expect(nextVisibleSearchCount(40, 110)).toBe(80)
    expect(nextVisibleSearchCount(80, 110)).toBe(110)
  })
})
