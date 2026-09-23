import type { CaptureRecord } from './domain'
import type { GroupingKind, GroupingProposal, GroupingProposalSnapshot, GroupingRelationshipCandidate, GroupingSignal } from './groupingProposal'

export interface ExistingCaptureRelationship {
  type: 'relates_to'
  sourceCaptureId: string
  targetCaptureId: string
}

export interface GroupingSuggestionInput {
  captures: readonly CaptureRecord[]
  existingRelationships?: readonly ExistingCaptureRelationship[]
  /** Required for deterministic provenance; callers choose the review-run timestamp. */
  generatedAt: string
}

/** Future providers implement this seam. They still pass through validation before Review. */
export interface GroupingSuggestionProvider {
  readonly id: string
  readonly version: string
  suggest(input: GroupingSuggestionInput): Promise<unknown>
}

const STOP_WORDS = new Set(['about', 'after', 'again', 'also', 'and', 'are', 'but', 'for', 'from', 'have', 'into', 'just', 'need', 'that', 'the', 'then', 'this', 'todo', 'want', 'with', 'you', 'your'])
const pairKey = (a: string, b: string) => [a, b].sort().join('\u0000')
const orderedPair = (a: string, b: string) => a < b ? [a, b] as const : [b, a] as const
const stableHash = (value: string) => {
  let hash = 2166136261
  for (let index = 0; index < value.length; index += 1) hash = Math.imul(hash ^ value.charCodeAt(index), 16777619)
  return (hash >>> 0).toString(36)
}
const tokens = (value: string) => [...new Set((value.toLocaleLowerCase().match(/[\p{L}\p{N}]+/gu) ?? [])
  .filter(word => word.length >= 3 && !STOP_WORDS.has(word)))].sort()
const cleanContext = (value?: string) => value?.trim().toLocaleLowerCase() || undefined
const validDate = (value: string) => Number.isFinite(Date.parse(value))

function signalsFor(left: CaptureRecord, right: CaptureRecord): GroupingSignal[] {
  const signals: GroupingSignal[] = []
  const leftTerms = tokens(left.originalContent)
  const rightTerms = new Set(tokens(right.originalContent))
  const shared = leftTerms.filter(term => rightTerms.has(term))
  if (shared.length) {
    const union = new Set([...leftTerms, ...rightTerms]).size
    const ratio = shared.length / Math.max(1, union)
    const weight = Math.min(.75, .5 + ratio * .5)
    signals.push({ kind: 'shared-topic', terms: shared, weight })
  }
  const leftContext = cleanContext(left.context)
  if (leftContext && leftContext === cleanContext(right.context)) {
    signals.push({ kind: 'shared-context', context: left.context!.trim(), weight: .6 })
  }
  if (validDate(left.createdAt) && validDate(right.createdAt)) {
    const minutesApart = Math.round(Math.abs(Date.parse(left.createdAt) - Date.parse(right.createdAt)) / 60_000)
    const weight = minutesApart <= 30 ? .6 : minutesApart <= 120 ? .35 : minutesApart <= 1_440 ? .15 : 0
    if (weight) signals.push({ kind: 'time-proximity', minutesApart, weight })
  }
  return signals
}

function qualifies(signals: readonly GroupingSignal[]) {
  return signals.reduce((sum, signal) => sum + signal.weight, 0) >= .55
}

function dominantKind(candidates: readonly GroupingRelationshipCandidate[]): GroupingKind {
  const totals = new Map<GroupingSignal['kind'], number>()
  candidates.flatMap(item => item.signals).forEach(signal => totals.set(signal.kind, (totals.get(signal.kind) ?? 0) + signal.weight))
  const kind = [...totals].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))[0]?.[0]
  return kind === 'shared-topic' ? 'topic' : kind === 'shared-context' ? 'context' : 'recent'
}

