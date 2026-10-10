import { describe, expect, it } from 'vitest'
import { createCanvasRecord } from './canvasBank'
import { isPersistedState, legacyUiProjection, migrateLegacyState, reconcileLegacyUi } from './migration'
import { confirmObject } from './objectWorkflow'
import { correctOriginal, reviseInterpretation } from './reviewRevision'
import { resolveReminderInState } from './reminderWorkflow'
import type { AppState, ThoughtObject } from './domain'
import { createUniversalSearchIndex, searchDocumentsFromAppState, searchDocumentsFromModel, type SearchDocument } from './universalSearch'

const at = '2026-10-09T00:00:00.000Z'
const thought = (id: string, kind: ThoughtObject['kind'], originalContent: string, summary: string): ThoughtObject => ({
  id, kind, originalContent, source: 'text', createdAt: at, confidence: 1, status: 'review',
  interpretation: { summary, suggestedKind: kind, rationale: '' }, metadata: {}, history: [], relationships: [],
})
const canvas = { ...createCanvasRecord(at, 'canvas:orchid'), title: 'Orchid board',
  elements: [{ id: 'element:orchid', type: 'text' as const, x: 0, y: 0, text: 'Orchid sketch' }] }
function model() {
  const source: AppState = { canvas: [], objects: [
    thought('a', 'action', 'Orchid source note', 'Orchid execution'),
    thought('c', 'commitment', 'Orchid appointment', 'Orchid obligation'),
    thought('i', 'idea', 'Orchid idea seed', 'Orchid concept'),
    thought('r', 'reminder', 'Orchid reminder wording', 'Orchid reminder'),
  ] }
  let state = legacyUiProjection(migrateLegacyState(source))
  state = legacyUiProjection(reconcileLegacyUi({ ...state, objects: state.objects.map(item =>
    item.id === 'r' ? item : confirmObject(item)) }))
  state = resolveReminderInState(state, 'r', { targetId: 'a', mode: 'daily-log' })
  state = legacyUiProjection(reconcileLegacyUi(correctOriginal(state, 'a', 'Corrected teal source', true, at)))
  state = legacyUiProjection(reconcileLegacyUi(correctOriginal(state, 'r', 'Corrected teal orchid reminder', true, at)))
  state = { ...state, canvasBank: { canvases: [canvas] } }
  const saved = reconcileLegacyUi(state)
  expect(isPersistedState(saved)).toBe(true)
  return saved
}

