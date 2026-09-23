import type { CaptureRecord } from './domain'

export type GroupingKind = 'topic' | 'context' | 'recent'
export type GroupingSuggestionSource = 'deterministic' | 'provider'

export type GroupingSignal =
  | { kind: 'shared-topic'; terms: string[]; weight: number }
  | { kind: 'shared-context'; context: string; weight: number }
  | { kind: 'time-proximity'; minutesApart: number; weight: number }
  | { kind: 'provider-suggestion'; provider: string; weight: number }

export interface GroupingRelationshipCandidate {
  id: string
  type: 'relates_to'
  sourceCaptureId: string
  targetCaptureId: string
  signals: GroupingSignal[]
}

export interface GroupingProposalSnapshot {
  id: string
  captureIds: string[]
  summary: string
  rationale: string
  confidence: number
  groupingKind: GroupingKind
  relationships: GroupingRelationshipCandidate[]
  provenance: {
    source: GroupingSuggestionSource
    generator: string
    generatorVersion: string
    generatedAt: string
    sourceCaptureIds: string[]
  }
}

export interface GroupingProposal extends GroupingProposalSnapshot {
  /** Suggestions can only enter persistence awaiting a review decision. */
  reviewState: 'review' | 'confirmed' | 'rejected' | 'reversed'
}

export interface ConfirmedGroupingRelationship {
  id: string
  type: 'relates_to'
  scope: 'capture'
  sourceCaptureId: string
  targetCaptureId: string
  provenance: {
    proposalId: string
    candidateId: string
    confirmationId: string
    suggestionSource: GroupingSuggestionSource
    signals: GroupingSignal[]
  }
}

export type GroupingReviewDecision =
  | {
    id: string
    decision: 'confirmed'
    at: string
    source: 'grouping-review-confirmation'
    proposal: GroupingProposalSnapshot
    selectedCandidateIds: string[]
    createdRelationshipIds: string[]
    suppressedCandidateIds: string[]
  }
  | {
    id: string
    decision: 'rejected'
    at: string
    source: 'grouping-review-rejection'
    proposal: GroupingProposalSnapshot
  }
  | {
    id: string
    decision: 'reversed'
    at: string
    source: 'grouping-review-reversal'
    proposal: GroupingProposalSnapshot
    reversesDecisionId: string
    removedRelationshipIds: string[]
  }

export interface GroupingReviewState {
  schemaVersion: 1
  proposals: GroupingProposal[]
  /** Only currently active, explicitly confirmed relationships live here. */
  relationships: ConfirmedGroupingRelationship[]
  /** Append-only decisions retain confirmations, rejections, and reversals. */
  history: GroupingReviewDecision[]
}

export const emptyGroupingReviewState = (): GroupingReviewState => ({
  schemaVersion: 1,
  proposals: [],
  relationships: [],
  history: [],
})

const copy = <T>(value: T): T => structuredClone(value)
const validDate = (value: string) => Number.isFinite(Date.parse(value))
const unique = (values: readonly string[]) => values.every(Boolean) && new Set(values).size === values.length
const pairKey = (sourceCaptureId: string, targetCaptureId: string) =>
  [sourceCaptureId, targetCaptureId].sort().join('\u0000')

function snapshot(proposal: GroupingProposal): GroupingProposalSnapshot {
  const { reviewState: _reviewState, ...rest } = proposal
  return copy(rest)
}

function activePairKeys(state: GroupingReviewState): Set<string> {
  return new Set(state.relationships.map(item => pairKey(item.sourceCaptureId, item.targetCaptureId)))
}

function requirePendingProposal(state: GroupingReviewState, proposalId: string): GroupingProposal {
  const proposal = state.proposals.find(item => item.id === proposalId)
  if (!proposal) throw new Error(`Unknown grouping proposal: ${proposalId}`)
  if (proposal.reviewState !== 'review') throw new Error(`Grouping proposal is already ${proposal.reviewState}.`)
  return proposal
}

