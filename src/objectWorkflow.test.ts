import { describe, expect, it } from 'vitest'
import { makeObject } from './store'
import { legacyUiProjection, migrateLegacyState, reconcileLegacyUi } from './migration'
import { bankObjects, confirmObject, hasConfirmation, reviewObjects, reverseObject, setObjectKind, setObjectStatus, updateObject } from './objectWorkflow'

const proposal = (kind: 'action' | 'commitment' | 'idea' = 'action') => makeObject({
  kind, source: 'text', originalContent: 'Keep the original thought', confidence: .6,
  interpretation: { summary: 'Proposed meaning', suggestedKind: kind, rationale: 'Uncertain' }
})
const roundTrip = (object: ReturnType<typeof proposal>) => {
  const state = legacyUiProjection(migrateLegacyState({ objects: [object], canvas: [] }))
  return (changed: typeof object) => legacyUiProjection(reconcileLegacyUi({ ...state, objects: [changed] }))
}

describe('Organize decisions and detail actions', () => {
  it.each(['action', 'commitment', 'idea'] as const)('rejects %s without losing capture/history, including after reload', kind => {
    const original = proposal(kind)
    const reload = roundTrip(original)
    const rejected = reverseObject(original, 'rejected')
    expect(reviewObjects([rejected])).toEqual([])
    const saved = reload(rejected)
    expect(reviewObjects(saved.objects)).toEqual([])
    expect(saved.model!.captures[0].originalContent).toBe(original.originalContent)
    expect(saved.objects[0].history).toEqual(rejected.history)
    expect(reviewObjects([setObjectKind(saved.objects[0], 'idea')])).toHaveLength(1)
  })

  it.each(['action', 'commitment', 'idea'] as const)('confirms %s and persists Complete, Archive, and edited details', kind => {
    const original = proposal(kind)
    const reload = roundTrip(original)
    const confirmed = confirmObject(original)
    expect(reviewObjects([confirmed])).toEqual([])
    for (const status of ['complete', 'archived'] as const) {
      const edited = updateObject(confirmed, setObjectStatus({ ...confirmed, context: 'Work', metadata: { deadline: '2026-10-01', urgency: 4, effort: 'large' } }, status))
      const saved = reload(edited).objects[0]
      expect(saved.status).toBe(status)
      expect(saved.context).toBe('Work')
      expect(saved.metadata).toMatchObject({ deadline: '2026-10-01', urgency: 4, effort: 'large' })
      if (kind !== 'idea') expect(hasConfirmation(saved)).toBe(true)
    }
  })

  it('preserves edits without letting Save, Complete or Archive confirm proposed work', () => {
    const original = proposal()
    for (const status of ['confirmed', 'complete', 'archived'] as const) {
      const saved = updateObject(original, { ...original, status, context: 'Home' })
      expect(saved.status).toBe('review')
      expect(saved.context).toBe('Home')
      expect(hasConfirmation(saved)).toBe(false)
    }
    expect(reviewObjects([reverseObject(confirmObject(original))])).toHaveLength(1)
  })
})

describe('Bank context folders', () => {
  it.each([
    [' Personal ', 'Personal'], ['HOME', 'Personal'], ['Business', 'Business'],
    [' work ', 'Business'], ['home business', 'Unfiled'], ['Homework', 'Unfiled'],
    ['Carvers', 'Unfiled'], ['', 'Unfiled'],
  ])('groups context %s as %s without inferring from capture text', (context, folder) => {
    const item = { ...confirmObject(proposal('idea')), context, originalContent: 'Business at home' }
    const before = structuredClone(item)
    const folders = bankObjects([item])
    expect(folders[folder as keyof typeof folders]).toEqual([item])
    expect(Object.values(folders).flat()).toHaveLength(1)
    expect(item).toEqual(before)
  })

  it('excludes pending, dismissed, reversed, archived and unconfirmed executable work', () => {
    const original = proposal()
    const confirmed = confirmObject(original)
    expect(Object.values(bankObjects([
      original, reverseObject(original, 'rejected'), reverseObject(confirmed),
      setObjectStatus(confirmed, 'archived'), { ...original, status: 'confirmed' },
    ])).flat()).toEqual([])
    expect(bankObjects([setObjectStatus(confirmed, 'complete')]).Unfiled).toHaveLength(1)
  })

  it('keeps context edits and folder grouping across persistence without changing capture evidence', () => {
    const original = proposal('idea')
    const reload = roundTrip(original)
    const confirmed = confirmObject(original)
    const edited = updateObject(confirmed, { ...confirmed, context: 'Business' })
    const saved = reload(edited)
    expect(bankObjects(saved.objects).Business).toHaveLength(1)
    expect(saved.model!.captures[0].originalContent).toBe(original.originalContent)
    const moved = updateObject(saved.objects[0], { ...saved.objects[0], context: 'Personal' })
    expect(bankObjects(reload(moved).objects).Personal).toHaveLength(1)
  })
})
