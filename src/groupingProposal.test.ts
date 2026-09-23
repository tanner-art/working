import { describe, expect, it } from 'vitest'
import type { CaptureRecord, PersistedState } from './domain'
import { isPersistedState, legacyUiProjection, migrateLegacyState, reconcileLegacyUi } from './migration'
import {
  cancelGroupingReview,
  confirmGroupingProposal,
  emptyGroupingReviewState,
  isGroupingReviewState,
  persistGroupingProposal,
  rejectGroupingProposal,
  reverseGroupingConfirmation,
} from './groupingProposal'
import { suggestGroupingProposals, validateProviderGroupingProposal } from './groupingSuggestions'

const capture = (id: string, content: string, createdAt: string, context?: string): CaptureRecord => ({
  id, source: 'text', createdAt, originalContent: content, context, evidence: 'text-only',
})
const captures = [
  capture('capture:a', 'Plan launch campaign', '2026-09-23T10:00:00Z', 'Launch'),
  capture('capture:b', 'Draft launch announcement', '2026-09-23T10:20:00Z', 'Launch'),
  capture('capture:c', 'Buy groceries', '2026-09-20T10:00:00Z', 'Home'),
]
const generatedAt = '2026-09-23T11:00:00Z'
const proposal = () => suggestGroupingProposals({ captures, generatedAt })[0]

describe('review-only grouping decisions', () => {
  it('persists a proposal in Review without creating a relationship and cancel is inert', () => {
    const original = emptyGroupingReviewState()
    const next = persistGroupingProposal(original, proposal())
    expect(original).toEqual(emptyGroupingReviewState())
    expect(next.proposals[0].reviewState).toBe('review')
    expect(next.relationships).toEqual([])
    expect(cancelGroupingReview(next)).toBe(next)
  })

  it('confirms only a selected subset, suppresses existing pairs, and retains exact provenance', () => {
    const baseProposal = proposal()
    const extra = { ...baseProposal.relationships[0], id: 'candidate:extra', sourceCaptureId: 'capture:a', targetCaptureId: 'capture:c' }
    const pending = persistGroupingProposal(emptyGroupingReviewState(), { ...baseProposal, captureIds: captures.map(item => item.id),
      provenance: { ...baseProposal.provenance, sourceCaptureIds: captures.map(item => item.id) }, relationships: [...baseProposal.relationships, extra] })
    const first = confirmGroupingProposal(pending, baseProposal.id, [baseProposal.relationships[0].id], { at: '2026-09-23T12:00:00Z', id: 'confirm:1' })
    expect(first.relationships).toHaveLength(1)
    expect(first.relationships[0]).toMatchObject({ type: 'relates_to', scope: 'capture', provenance: { proposalId: baseProposal.id, confirmationId: 'confirm:1' } })
    expect(first.history[0]).toMatchObject({ selectedCandidateIds: [baseProposal.relationships[0].id], createdRelationshipIds: [first.relationships[0].id],
      proposal: { provenance: { ...baseProposal.provenance, sourceCaptureIds: captures.map(item => item.id) } } })
    expect(pending.relationships).toEqual([])

    const repeat = persistGroupingProposal(first, { ...baseProposal, id: 'proposal:repeat' })
    const suppressed = confirmGroupingProposal(repeat, 'proposal:repeat', [baseProposal.relationships[0].id], { at: '2026-09-23T12:01:00Z', id: 'confirm:2' })
    expect(suppressed.relationships).toEqual(first.relationships)
    expect(suppressed.history.at(-1)).toMatchObject({ suppressedCandidateIds: [baseProposal.relationships[0].id], createdRelationshipIds: [] })

    const raced = persistGroupingProposal(emptyGroupingReviewState(), { ...baseProposal, id: 'proposal:race' })
    const rechecked = confirmGroupingProposal(raced, 'proposal:race', [baseProposal.relationships[0].id], { at: '2026-09-23T12:02:00Z',
      existingRelationships: [{ type: 'relates_to', sourceCaptureId: 'capture:b', targetCaptureId: 'capture:a' }] })
    expect(rechecked.relationships).toEqual([])
    expect(rechecked.history[0]).toMatchObject({ suppressedCandidateIds: [baseProposal.relationships[0].id] })
  })

  it('rejects without side effects and prevents later confirmation', () => {
    const pending = persistGroupingProposal(emptyGroupingReviewState(), proposal())
    const rejected = rejectGroupingProposal(pending, proposal().id, { at: '2026-09-23T12:00:00Z' })
    expect(rejected.relationships).toEqual([])
    expect(rejected.proposals[0].reviewState).toBe('rejected')
    expect(() => confirmGroupingProposal(rejected, proposal().id, [proposal().relationships[0].id], { at: '2026-09-23T12:01:00Z' })).toThrow('already rejected')
  })

  it('reverses only links created by that confirmation while preserving proposal and history', () => {
    const pending = persistGroupingProposal(emptyGroupingReviewState(), proposal())
    const confirmed = confirmGroupingProposal(pending, proposal().id, [proposal().relationships[0].id], { at: '2026-09-23T12:00:00Z', id: 'confirm:1' })
    const reversed = reverseGroupingConfirmation(confirmed, 'confirm:1', { at: '2026-09-23T13:00:00Z', id: 'reverse:1' })
    expect(reversed.relationships).toEqual([])
    expect(reversed.proposals[0]).toMatchObject({ id: proposal().id, reviewState: 'reversed', captureIds: ['capture:a', 'capture:b'] })
    expect(reversed.history).toHaveLength(2)
    expect(reversed.history[0]).toEqual(confirmed.history[0])
    expect(reversed.history[1]).toMatchObject({ reversesDecisionId: 'confirm:1', removedRelationshipIds: confirmed.history[0].decision === 'confirmed' ? confirmed.history[0].createdRelationshipIds : [] })
  })

  it('rejects decisions that predate the state they act on', () => {
    const pending = persistGroupingProposal(emptyGroupingReviewState(), proposal())
    expect(() => confirmGroupingProposal(pending, proposal().id, [proposal().relationships[0].id], { at: '2026-09-23T10:59:59Z' }))
      .toThrow('cannot predate the proposal')
    expect(() => rejectGroupingProposal(pending, proposal().id, { at: '2026-09-23T10:59:59Z' }))
      .toThrow('cannot predate the proposal')
    const confirmed = confirmGroupingProposal(pending, proposal().id, [proposal().relationships[0].id], { at: '2026-09-23T12:00:00Z', id: 'confirm:chronology' })
    expect(() => reverseGroupingConfirmation(confirmed, 'confirm:chronology', { at: '2026-09-23T11:59:59Z' }))
      .toThrow('cannot predate the confirmation')
  })
})