/** Adds a suggestion to Review. Provider-supplied state can never bypass this gate. */
export function persistGroupingProposal(state: GroupingReviewState, proposal: GroupingProposalSnapshot): GroupingReviewState {
  const existing = state.proposals.find(item => item.id === proposal.id)
  if (existing) {
    if (JSON.stringify(snapshot(existing)) === JSON.stringify(proposal)) return state
    throw new Error(`Grouping proposal ID already exists with different evidence: ${proposal.id}`)
  }
  const next: GroupingReviewState = {
    ...copy(state),
    proposals: [...copy(state.proposals), { ...copy(proposal), reviewState: 'review' }],
  }
  if (!isGroupingReviewState(next)) throw new Error('Grouping proposal is invalid.')
  return next
}

export interface GroupingDecisionInput {
  at: string
  id?: string
  /** Current links may have changed since the suggestion run; recheck them at confirmation. */
  existingRelationships?: readonly Pick<ConfirmedGroupingRelationship, 'type' | 'sourceCaptureId' | 'targetCaptureId'>[]
}

/** Creates only the user-selected links. Existing unordered pairs are suppressed. */
export function confirmGroupingProposal(
  state: GroupingReviewState,
  proposalId: string,
  selectedCandidateIds: readonly string[],
  input: GroupingDecisionInput,
): GroupingReviewState {
  const proposal = requirePendingProposal(state, proposalId)
  if (!validDate(input.at)) throw new Error('Confirmation timestamp is invalid.')
  if (Date.parse(input.at) < Date.parse(proposal.provenance.generatedAt)) throw new Error('Confirmation cannot predate the proposal.')
  const selected = [...new Set(selectedCandidateIds)]
  if (!selected.length) throw new Error('Select at least one suggested relationship.')
  const candidates = selected.map(id => proposal.relationships.find(item => item.id === id) ?? (() => { throw new Error(`Unknown relationship candidate: ${id}`) })())
  const confirmationId = input.id ?? `grouping-confirmation:${proposal.id}:${input.at}`
  if (state.history.some(item => item.id === confirmationId)) throw new Error(`Duplicate grouping decision: ${confirmationId}`)
  const existing = activePairKeys(state)
  input.existingRelationships?.forEach(item => existing.add(pairKey(item.sourceCaptureId, item.targetCaptureId)))
  const created: ConfirmedGroupingRelationship[] = []
  const suppressedCandidateIds: string[] = []
  for (const candidate of candidates) {
    const key = pairKey(candidate.sourceCaptureId, candidate.targetCaptureId)
    if (existing.has(key)) {
      suppressedCandidateIds.push(candidate.id)
      continue
    }
    existing.add(key)
    created.push({
      id: `grouping-relationship:${confirmationId}:${candidate.id}`,
      type: 'relates_to',
      scope: 'capture',
      sourceCaptureId: candidate.sourceCaptureId,
      targetCaptureId: candidate.targetCaptureId,
      provenance: {
        proposalId: proposal.id,
        candidateId: candidate.id,
        confirmationId,
        suggestionSource: proposal.provenance.source,
        signals: copy(candidate.signals),
      },
    })
  }
  const decision: GroupingReviewDecision = {
    id: confirmationId,
    decision: 'confirmed',
    at: input.at,
    source: 'grouping-review-confirmation',
    proposal: snapshot(proposal),
    selectedCandidateIds: selected,
    createdRelationshipIds: created.map(item => item.id),
    suppressedCandidateIds,
  }
  return {
    ...copy(state),
    proposals: state.proposals.map(item => item.id === proposal.id ? { ...copy(item), reviewState: 'confirmed' } : copy(item)),
    relationships: [...copy(state.relationships), ...created],
    history: [...copy(state.history), decision],
  }
}

