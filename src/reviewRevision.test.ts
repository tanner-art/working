import { describe, expect, it, vi } from 'vitest'
import { migrateLegacyState, legacyUiProjection, reconcileLegacyUi } from './migration'
import { correctOriginal, reviseInterpretation, reviewTextSnapshot } from './reviewRevision'
import { isPersistedState } from './migration'
import type { AppState, ThoughtObject } from './domain'

vi.stubGlobal('crypto', { randomUUID: () => 'correction-1' })

const thought: ThoughtObject = {
  id: 'one', kind: 'idea', originalContent: 'orginal wording', source: 'text', createdAt: '2026-09-20T00:00:00.000Z',
  interpretation: { summary: 'First reading', suggestedKind: 'idea', rationale: 'Test' }, confidence: .8,
  relationships: [], history: [{ at: '2026-09-20T00:00:00.000Z', event: 'Captured' }], status: 'review', metadata: {},
}
const fixture = (): AppState => legacyUiProjection(migrateLegacyState({ objects: [thought], canvas: [] }))

describe('review text revisions', () => {
  it('creates a new interpretation version while preserving the capture', () => {
    const state = reviseInterpretation(fixture(), 'one', 'Better reading', '2026-09-20T01:00:00.000Z')
    expect(reconcileLegacyUi(state).interpretations).toHaveLength(2)
    expect(reconcileLegacyUi(state).interpretations[1]).toMatchObject({ version: 2, previousId: 'interpretation:one:1', summary: 'Better reading' })
    expect(reconcileLegacyUi(state).captures[0].originalContent).toBe('orginal wording')
    expect(reviewTextSnapshot(state, 'one').revisions).toEqual([{ at: '2026-09-20T01:00:00.000Z', from: 'First reading', to: 'Better reading' }])
  })

  it('requires confirmation and records an overlay without rewriting source evidence', () => {
    expect(() => correctOriginal(fixture(), 'one', 'Original wording', false)).toThrow('explicit confirmation')
    const state = correctOriginal(fixture(), 'one', 'Original wording', true, '2026-09-20T02:00:00.000Z')
    const snapshot = reviewTextSnapshot(state, 'one')
    expect(snapshot).toMatchObject({ immutableSource: 'orginal wording', currentText: 'Original wording' })
    expect(snapshot.corrections[0]).toMatchObject({ id: 'correction-1', captureId: 'capture:one', correctedContent: 'Original wording' })
    expect(reconcileLegacyUi(state).captures[0].originalContent).toBe('orginal wording')
  })

  it('survives JSON persistence and projection with full history', () => {
    let state = reviseInterpretation(fixture(), 'one', 'Better reading', '2026-09-20T01:00:00.000Z')
    state = correctOriginal(state, 'one', 'Original wording', true, '2026-09-20T02:00:00.000Z')
    const saved = JSON.parse(JSON.stringify(reconcileLegacyUi(state)))
    expect(isPersistedState(saved)).toBe(true)
    const loaded = legacyUiProjection(saved)
    expect(reviewTextSnapshot(loaded, 'one')).toMatchObject({ immutableSource: 'orginal wording', currentText: 'Original wording' })
    expect(reconcileLegacyUi(loaded).interpretations).toHaveLength(2)
  })

  it('rejects empty, unchanged, unknown and non-text edits without changing state', () => {
    const state = fixture()
    const before = structuredClone(state)
    expect(() => reviseInterpretation(state, 'one', '   ')).toThrow('different non-empty')
    expect(() => reviseInterpretation(state, 'one', 'First reading')).toThrow('different non-empty')
    expect(() => reviseInterpretation(state, 'missing', 'x')).toThrow('existing capture')
    expect(() => correctOriginal(state, 'one', '  ', true)).toThrow('different non-empty')
    expect(() => correctOriginal(state, 'one', 'orginal wording', true)).toThrow('different non-empty')
    const voice = legacyUiProjection(migrateLegacyState({ objects: [{ ...thought, source: 'voice' }], canvas: [] }))
    expect(() => reviseInterpretation(voice, 'one', 'x')).toThrow('text capture')
    expect(() => correctOriginal(voice, 'one', 'x', true)).toThrow('text capture')
    expect(state).toEqual(before)
  })

  it('chains successive corrections and keeps each one inspectable', () => {
    vi.stubGlobal('crypto', { randomUUID: vi.fn().mockReturnValueOnce('c1').mockReturnValueOnce('c2') })
    let state = correctOriginal(fixture(), 'one', 'Original wording', true, '2026-09-20T02:00:00.000Z')
    state = correctOriginal(state, 'one', 'Original wording.', true, '2026-09-20T03:00:00.000Z')
    const snapshot = reviewTextSnapshot(state, 'one')
    expect(snapshot.corrections.map(c => [c.id, c.previousId])).toEqual([['c1', undefined], ['c2', 'c1']])
    expect(snapshot).toMatchObject({ immutableSource: 'orginal wording', currentText: 'Original wording.' })
    vi.stubGlobal('crypto', { randomUUID: () => 'correction-1' })
  })

  it('validates persisted correction chains and rejects malformed ones', () => {
    const saved = JSON.parse(JSON.stringify(reconcileLegacyUi(correctOriginal(fixture(), 'one', 'Original wording', true, '2026-09-20T02:00:00.000Z'))))
    const first = saved.sourceCorrections[0]
    const bad = (corrections: unknown[]) => isPersistedState({ ...saved, sourceCorrections: corrections })
    expect(bad([first])).toBe(true)
    expect(bad([first, first])).toBe(false)
    expect(bad([{ ...first, previousId: 'ghost' }])).toBe(false)
    expect(bad([{ ...first, captureId: 'capture:none' }])).toBe(false)
    expect(bad([{ ...first, correctedContent: '  ' }])).toBe(false)
    expect(bad([{ ...first, correctedAt: 'not a date' }])).toBe(false)
    expect(bad([{ ...first, extra: true }])).toBe(false)
    expect(bad([first, { ...first, id: 'c2' }])).toBe(false)
    expect(isPersistedState({ ...saved, sourceCorrections: 'nope' })).toBe(false)
  })

  it('loads legacy state without corrections unchanged', () => {
    const state = fixture()
    expect(state.model?.sourceCorrections).toBeUndefined()
    expect(reviewTextSnapshot(state, 'one')).toMatchObject({ currentText: 'orginal wording', corrections: [], revisions: [] })
  })

  it('refuses reconciliation of interpretation changes that are not recorded as revisions', () => {
    const state = fixture()
    const tampered = { ...state, objects: state.objects.map(o => ({ ...o, interpretation: { ...o.interpretation, summary: 'Silent edit' } })) }
    expect(() => legacyUiProjection(reconcileLegacyUi(tampered))).toThrow()
  })
})
