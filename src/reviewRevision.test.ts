import { describe, expect, it, vi } from 'vitest'
import { migrateLegacyState, legacyUiProjection, reconcileLegacyUi } from './migration'
import { correctOriginal, hasUnsavedReviewDrafts, reviseInterpretation, revisionNeedsReconfirmation, revisionReviewNotice, reviewTextSnapshot } from './reviewRevision'
import { confirmedActions, confirmObject, hasConfirmation, reviewObjects } from './objectWorkflow'
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

  it('presents the immutable capture and text or meaning revisions as one chronological progression', () => {
    let state = reviseInterpretation(fixture(), 'one', 'Better reading', '2026-09-20T02:00:00.000Z')
    state = correctOriginal(state, 'one', 'Original wording', true, '2026-09-20T01:00:00.000Z')
    expect(reviewTextSnapshot(state, 'one').progression).toEqual([
      { id: 'capture:one', at: '2026-09-20T00:00:00.000Z', kind: 'capture', label: 'Original capture', text: 'orginal wording' },
      { id: 'correction-1', at: '2026-09-20T01:00:00.000Z', kind: 'correction', label: 'Thought text revised', text: 'Original wording', previousText: 'orginal wording' },
      { id: 'interpretation-1', at: '2026-09-20T02:00:00.000Z', kind: 'interpretation', label: 'Organized meaning revised', text: 'Better reading', previousText: 'First reading' },
    ])
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

  it('rejects empty, unchanged and unknown edits without changing state', () => {
    const state = fixture()
    const before = structuredClone(state)
    expect(() => reviseInterpretation(state, 'one', '   ')).toThrow('different non-empty')
    expect(() => reviseInterpretation(state, 'one', 'First reading')).toThrow('different non-empty')
    expect(() => reviseInterpretation(state, 'missing', 'x')).toThrow('existing capture')
    expect(() => correctOriginal(state, 'one', '  ', true)).toThrow('different non-empty')
    expect(() => correctOriginal(state, 'one', 'orginal wording', true)).toThrow('different non-empty')
    expect(state).toEqual(before)
  })

  it.each(['voice', 'canvas'] as const)('revises %s meaning while refusing to rewrite its raw source', source => {
    const state = legacyUiProjection(migrateLegacyState({ objects: [{ ...thought, source }], canvas: [] }))
    const revised = reviseInterpretation(state, 'one', 'A source-appropriate reading', '2026-09-20T01:00:00.000Z')
    expect(revised.objects[0]).toMatchObject({ source, originalContent: 'orginal wording', interpretation: { summary: 'A source-appropriate reading' } })
    expect(reviewTextSnapshot(revised, 'one').progression.at(-1)).toMatchObject({ kind: 'interpretation', previousText: 'First reading' })
    expect(() => correctOriginal(state, 'one', 'x', true)).toThrow('text capture')
  })

  it('detects only drafts that the source-specific editor can lose', () => {
    expect(hasUnsavedReviewDrafts(thought, 'orginal wording', 'Original wording', 'First reading')).toBe(true)
    expect(hasUnsavedReviewDrafts(thought, 'orginal wording', 'orginal wording', 'Better reading')).toBe(true)
    expect(hasUnsavedReviewDrafts({ ...thought, source: 'voice' }, 'orginal wording', 'hidden change', 'First reading')).toBe(false)
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

  const cases = (['action', 'commitment'] as const).flatMap(kind => (['confirmed', 'complete', 'archived'] as const).map(status => [kind, status] as const))
  it.each(cases)('returns a revised %s %s to Review immediately and after reload (D-009)', (kind, status) => {
    const proposed = legacyUiProjection(migrateLegacyState({ objects: [{ ...thought, kind }], canvas: [] }))
    const confirmed = { ...proposed, objects: proposed.objects.map(o => ({ ...confirmObject(o), status })) }
    expect(confirmedActions(confirmed.objects)).toHaveLength(kind === 'action' && status === 'confirmed' ? 1 : 0)
    expect(revisionReviewNotice(confirmed.objects[0])).toContain(`Revising this ${status} ${kind} returns it to Review`)
    const state = reviseInterpretation(confirmed, 'one', 'Better reading', '2026-09-20T01:00:00.000Z')
    const [revised] = state.objects
    expect(revised.status).toBe('review')
    expect(reviewObjects(state.objects).map(o => o.id)).toEqual(['one'])
    expect(confirmedActions(state.objects)).toEqual([])
    expect(revised.history.map(h => h.event)).toEqual(['Captured', `Confirmed as ${kind}`, 'Revised interpretation'])
    expect(revised.history[1].confirmation?.summary).toBe('First reading')
    expect(revised.originalContent).toBe('orginal wording')
    const loaded = legacyUiProjection(JSON.parse(JSON.stringify(reconcileLegacyUi(state))))
    expect(loaded.objects[0].status).toBe('review')
    expect(reviewObjects(loaded.objects).map(o => o.id)).toEqual(['one'])
    expect(confirmedActions(loaded.objects)).toEqual([])
    expect(loaded.objects[0].history).toEqual(revised.history)
    expect(revisionNeedsReconfirmation(confirmed.objects[0])).toBe(true)
    expect(revisionNeedsReconfirmation(revised)).toBe(false)
    expect(revisionReviewNotice(revised)).toBeUndefined()
  })

  it.each(['action', 'commitment'] as const)('does not resurrect a %s confirmation after A→B→A, including after reload', kind => {
    const proposed = legacyUiProjection(migrateLegacyState({ objects: [{ ...thought, kind }], canvas: [] }))
    const confirmed = { ...proposed, objects: proposed.objects.map(o => confirmObject(o)) }
    expect(hasConfirmation(confirmed.objects[0])).toBe(true)
    let state = reviseInterpretation(confirmed, 'one', 'Second reading', '2026-09-20T01:00:00.000Z')
    state = reviseInterpretation(state, 'one', 'First reading', '2026-09-20T02:00:00.000Z')
    const [returned] = state.objects
    expect(returned.interpretation.summary).toBe('First reading')
    expect(returned.status).toBe('review')
    expect(hasConfirmation(returned)).toBe(false)
    expect(confirmedActions(state.objects)).toEqual([])
    // The original confirmation event stays in history for audit.
    expect(returned.history.map(h => h.event)).toEqual(['Captured', `Confirmed as ${kind}`, 'Revised interpretation', 'Revised interpretation'])
    expect(returned.history[1].confirmation?.summary).toBe('First reading')

    const loaded = legacyUiProjection(JSON.parse(JSON.stringify(reconcileLegacyUi(state))))
    expect(loaded.objects[0].status).toBe('review')
    expect(hasConfirmation(loaded.objects[0])).toBe(false)
    expect(loaded.objects[0].history).toEqual(returned.history)

    const reconfirmed = confirmObject(loaded.objects[0])
    expect(hasConfirmation(reconfirmed)).toBe(true)
    expect(reconfirmed.history.at(-1)?.event).toBe(`Confirmed as ${kind}`)
    expect(reconfirmed.history).toHaveLength(returned.history.length + 1)
    const reloaded = legacyUiProjection(JSON.parse(JSON.stringify(reconcileLegacyUi({ ...loaded, objects: [reconfirmed] }))))
    expect(hasConfirmation(reloaded.objects[0])).toBe(true)
  })

  it('describes each status transition accurately', () => {
    const base = { ...thought, kind: 'action' as const }
    expect(revisionReviewNotice({ ...base, status: 'confirmed' })).toContain('leaves your confirmed list')
    expect(revisionReviewNotice({ ...base, status: 'complete' })).toContain('no longer marked complete')
    expect(revisionReviewNotice({ ...base, status: 'archived' })).toContain('leaves the archive')
  })

  it('leaves non-consequential objects untouched by the re-confirmation rule', () => {
    expect(revisionNeedsReconfirmation({ ...thought, status: 'confirmed' })).toBe(false)
  })

  it('refuses reconciliation of interpretation changes that are not recorded as revisions', () => {
    const state = fixture()
    const tampered = { ...state, objects: state.objects.map(o => ({ ...o, interpretation: { ...o.interpretation, summary: 'Silent edit' } })) }
    expect(() => legacyUiProjection(reconcileLegacyUi(tampered))).toThrow()
  })
})