describe('universal search source adapters', () => {
  it('returns all six kinds once per authoritative identity with original/current meaning distinguished', () => {
    const saved = model()
    const documents = searchDocumentsFromModel(saved)
    expect(searchDocumentsFromAppState(legacyUiProjection(saved))).toEqual(documents)
    expect(searchDocumentsFromAppState(legacyUiProjection(structuredClone(saved)))).toEqual(documents)
    const index = createUniversalSearchIndex(documents)
    expect(index.size).toBe(9)
    const matches = index.query('ORCHID')
    expect([...new Set(matches.map(result => result.document.kind))]).toEqual(['capture', 'action', 'commitment', 'reminder', 'idea', 'canvas'])
    expect(matches.filter(result => result.document.kind === 'reminder')).toHaveLength(1)
    expect(matches.find(result => result.document.id === 'capture:a')?.matchedFields).toEqual(['original'])
    expect(index.query('teal')[0]).toMatchObject({ document: { id: 'capture:a' }, matchedFields: ['corrected-source'] })
    expect(index.query('orchid teal')[0]).toMatchObject({ document: { id: 'capture:a' }, matchedFields: ['original', 'corrected-source'] })
    expect(index.query('teal').find(result => result.document.kind === 'reminder')).toMatchObject({
      document: { id: 'reminder:r' }, matchedFields: ['reminder-source'],
    })
    expect(index.query('execution')).toMatchObject([{ document: { kind: 'action', id: 'a', captureIds: ['capture:a'] },
      matchedFields: ['current-meaning'] }])
    expect(index.query('execution')[0].document.interpretationIds).toContain('interpretation:a:1')
    expect(index.query('sketch')[0]).toMatchObject({ document: { kind: 'canvas', id: 'canvas:orchid' }, matchedFields: ['canvas-element'] })
  })

  it('uses the same canonical documents for local and account-loaded state', () => {
    const legacy: AppState = { canvas: [], objects: [{ id: 'local', kind: 'idea', originalContent: 'Orchid source', source: 'text', createdAt: at,
      interpretation: { summary: 'Orchid idea', suggestedKind: 'idea', rationale: '' }, confidence: 1, relationships: [],
      history: [], status: 'confirmed', metadata: {} }] }
    const canonical = migrateLegacyState(legacy)
    const local = legacyUiProjection(canonical)
    const account = legacyUiProjection(structuredClone(canonical))
    expect(searchDocumentsFromAppState(local)).toEqual(searchDocumentsFromModel(canonical))
    expect(searchDocumentsFromAppState(account)).toEqual(searchDocumentsFromAppState(local))
    const edited = reviseInterpretation(local, 'local', 'Cobalt idea', at)
    const index = createUniversalSearchIndex(searchDocumentsFromAppState(edited))
    expect(index.query('cobalt').map(result => result.document.id)).toEqual(['local'])
    expect(index.query('Orchid').some(result => result.document.kind === 'idea')).toBe(false)
  })

  it('replaces changed source snapshots without retaining stale terms', () => {
    const before = model()
    const index = createUniversalSearchIndex(searchDocumentsFromModel(before))
    const revised = reviseInterpretation(legacyUiProjection(model()), 'i', 'Cobalt concept', at)
    const after = reconcileLegacyUi({ ...revised, canvasBank: { canvases: [{ ...canvas, title: 'Cobalt board' }] } })
    index.replace(searchDocumentsFromModel(after))
    expect(index.query('Orchid').some(result => result.document.id === 'i')).toBe(false)
    expect(index.query('Cobalt').map(result => result.document.id)).toEqual(['i', 'canvas:orchid'])
  })

  it('omits malformed, duplicate, and dangling records instead of guessing identity', () => {
    const stale = model()
    stale.captures = stale.captures.filter(capture => capture.id !== 'capture:c')
    expect(searchDocumentsFromModel(stale)).toEqual([])
    const forged = model()
    forged.semanticObjects[0].summary = 'Forged search meaning'
    expect(searchDocumentsFromModel(forged)).toEqual([])
    const brokenCorrection = model()
    brokenCorrection.sourceCorrections![0] = { ...brokenCorrection.sourceCorrections![0], correctedContent: 'Forged corrected source' }
    expect(searchDocumentsFromModel(brokenCorrection)).toEqual([])
    const duplicate: SearchDocument = { kind: 'idea', id: 'same', captureIds: ['capture:i'], interpretationIds: [], fields: { 'current-meaning': 'Orchid' } }
    expect(createUniversalSearchIndex([duplicate, duplicate]).query('orchid')).toEqual([])
  })

  it('canonicalizes model-less state and does not promote unconfirmed work or corrections without audit', () => {
    const legacy: AppState = { canvas: [], objects: [{ id: 'old', kind: 'idea', originalContent: 'Orchid original', currentContent: 'Teal correction',
      source: 'text', createdAt: at, interpretation: { summary: 'Cobalt idea', suggestedKind: 'idea', rationale: '' },
      confidence: 1, relationships: [], history: [], status: 'confirmed', metadata: {} },
      { id: 'unconfirmed-action', kind: 'action', originalContent: 'Do risky work', source: 'text', createdAt: at,
        interpretation: { summary: 'Risky action', suggestedKind: 'action', rationale: '' },
        confidence: 1, relationships: [], history: [], status: 'confirmed', metadata: {} },
      { id: 'unconfirmed-commitment', kind: 'commitment', originalContent: 'Promise risky work', source: 'text', createdAt: at,
        interpretation: { summary: 'Risky commitment', suggestedKind: 'commitment', rationale: '' },
        confidence: 1, relationships: [], history: [], status: 'confirmed', metadata: {} }] }
    const index = createUniversalSearchIndex(searchDocumentsFromAppState(legacy))
    expect(index.query('orchid')[0].document.kind).toBe('capture')
    expect(index.query('teal')).toEqual([])
    expect(index.query('cobalt')[0].document.kind).toBe('idea')
    expect(index.query('risky').every(result => result.document.kind === 'capture')).toBe(true)
  })

  it('indexes only resolved reminder instructions from real migration evidence', () => {
    const source: AppState = { canvas: [], objects: [
      { id: 'idea:target', kind: 'idea', originalContent: 'Launch concept', source: 'text', createdAt: at,
        interpretation: { summary: 'Launch concept', suggestedKind: 'idea', rationale: '' }, confidence: 1,
        relationships: [], history: [], status: 'confirmed', metadata: {} },
      { id: 'reminder:source', kind: 'reminder', originalContent: 'Remind me about launch', source: 'text', createdAt: at,
        interpretation: { summary: 'Launch reminder', suggestedKind: 'reminder', rationale: '' }, confidence: .5,
        relationships: [], history: [], status: 'review', metadata: {} },
    ] }
    const pending = legacyUiProjection(migrateLegacyState(source))
    expect(searchDocumentsFromAppState(pending).some(document => document.kind === 'reminder')).toBe(false)
    const rejected = legacyUiProjection(migrateLegacyState({ ...source, objects: [source.objects[0], {
      ...source.objects[1], history: [{ at, event: 'Rejected interpretation', reviewDecision: 'rejected' }],
    }] }))
    expect(searchDocumentsFromAppState(rejected).some(document => document.kind === 'reminder')).toBe(false)
    const resolved = resolveReminderInState(pending, 'reminder:source', { targetId: 'idea:target', mode: 'daily-log' })
    expect(searchDocumentsFromAppState(resolved).filter(document => document.kind === 'reminder')).toMatchObject([{
      id: 'reminder:reminder:source', targetId: 'idea:target', captureIds: ['capture:reminder:source'],
    }])
    const rejectedInstruction = model()
    rejectedInstruction.interpretations[rejectedInstruction.interpretations.length - 1] = {
      ...rejectedInstruction.interpretations.at(-1)!, reviewState: 'rejected',
    }
    expect(searchDocumentsFromModel(rejectedInstruction).some(document => document.kind === 'reminder')).toBe(false)
    const unauditedInstruction = model()
    unauditedInstruction.interpretations.at(-1)!.legacy.history = []
    expect(searchDocumentsFromModel(unauditedInstruction).some(document => document.kind === 'reminder')).toBe(false)
  })

  it('returns every matching kind by default rather than truncating before later kind buckets', () => {
    const documents: SearchDocument[] = Array.from({ length: 102 }, (_, index) => ({
      kind: 'capture', id: `capture:${index}`, captureIds: [`capture:${index}`], interpretationIds: [], fields: { original: 'Orchid' },
    }))
    documents.push({ kind: 'canvas', id: 'canvas:late', captureIds: [], interpretationIds: [], fields: { 'canvas-title': 'Orchid' } })
    const index = createUniversalSearchIndex(documents)
    expect(index.query('orchid')).toHaveLength(103)
    expect(index.query('orchid').at(-1)?.document.kind).toBe('canvas')
    expect(index.query('orchid', 10)).toHaveLength(10)
  })
})