/** Rejecting a suggestion records the review decision and creates no relationship. */
export function rejectGroupingProposal(
  state: GroupingReviewState,
  proposalId: string,
  input: GroupingDecisionInput,
): GroupingReviewState {
  const proposal = requirePendingProposal(state, proposalId)
  if (!validDate(input.at)) throw new Error('Rejection timestamp is invalid.')
  if (Date.parse(input.at) < Date.parse(proposal.provenance.generatedAt)) throw new Error('Rejection cannot predate the proposal.')
  const id = input.id ?? `grouping-rejection:${proposal.id}:${input.at}`
  if (state.history.some(item => item.id === id)) throw new Error(`Duplicate grouping decision: ${id}`)
  return {
    ...copy(state),
    proposals: state.proposals.map(item => item.id === proposal.id ? { ...copy(item), reviewState: 'rejected' } : copy(item)),
    history: [...copy(state.history), {
      id,
      decision: 'rejected',
      at: input.at,
      source: 'grouping-review-rejection',
      proposal: snapshot(proposal),
    }],
  }
}

/** Removes exactly one confirmation's active links and leaves all source captures/history intact. */
export function reverseGroupingConfirmation(
  state: GroupingReviewState,
  confirmationId: string,
  input: GroupingDecisionInput,
): GroupingReviewState {
  const confirmation = state.history.find((item): item is Extract<GroupingReviewDecision, { decision: 'confirmed' }> =>
    item.id === confirmationId && item.decision === 'confirmed')
  if (!confirmation) throw new Error(`Unknown grouping confirmation: ${confirmationId}`)
  if (state.history.some(item => item.decision === 'reversed' && item.reversesDecisionId === confirmationId)) {
    throw new Error('Grouping confirmation is already reversed.')
  }
  if (!validDate(input.at)) throw new Error('Reversal timestamp is invalid.')
  if (Date.parse(input.at) < Date.parse(confirmation.at)) throw new Error('Reversal cannot predate the confirmation.')
  const id = input.id ?? `grouping-reversal:${confirmation.proposal.id}:${input.at}`
  if (state.history.some(item => item.id === id)) throw new Error(`Duplicate grouping decision: ${id}`)
  const created = new Set(confirmation.createdRelationshipIds)
  const removed = state.relationships.filter(item => created.has(item.id)).map(item => item.id)
  return {
    ...copy(state),
    proposals: state.proposals.map(item => item.id === confirmation.proposal.id ? { ...copy(item), reviewState: 'reversed' } : copy(item)),
    relationships: state.relationships.filter(item => !created.has(item.id)).map(copy),
    history: [...copy(state.history), {
      id,
      decision: 'reversed',
      at: input.at,
      source: 'grouping-review-reversal',
      proposal: copy(confirmation.proposal),
      reversesDecisionId: confirmation.id,
      removedRelationshipIds: removed,
    }],
  }
}

/** Cancel is deliberately an identity operation: it records no decision and changes no links. */
export function cancelGroupingReview(state: GroupingReviewState): GroupingReviewState {
  return state
}

function isSignal(value: unknown): value is GroupingSignal {
  if (!value || typeof value !== 'object') return false
  const signal = value as Partial<GroupingSignal>
  if (typeof signal.weight !== 'number' || !Number.isFinite(signal.weight) || signal.weight <= 0 || signal.weight > 1) return false
  if (signal.kind === 'shared-topic') return Array.isArray(signal.terms) && unique(signal.terms) && signal.terms.every(term => typeof term === 'string')
  if (signal.kind === 'shared-context') return typeof signal.context === 'string' && signal.context.length > 0
  if (signal.kind === 'time-proximity') return typeof signal.minutesApart === 'number' && Number.isFinite(signal.minutesApart) && signal.minutesApart >= 0
  return signal.kind === 'provider-suggestion' && typeof signal.provider === 'string' && signal.provider.length > 0
}