function proposalText(kind: GroupingKind, captureCount: number, candidates: readonly GroupingRelationshipCandidate[]) {
  const topics = [...new Set(candidates.flatMap(item => item.signals.flatMap(signal => signal.kind === 'shared-topic' ? signal.terms : [])))].slice(0, 3)
  const contexts = [...new Set(candidates.flatMap(item => item.signals.flatMap(signal => signal.kind === 'shared-context' ? [signal.context] : [])))].slice(0, 2)
  const summary = kind === 'topic' && topics.length ? `${captureCount} related thoughts about ${topics.join(', ')}`
    : kind === 'context' && contexts.length ? `${captureCount} related thoughts in ${contexts.join(', ')}`
      : `${captureCount} thoughts captured close together`
  const reasons = [topics.length ? `shared terms: ${topics.join(', ')}` : '', contexts.length ? `shared context: ${contexts.join(', ')}` : '',
    candidates.some(item => item.signals.some(signal => signal.kind === 'time-proximity')) ? 'capture timing is close' : ''].filter(Boolean)
  return { summary, rationale: `Suggested because ${reasons.join('; ')}.` }
}

/** Side-effect-free deterministic baseline. It creates proposals only; never relationships. */
export function suggestGroupingProposals(input: GroupingSuggestionInput): GroupingProposal[] {
  if (!validDate(input.generatedAt)) throw new Error('Suggestion timestamp is invalid.')
  const captures = [...input.captures].sort((a, b) => a.id.localeCompare(b.id))
  if (new Set(captures.map(item => item.id)).size !== captures.length) throw new Error('Capture IDs must be unique.')
  const existing = new Set((input.existingRelationships ?? []).map(item => pairKey(item.sourceCaptureId, item.targetCaptureId)))
  const candidates: GroupingRelationshipCandidate[] = []
  for (let left = 0; left < captures.length; left += 1) {
    for (let right = left + 1; right < captures.length; right += 1) {
      const [sourceCaptureId, targetCaptureId] = orderedPair(captures[left].id, captures[right].id)
      if (existing.has(pairKey(sourceCaptureId, targetCaptureId))) continue
      const signals = signalsFor(captures[left], captures[right])
      if (!qualifies(signals)) continue
      candidates.push({ id: `grouping-candidate:${stableHash(`${sourceCaptureId}\u0000${targetCaptureId}`)}`,
        type: 'relates_to', sourceCaptureId, targetCaptureId, signals })
    }
  }
  const neighbors = new Map<string, Set<string>>()
  candidates.forEach(candidate => {
    if (!neighbors.has(candidate.sourceCaptureId)) neighbors.set(candidate.sourceCaptureId, new Set())
    if (!neighbors.has(candidate.targetCaptureId)) neighbors.set(candidate.targetCaptureId, new Set())
    neighbors.get(candidate.sourceCaptureId)!.add(candidate.targetCaptureId)
    neighbors.get(candidate.targetCaptureId)!.add(candidate.sourceCaptureId)
  })
  const seen = new Set<string>()
  const components: string[][] = []
  for (const start of [...neighbors.keys()].sort()) {
    if (seen.has(start)) continue
    const stack = [start], component: string[] = []
    while (stack.length) {
      const current = stack.pop()!
      if (seen.has(current)) continue
      seen.add(current); component.push(current)
      stack.push(...[...(neighbors.get(current) ?? [])].sort().reverse())
    }
    components.push(component.sort())
  }
  return components.map(captureIds => {
    const component = new Set(captureIds)
    const relationships = candidates.filter(item => component.has(item.sourceCaptureId) && component.has(item.targetCaptureId))
    const groupingKind = dominantKind(relationships)
    const text = proposalText(groupingKind, captureIds.length, relationships)
    const score = relationships.flatMap(item => item.signals).reduce((sum, signal) => sum + signal.weight, 0) / relationships.length
    return {
      id: `grouping-proposal:${stableHash(`${captureIds.join('\u0000')}:${relationships.map(item => item.id).join(',')}:${input.generatedAt}`)}`,
      captureIds,
      ...text,
      confidence: Math.min(.95, Number(score.toFixed(2))),
      groupingKind,
      relationships,
      provenance: { source: 'deterministic', generator: 'threadline-grouping-rules', generatorVersion: '1', generatedAt: input.generatedAt, sourceCaptureIds: [...captureIds] },
      reviewState: 'review',
    }
  })
}

