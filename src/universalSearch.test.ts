import { describe, expect, it } from 'vitest'
import { createCanvasRecord } from './canvasBank'
import { legacyUiProjection, migrateLegacyState } from './migration'
import { reviseInterpretation } from './reviewRevision'
import { resolveReminderInState } from './reminderWorkflow'
import type { AppState, PersistedState } from './domain'
import { createUniversalSearchIndex, searchDocumentsFromAppState, searchDocumentsFromModel, type SearchDocument } from './universalSearch'

const at = '2026-10-09T00:00:00.000Z'
const captures = [
  { id: 'capture:a', source: 'text' as const, createdAt: at, originalContent: 'Orchid source note', evidence: 'text-only' as const },
  { id: 'capture:c', source: 'text' as const, createdAt: at, originalContent: 'Orchid appointment', evidence: 'text-only' as const },
  { id: 'capture:i', source: 'text' as const, createdAt: at, originalContent: 'Orchid idea seed', evidence: 'text-only' as const },
  { id: 'capture:r', source: 'text' as const, createdAt: at, originalContent: 'Orchid reminder wording', evidence: 'text-only' as const },
]
const semantic = (id: string, kind: 'action' | 'commitment' | 'idea', captureId: string, summary: string) => ({
  id, kind, captureIds: [captureId], interpretationIds: [`interpretation:${id}`], summary, status: 'confirmed' as const,
  metadata: {}, reminders: [],
})
const canvas = { ...createCanvasRecord(at, 'canvas:orchid'), title: 'Orchid board',
  elements: [{ id: 'element:orchid', type: 'text' as const, x: 0, y: 0, text: 'Orchid sketch' }] }
const model = (): PersistedState => ({
  schemaVersion: 2, captures: structuredClone(captures), sourceCorrections: [
    { id: 'correction:a', captureId: 'capture:a', correctedAt: at, correctedContent: 'Corrected teal source' },
    { id: 'correction:r', captureId: 'capture:r', correctedAt: at, correctedContent: 'Corrected teal orchid reminder' },
  ],
  interpretations: ['a', 'c', 'i', 'r'].map(id => ({ id: `interpretation:${id}`, version: 1,
    captureIds: [`capture:${id}`], recordedAt: at, summary: 'Orchid', rationale: '', confidence: 1,
    proposedKind: id === 'r' ? 'unresolved' as const : 'idea' as const, reviewState: 'accepted' as const,
    legacy: { id, kind: id === 'r' ? 'reminder' as const : 'idea' as const, interpretation: { summary: 'Orchid', suggestedKind: 'idea' as const, rationale: '' },
      confidence: 1, relationships: [], history: id === 'r' ? [{ at, event: 'Created Daily log reminder', reminderInstruction: {
        instructionId: 'reminder:r', action: 'created' as const, targetId: 'a', mode: 'daily-log' as const,
      } }] : [], status: 'confirmed' as const, metadata: {} },
  })),
  semanticObjects: [semantic('a', 'action', 'capture:a', 'Orchid execution'), semantic('c', 'commitment', 'capture:c', 'Orchid obligation'),
    semantic('i', 'idea', 'capture:i', 'Orchid concept')],
  reminderInstructions: [{ id: 'reminder:r', targetId: 'a', captureIds: ['capture:r'], sourceInterpretationId: 'interpretation:r',
    mode: 'daily-log', deliveryState: 'active', createdAt: at }],
  calendarEvents: [], relationships: [], legacyUiIds: ['a', 'c', 'i', 'r'], canvas: [], canvasBank: { canvases: [canvas] },
})

describe('universal search source adapters', () => {
  it('returns all six kinds once per authoritative identity with original/current meaning distinguished', () => {
    const documents = searchDocumentsFromModel(model())
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
    expect(index.query('execution')).toMatchObject([{ document: { kind: 'action', id: 'a', captureIds: ['capture:a'],
      interpretationIds: ['interpretation:a'] }, matchedFields: ['current-meaning'] }])
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
    const after = model()
    after.semanticObjects[0].summary = 'Cobalt execution'
    after.canvasBank!.canvases[0].title = 'Cobalt board'
    index.replace(searchDocumentsFromModel(after))
    expect(index.query('Orchid').some(result => result.document.id === 'a')).toBe(false)
    expect(index.query('Cobalt').map(result => result.document.id)).toEqual(['a', 'canvas:orchid'])
  })

  it('omits malformed, duplicate, and dangling records instead of guessing identity', () => {
    const stale = model()
    stale.captures = stale.captures.filter(capture => capture.id !== 'capture:c')
    stale.semanticObjects.push({ ...semantic('broken', 'idea', 'missing:capture', 'Orchid stale') })
    stale.canvasBank!.canvases.push({ ...canvas, id: '', title: 'Bad Orchid' })
    const documents = searchDocumentsFromModel(stale)
    expect(documents.some(document => document.id === 'c' || document.id === 'broken' || document.id === '')).toBe(false)
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
    rejectedInstruction.interpretations[3] = { ...rejectedInstruction.interpretations[3], reviewState: 'rejected' }
    expect(searchDocumentsFromModel(rejectedInstruction).some(document => document.kind === 'reminder')).toBe(false)
    const unauditedInstruction = model()
    unauditedInstruction.interpretations[3].legacy.history = []
    expect(searchDocumentsFromModel(unauditedInstruction).some(document => document.kind === 'reminder')).toBe(false)
  })
})

describe('universal search performance', () => {
  it('meets cold construction+query and warm query thresholds over 10,000 mixed documents', () => {
    const kinds = ['capture', 'action', 'commitment', 'reminder', 'idea', 'canvas'] as const
    const fields = ['original', 'current-meaning', 'current-meaning', 'reminder-source', 'current-meaning', 'canvas-title'] as const
    const documents: SearchDocument[] = Array.from({ length: 10_000 }, (_, position) => {
      const kind = kinds[position % kinds.length]
      const text = position % 100 === 0 ? `Amber signal notebook ${position}` : `Blue violet notebook ${position}`
      return { kind, id: `${kind}:${position}`, captureIds: kind === 'canvas' ? [] : [`capture:${position}`],
        interpretationIds: kind === 'capture' || kind === 'canvas' ? [] : [`interpretation:${position}`],
        fields: { [fields[position % fields.length]]: text } }
    })
    const coldAt = performance.now()
    const index = createUniversalSearchIndex(documents)
    const cold = index.query('amber signal', 10_000)
    const coldMs = performance.now() - coldAt
    const warmAt = performance.now()
    const warm = index.query('amber signal', 10_000)
    const warmMs = performance.now() - warmAt
    const runtime = (globalThis as { process?: { version: string; platform: string; arch: string } }).process
    console.info(`Universal Search benchmark: 10000 mixed six-type documents, 100 matches, Node ${runtime?.version ?? 'unknown'}, ${runtime?.platform ?? 'unknown'}/${runtime?.arch ?? 'unknown'}; cold build+query ${coldMs.toFixed(2)} ms, warm query ${warmMs.toFixed(2)} ms`)
    expect(cold).toHaveLength(100)
    expect(warm).toHaveLength(100)
    expect(coldMs).toBeLessThanOrEqual(100)
    expect(warmMs).toBeLessThanOrEqual(50)
  })
})