function isCandidate(value: unknown, captureIds?: Set<string>): value is GroupingRelationshipCandidate {
  if (!value || typeof value !== 'object') return false
  const item = value as Partial<GroupingRelationshipCandidate>
  return typeof item.id === 'string' && item.id.length > 0 && item.type === 'relates_to' &&
    typeof item.sourceCaptureId === 'string' && typeof item.targetCaptureId === 'string' &&
    item.sourceCaptureId < item.targetCaptureId && (!captureIds || (captureIds.has(item.sourceCaptureId) && captureIds.has(item.targetCaptureId))) &&
    Array.isArray(item.signals) && item.signals.length > 0 && item.signals.every(isSignal)
}

function isSnapshot(value: unknown, captureIds?: Set<string>): value is GroupingProposalSnapshot {
  if (!value || typeof value !== 'object') return false
  const item = value as Partial<GroupingProposalSnapshot>
  const p = item.provenance
  return typeof item.id === 'string' && item.id.length > 0 && Array.isArray(item.captureIds) && item.captureIds.length >= 2 &&
    unique(item.captureIds) && (!captureIds || item.captureIds.every(id => captureIds.has(id))) &&
    typeof item.summary === 'string' && item.summary.trim().length > 0 && typeof item.rationale === 'string' && item.rationale.trim().length > 0 &&
    typeof item.confidence === 'number' && Number.isFinite(item.confidence) && item.confidence >= 0 && item.confidence <= 1 &&
    ['topic', 'context', 'recent'].includes(item.groupingKind as GroupingKind) && Array.isArray(item.relationships) && item.relationships.length > 0 &&
    unique(item.relationships.map(candidate => candidate.id)) &&
    new Set(item.relationships.map(candidate => pairKey(candidate.sourceCaptureId, candidate.targetCaptureId))).size === item.relationships.length &&
    item.relationships.every(candidate => isCandidate(candidate, new Set(item.captureIds))) &&
    !!p && ['deterministic', 'provider'].includes(p.source) && typeof p.generator === 'string' && p.generator.length > 0 &&
    typeof p.generatorVersion === 'string' && p.generatorVersion.length > 0 && typeof p.generatedAt === 'string' && validDate(p.generatedAt) &&
    Array.isArray(p.sourceCaptureIds) && unique(p.sourceCaptureIds) && JSON.stringify(p.sourceCaptureIds) === JSON.stringify(item.captureIds)
}