/** Validates an eventual provider proposal and always returns review-only state. */
export function validateProviderGroupingProposal(
  input: GroupingSuggestionInput,
  value: unknown,
  provider: Pick<GroupingSuggestionProvider, 'id' | 'version'>,
): GroupingProposal {
  if (!value || typeof value !== 'object') throw new Error('Grouping provider response is not an object.')
  const raw = value as Record<string, unknown>
  if (typeof raw.summary !== 'string' || !raw.summary.trim() || typeof raw.rationale !== 'string' || !raw.rationale.trim()) throw new Error('Grouping provider response is missing explanation.')
  if (typeof raw.confidence !== 'number' || !Number.isFinite(raw.confidence) || raw.confidence < 0 || raw.confidence > 1) throw new Error('Grouping provider confidence is invalid.')
  if (!['topic', 'context', 'recent'].includes(raw.groupingKind as string) || !Array.isArray(raw.relationships)) throw new Error('Grouping provider relationships are invalid.')
  const available = new Set(input.captures.map(item => item.id))
  const existing = new Set((input.existingRelationships ?? []).map(item => pairKey(item.sourceCaptureId, item.targetCaptureId)))
  const seen = new Set<string>()
  const relationships: GroupingRelationshipCandidate[] = raw.relationships.map((item, index) => {
    if (!item || typeof item !== 'object') throw new Error('Grouping provider relationship is invalid.')
    const relationship = item as Record<string, unknown>
    if (typeof relationship.sourceCaptureId !== 'string' || typeof relationship.targetCaptureId !== 'string' ||
        !available.has(relationship.sourceCaptureId) || !available.has(relationship.targetCaptureId) || relationship.sourceCaptureId === relationship.targetCaptureId) {
      throw new Error('Grouping provider referenced an unknown capture.')
    }
    const [sourceCaptureId, targetCaptureId] = orderedPair(relationship.sourceCaptureId, relationship.targetCaptureId)
    const key = pairKey(sourceCaptureId, targetCaptureId)
    if (existing.has(key) || seen.has(key)) throw new Error('Grouping provider proposed a duplicate relationship.')
    seen.add(key)
    return { id: `grouping-provider-candidate:${stableHash(`${provider.id}:${sourceCaptureId}\u0000${targetCaptureId}:${index}`)}`,
      type: 'relates_to', sourceCaptureId, targetCaptureId, signals: [{ kind: 'provider-suggestion', provider: provider.id, weight: Math.max(.01, raw.confidence as number) }] }
  })
  if (!relationships.length) throw new Error('Grouping provider proposed no relationships.')
  const captureIds = [...new Set(relationships.flatMap(item => [item.sourceCaptureId, item.targetCaptureId]))].sort()
  const proposal: GroupingProposalSnapshot = {
    id: `grouping-provider-proposal:${stableHash(`${provider.id}:${captureIds.join('\u0000')}:${input.generatedAt}`)}`,
    captureIds,
    summary: raw.summary.trim(),
    rationale: raw.rationale.trim(),
    confidence: raw.confidence,
    groupingKind: raw.groupingKind as GroupingKind,
    relationships,
    provenance: { source: 'provider', generator: provider.id, generatorVersion: provider.version, generatedAt: input.generatedAt, sourceCaptureIds: [...captureIds] },
  }
  return { ...proposal, reviewState: 'review' }
}

export const deterministicGroupingSuggestionProvider: GroupingSuggestionProvider = {
  id: 'threadline-grouping-rules',
  version: '1',
  async suggest(input) { return suggestGroupingProposals(input) },
}