describe('universal search performance', () => {
  it('meets first and repeated query thresholds over 10,000 indexed mixed documents', () => {
    const kinds = ['capture', 'action', 'commitment', 'reminder', 'idea', 'canvas'] as const
    const fields = ['original', 'current-meaning', 'current-meaning', 'reminder-source', 'current-meaning', 'canvas-title'] as const
    const documents: SearchDocument[] = Array.from({ length: 10_000 }, (_, position) => {
      const kind = kinds[position % kinds.length]
      const text = position % 100 === 0 ? `Amber signal notebook ${position}` : `Blue violet notebook ${position}`
      return { kind, id: `${kind}:${position}`, captureIds: kind === 'canvas' ? [] : [`capture:${position}`],
        interpretationIds: kind === 'capture' || kind === 'canvas' ? [] : [`interpretation:${position}`],
        fields: { [fields[position % fields.length]]: text } }
    })
    const buildAt = performance.now()
    const index = createUniversalSearchIndex(documents)
    const buildMs = performance.now() - buildAt
    const coldAt = performance.now()
    const cold = index.query('amber signal', 10_000)
    const coldMs = performance.now() - coldAt
    const warmAt = performance.now()
    const warm = index.query('amber signal', 10_000)
    const warmMs = performance.now() - warmAt
    const runtime = (globalThis as { process?: { version: string; platform: string; arch: string } }).process
    console.info(`Universal Search benchmark: 10000 indexed mixed six-type documents, 100 matches, Node ${runtime?.version ?? 'unknown'}, ${runtime?.platform ?? 'unknown'}/${runtime?.arch ?? 'unknown'}; build ${buildMs.toFixed(2)} ms, first query ${coldMs.toFixed(2)} ms, repeated query ${warmMs.toFixed(2)} ms`)
    expect(cold).toHaveLength(100)
    expect(warm).toHaveLength(100)
    expect(coldMs).toBeLessThanOrEqual(100)
    expect(warmMs).toBeLessThanOrEqual(50)
  })
})
