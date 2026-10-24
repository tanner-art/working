import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { buildBrain, filterBrain, layoutBrain } from './brain'
import { BrainView } from './BrainView'
import type { AppState, ThoughtObject } from './domain'
import { legacyUiProjection, migrateLegacyState, reconcileLegacyUi } from './migration'
import { confirmObject, reverseObject } from './objectWorkflow'
import { createCanvasRecord } from './canvasBank'
import { connectThoughts } from './semanticLinks'
import { resolveReminderInState } from './reminderWorkflow'
import { createUniversalSearchIndex, searchDocumentsFromModel } from './universalSearch'
import { appSurfaceForPath } from './surfaces'
import { enterWorkspaceHistory, leaveWorkspaceHistory, performWorkspaceNavigation, performWorkspaceRouteTransition } from './workspaceNavigation'
import config from '../vercel.json'

const at = '2026-10-24T12:00:00Z'
const thought = (id: string, kind: ThoughtObject['kind']): ThoughtObject => ({ id, kind, originalContent: `Orchid ${kind} source`, source: 'text', createdAt: at,
  confidence: 1, status: 'review', interpretation: { summary: `Orchid ${kind}`, suggestedKind: kind, rationale: '' }, metadata: {}, history: [], relationships: [] })
function fixture(): AppState {
  let state = legacyUiProjection(migrateLegacyState({ objects: [thought('a', 'action'), thought('i', 'idea'), thought('c', 'commitment'), thought('r', 'reminder')], canvas: [] }))
  state = legacyUiProjection(reconcileLegacyUi({ ...state, objects: state.objects.map(o => o.id === 'r' ? o : confirmObject(o)) }))
  state = resolveReminderInState(state, 'r', { targetId: 'i', mode: 'daily-log' })
  return { ...state, canvasBank: { canvases: [{ ...createCanvasRecord(at, 'board'), title: 'Orchid sketches' }] }, captureLibrary: {
    folders: [{ id: 'f', name: 'Garden', parentId: null, createdAt: at, updatedAt: at }], placements: [{ id: 'i', folderId: 'f' }],
  } }
}
describe('Brain shared workspace projection', () => {
  it('includes all six search types with identical query results and no writes', () => {
    const state = fixture(), before = JSON.stringify(state)
    const brain = buildBrain(state, reconcileLegacyUi)
    const documents = searchDocumentsFromModel(reconcileLegacyUi(state))
    expect(new Set(brain.nodes.map(n => n.document.kind)).size).toBe(6)
    expect(filterBrain(brain, 'ORCHID', '').nodes.map(n => n.document)).toEqual(documents)
    expect(new Set(filterBrain(brain, 'source', '').nodes.map(n => n.id))).toEqual(new Set(createUniversalSearchIndex(documents).query('source').map(r => `${r.document.kind}:${r.document.id}`)))
    expect(JSON.stringify(state)).toBe(before)
    expect(brain.incomplete).toBe(false)
  })
  it('uses folder groups without inventing semantic links between nearby thoughts', () => {
    const brain = buildBrain(fixture(), reconcileLegacyUi)
    expect(filterBrain(brain, '', 'folder:f').nodes.map(n => n.document.id)).toEqual(['capture:i', 'i'])
    expect(brain.links.some(l => l.label === 'Source capture')).toBe(true)
    expect(brain.links.some(l => l.source === 'action:a' && l.target === 'idea:i')).toBe(false)
  })
  it('only shows explicit current semantic links and drops reversed endpoints', () => {
    const state = connectThoughts(fixture(), 'a', 'i', 'gesture', at)
    expect(buildBrain(state).links).toContainEqual({ source: 'action:a', target: 'idea:i', label: 'relates to' })
    const reversed = { ...state, objects: state.objects.map(o => o.id === 'i' ? reverseObject(o) : o) }
    expect(buildBrain(reversed).links.some(l => l.target === 'idea:i')).toBe(false)
  })
  it('keeps same-named folders and type categories separate', () => {
    const state = fixture()
    state.captureLibrary = { folders: [{ id: 'f', name: 'Ideas', parentId: null }, { id: 'g', name: 'A / B', parentId: null }, { id: 'h', name: 'A', parentId: null }, { id: 'k', name: 'B', parentId: 'h' }].map(f => ({ ...f, createdAt: at, updatedAt: at })), placements: [{ id: 'a', folderId: 'f' }, { id: 'c', folderId: 'g' }, { id: 'r', folderId: 'k' }] }
    const brain = buildBrain(state, reconcileLegacyUi)
    const ideas = brain.nodes.filter(n => n.groupLabel === 'Ideas')
    expect(new Set(ideas.map(n => n.group))).toEqual(new Set(['folder:f', 'kind:idea']))
    expect(new Set(brain.nodes.filter(n => n.groupLabel === 'A / B').map(n => n.group))).toEqual(new Set(['folder:g', 'folder:k']))
    expect(filterBrain(brain, '', 'folder:f').nodes.every(n => n.document.captureIds.includes('capture:a'))).toBe(true)
  })
  it('protects an unsaved surface on browser Back and surface changes', () => {
    for (const destination of ['app', 'workspace'] as const) {
      let transitions = 0
      const host = { enterSurface: () => transitions++, leaveSurface: () => transitions++ }
      const context = { available: true, prepareCanvasExit: () => true, canLeaveSurface: () => false }
      expect(performWorkspaceRouteTransition(destination, context, host).ok).toBe(false)
      expect(transitions).toBe(0)
      expect(performWorkspaceRouteTransition(destination, { ...context, canLeaveSurface: () => true }, host).ok).toBe(true)
      expect(transitions).toBe(1)
    }
  })
  it('uses authoritative account readModel and reports failure instead of fake emptiness', () => {
    const saved = reconcileLegacyUi(fixture())
    expect(buildBrain(fixture(), () => saved)).toEqual(buildBrain(legacyUiProjection(saved), () => saved))
    expect(buildBrain(fixture(), () => { throw Error('offline') })).toEqual({ nodes: [], links: [], incomplete: true })
  })
  it('keeps nodes within layout bounds and layout stable for large groups', () => {
    const first = buildBrain(fixture(), reconcileLegacyUi).nodes[0]
    const nodes = Array.from({ length: 160 }, (_, i) => ({ ...first, id: String(i) }))
    const layout = layoutBrain(nodes)
    expect(layout).toEqual(layoutBrain(nodes))
    for (const p of layout.positions.values()) { expect(p.x).toBeGreaterThan(22); expect(p.y).toBeGreaterThan(22); expect(p.x).toBeLessThan(layout.width - 22); expect(p.y).toBeLessThan(layout.height - 22) }
  })
  it('routes selected items through stale-snapshot checks', () => {
    const state = fixture(), document = buildBrain(state, reconcileLegacyUi).nodes[0].document
    let opened = false
    expect(performWorkspaceNavigation({ type: 'open-search-result', document, snapshotToken: 'old' }, { state, snapshotToken: 'new', stateIsCurrent: true, available: true, readModel: reconcileLegacyUi }, { close() {}, open() { opened = true } }).ok).toBe(false)
    expect(opened).toBe(false)
  })
  it('renders an accessible map and registers direct page paths', () => {
    const html = renderToStaticMarkup(<BrainView state={fixture()} readModel={reconcileLegacyUi} snapshotToken="s" update={() => {}} navigate={() => ({ ok: true })} />)
    expect(html).toContain('Search everything'); expect(html).toContain('Connections'); expect(html).toContain('role="button"'); expect(html).toContain('not an inferred relationship')
    for (const name of ['brain', 'chat']) { expect(appSurfaceForPath(`/${name}`)).toBe(name); expect(config.rewrites).toContainEqual({ source: `/${name}`, destination: '/index.html' }) }
  })
  it('keeps Back local for all three workspace pages', () => {
    for (const path of ['/search', '/brain', '/chat']) {
      let back = false, url = '/'
      const history = { state: {} as unknown, replaceState(data: unknown, _: string, next: string) { this.state = data; url = next }, pushState(data: unknown, _: string, next: string) { this.state = data; url = next }, back() { back = true } }
      enterWorkspaceHistory(history, '/', 'session', path)
      expect(url).toBe(path)
      leaveWorkspaceHistory(history, path, 'session'); expect(back).toBe(true)
    }
  })
})