describe('validated persistence', () => {
  it('roundtrips additive grouping review state without changing captures or interpretations', () => {
    const objects = captures.map(item => ({ id: item.id.replace('capture:', ''), kind: 'idea' as const, originalContent: item.originalContent,
      source: item.source, createdAt: item.createdAt, context: item.context,
      interpretation: { summary: item.originalContent, suggestedKind: 'idea' as const, rationale: 'Explicit' }, confidence: .9,
      relationships: [], history: [{ at: item.createdAt, event: 'Captured' }], status: 'confirmed' as const, metadata: {} }))
    const legacy = { objects, canvas: [] }
    const model = migrateLegacyState(legacy)
    const pending = persistGroupingProposal(emptyGroupingReviewState(), proposal())
    model.groupingReview = confirmGroupingProposal(pending, proposal().id, [proposal().relationships[0].id], { at: '2026-09-23T12:00:00Z' })
    expect(isPersistedState(model)).toBe(true)
    const decoded = JSON.parse(JSON.stringify(model)) as PersistedState
    expect(isPersistedState(decoded)).toBe(true)
    expect(decoded.captures).toEqual(captures)
    expect(decoded.groupingReview).toEqual(model.groupingReview)
  })

  it('survives the legacy UI reconcile path unchanged', () => {
    const item = { id: 'a', kind: 'idea' as const, originalContent: 'Launch plan', source: 'text' as const, createdAt: '2026-09-23T10:00:00Z',
      context: 'Launch', interpretation: { summary: 'Launch plan', suggestedKind: 'idea' as const, rationale: 'Explicit' }, confidence: .9,
      relationships: [], history: [{ at: '2026-09-23T10:00:00Z', event: 'Captured' }], status: 'confirmed' as const, metadata: {} }
    const other = { ...structuredClone(item), id: 'b', originalContent: 'Launch campaign', createdAt: '2026-09-23T10:10:00Z' }
    const model = migrateLegacyState({ objects: [item, other], canvas: [] })
    const suggestions = suggestGroupingProposals({ captures: model.captures, generatedAt })
    model.groupingReview = persistGroupingProposal(emptyGroupingReviewState(), suggestions[0])
    const view = legacyUiProjection(model)
    const reconciled = reconcileLegacyUi(view)
    expect(reconciled.groupingReview).toEqual(model.groupingReview)
    expect(reconciled.captures).toEqual(model.captures)
    expect(reconciled.interpretations).toEqual(model.interpretations)
  })

  it('reversal leaves every persisted capture and interpretation byte-for-byte intact', () => {
    const objects = captures.slice(0, 2).map(item => ({ id: item.id.replace('capture:', ''), kind: 'idea' as const, originalContent: item.originalContent,
      source: item.source, createdAt: item.createdAt, context: item.context,
      interpretation: { summary: item.originalContent, suggestedKind: 'idea' as const, rationale: 'Explicit' }, confidence: .9,
      relationships: [], history: [{ at: item.createdAt, event: 'Captured' }], status: 'confirmed' as const, metadata: {} }))
    const model = migrateLegacyState({ objects, canvas: [] })
    const originalEvidence = { captures: structuredClone(model.captures), interpretations: structuredClone(model.interpretations), semanticObjects: structuredClone(model.semanticObjects) }
    const suggested = suggestGroupingProposals({ captures: model.captures, generatedAt })[0]
    const pending = persistGroupingProposal(emptyGroupingReviewState(), suggested)
    const confirmed = confirmGroupingProposal(pending, suggested.id, [suggested.relationships[0].id], { at: '2026-09-23T12:00:00Z', id: 'confirm:preserve' })
    model.groupingReview = reverseGroupingConfirmation(confirmed, 'confirm:preserve', { at: '2026-09-23T13:00:00Z' })
    expect(isPersistedState(model)).toBe(true)
    expect({ captures: model.captures, interpretations: model.interpretations, semanticObjects: model.semanticObjects }).toEqual(originalEvidence)
    expect(model.groupingReview.relationships).toEqual([])
  })

  it('rejects unknown captures, forged accepted proposals, and malformed decision history', () => {
    const pending = persistGroupingProposal(emptyGroupingReviewState(), proposal())
    expect(isGroupingReviewState(pending, captures)).toBe(true)
    const unknown = structuredClone(pending)
    unknown.proposals[0].captureIds[0] = 'capture:missing'
    expect(isGroupingReviewState(unknown, captures)).toBe(false)
    const forged = structuredClone(pending) as unknown as { proposals: { reviewState: string }[] }
    forged.proposals[0].reviewState = 'accepted'
    expect(isGroupingReviewState(forged, captures)).toBe(false)
    const decided = confirmGroupingProposal(pending, proposal().id, [proposal().relationships[0].id], { at: '2026-09-23T12:00:00Z' })
    const damaged = structuredClone(decided)
    damaged.relationships[0].provenance.confirmationId = 'missing'
    expect(isGroupingReviewState(damaged, captures)).toBe(false)
    const wrongState = structuredClone(decided)
    wrongState.proposals[0].reviewState = 'reversed'
    expect(isGroupingReviewState(wrongState, captures)).toBe(false)
    const missingActiveLink = structuredClone(decided)
    missingActiveLink.relationships = []
    expect(isGroupingReviewState(missingActiveLink, captures)).toBe(false)
  })
})

describe('provider boundary', () => {
  it('forces provider output into Review and ignores a forged accepted state', () => {
    const result = validateProviderGroupingProposal({ captures, generatedAt }, {
      summary: 'Launch work', rationale: 'The content appears related.', confidence: .8, groupingKind: 'topic', reviewState: 'accepted',
      relationships: [{ sourceCaptureId: 'capture:b', targetCaptureId: 'capture:a' }],
    }, { id: 'future-provider', version: '2026-09' })
    expect(result.reviewState).toBe('review')
    expect(result.relationships[0]).toMatchObject({ sourceCaptureId: 'capture:a', targetCaptureId: 'capture:b', type: 'relates_to' })
    expect(result.relationships[0].signals).toEqual([{ kind: 'provider-suggestion', provider: 'future-provider', weight: .8 }])
    expect(JSON.stringify(result.relationships[0].signals)).not.toContain('provider-suggested')
    expect(result.provenance).toMatchObject({ source: 'provider', generator: 'future-provider' })
  })
})