/** Strict validator used by schema-v2 loading before grouping data is exposed. */
export function isGroupingReviewState(value: unknown, captures?: readonly Pick<CaptureRecord, 'id'>[]): value is GroupingReviewState {
  if (!value || typeof value !== 'object') return false
  const state = value as GroupingReviewState
  if (Object.keys(state).some(key => !['schemaVersion', 'proposals', 'relationships', 'history'].includes(key)) || state.schemaVersion !== 1 ||
      !Array.isArray(state.proposals) || !Array.isArray(state.relationships) || !Array.isArray(state.history)) return false
  const captureIds = captures ? new Set(captures.map(item => item.id)) : undefined
  if (!unique(state.proposals.map(item => item.id)) || !unique(state.relationships.map(item => item.id)) || !unique(state.history.map(item => item.id))) return false
  if (!state.proposals.every(item => isSnapshot(item, captureIds) && ['review', 'confirmed', 'rejected', 'reversed'].includes(item.reviewState))) return false
  const proposalIds = new Set(state.proposals.map(item => item.id))
  const confirmationIds = new Set(state.history.filter(item => item.decision === 'confirmed').map(item => item.id))
  if (!state.relationships.every(item => item.type === 'relates_to' && item.scope === 'capture' &&
    typeof item.id === 'string' && isCandidate({ id: item.provenance?.candidateId, type: item.type, sourceCaptureId: item.sourceCaptureId,
      targetCaptureId: item.targetCaptureId, signals: item.provenance?.signals }, captureIds) &&
    proposalIds.has(item.provenance.proposalId) && confirmationIds.has(item.provenance.confirmationId) &&
    ['deterministic', 'provider'].includes(item.provenance.suggestionSource))) return false
  if (new Set(state.relationships.map(item => pairKey(item.sourceCaptureId, item.targetCaptureId))).size !== state.relationships.length) return false
  if (!state.history.every(item => {
    if (!item || typeof item !== 'object' || !validDate(item.at) || !isSnapshot(item.proposal, captureIds) || !proposalIds.has(item.proposal.id)) return false
    const persisted = state.proposals.find(proposal => proposal.id === item.proposal.id)
    if (!persisted || JSON.stringify(snapshot(persisted)) !== JSON.stringify(item.proposal) || Date.parse(item.at) < Date.parse(item.proposal.provenance.generatedAt)) return false
    if (item.decision === 'confirmed') return item.source === 'grouping-review-confirmation' && unique(item.selectedCandidateIds) && item.selectedCandidateIds.length > 0 &&
      item.selectedCandidateIds.every(id => item.proposal.relationships.some(candidate => candidate.id === id)) && unique(item.createdRelationshipIds) && unique(item.suppressedCandidateIds) &&
      item.createdRelationshipIds.length + item.suppressedCandidateIds.length === item.selectedCandidateIds.length &&
      item.suppressedCandidateIds.every(id => item.selectedCandidateIds.includes(id))
    if (item.decision === 'rejected') return item.source === 'grouping-review-rejection'
    return item.decision === 'reversed' && item.source === 'grouping-review-reversal' && confirmationIds.has(item.reversesDecisionId) && unique(item.removedRelationshipIds)
  })) return false
  const activeRelationshipIds = new Set(state.relationships.map(item => item.id))
  for (const proposal of state.proposals) {
    const primary = state.history.filter((item): item is Exclude<GroupingReviewDecision, { decision: 'reversed' }> =>
      item.proposal.id === proposal.id && item.decision !== 'reversed')
    if (primary.length > 1) return false
    if (!primary.length) {
      if (proposal.reviewState !== 'review') return false
      continue
    }
    const decision = primary[0]
    if (decision.decision === 'rejected') {
      if (proposal.reviewState !== 'rejected') return false
      continue
    }
    const reversals = state.history.filter((item): item is Extract<GroupingReviewDecision, { decision: 'reversed' }> =>
      item.decision === 'reversed' && item.reversesDecisionId === decision.id)
    if (reversals.length > 1 || (reversals[0] && reversals[0].proposal.id !== proposal.id)) return false
    if (reversals.length) {
      if (proposal.reviewState !== 'reversed' || JSON.stringify(reversals[0].removedRelationshipIds) !== JSON.stringify(decision.createdRelationshipIds) ||
          decision.createdRelationshipIds.some(id => activeRelationshipIds.has(id)) || Date.parse(reversals[0].at) < Date.parse(decision.at) ||
          state.history.indexOf(reversals[0]) < state.history.indexOf(decision)) return false
    } else if (proposal.reviewState !== 'confirmed' || decision.createdRelationshipIds.some(id => !activeRelationshipIds.has(id))) return false
    for (const relationshipId of decision.createdRelationshipIds) {
      const relationship = state.relationships.find(item => item.id === relationshipId)
      const candidate = proposal.relationships.find(item => item.id === relationship?.provenance.candidateId)
      if (!reversals.length && (!relationship || !candidate || relationship.provenance.confirmationId !== decision.id ||
          !decision.selectedCandidateIds.includes(relationship.provenance.candidateId) || decision.suppressedCandidateIds.includes(relationship.provenance.candidateId) ||
          relationship.provenance.suggestionSource !== proposal.provenance.source || JSON.stringify(relationship.provenance.signals) !== JSON.stringify(candidate.signals))) return false
    }
  }
  return state.relationships.every(relationship => state.history.some(item =>
    item.decision === 'confirmed' && item.id === relationship.provenance.confirmationId && item.createdRelationshipIds.includes(relationship.id)))
}
