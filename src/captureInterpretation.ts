import type { CaptureRecord, ThoughtObject } from './domain'
import { interpretationService, type InterpretationService } from './interpretationService'
import { makeObject } from './store'

/** Adapter for the current UI/schema-v2 writer; heuristic code never sees it.
 * The writer records the proposal as an Interpretation and materializes an
 * unresolved ReminderInstruction for the legacy reminder route. No target,
 * obligation, event, deadline or delivery eligibility is inferred here.
 */
export async function createInterpretedObject(
  content: string,
  context?: string,
  service: InterpretationService = interpretationService,
): Promise<ThoughtObject> {
  const item = makeObject({ kind: 'idea', originalContent: content, source: 'text', confidence: 0,
    interpretation: { summary: content, suggestedKind: 'idea', rationale: 'Awaiting interpretation.' } })
  item.context = context
  const capture: CaptureRecord = Object.freeze({ id: `capture:${item.id}`, source: item.source,
    createdAt: item.createdAt, originalContent: content, context, evidence: 'text-only' })
  const proposal = await service.interpret(capture)
  // Fail rather than silently discard meaning the compatibility writer cannot
  // represent. A future provider must implement this single-capture contract.
  if (!Number.isFinite(proposal.confidence) || proposal.confidence < 0 || proposal.confidence > 1 ||
    (proposal.proposedKind === 'action' && proposal.proposedAction.summary !== proposal.summary) ||
    (proposal.proposedKind === 'unresolved' && (
      proposal.proposedReminder.trigger.wording !== content ||
      proposal.proposedReminder.captureIds.length !== 1 || proposal.proposedReminder.captureIds[0] !== capture.id ||
      proposal.proposedReminder.trigger.legacyDate !== proposal.suggestedDate))) {
    throw new Error('Interpretation cannot be represented by the current capture model.')
  }
  const kind = proposal.proposedKind === 'unresolved' ? 'reminder' : proposal.proposedKind
  return { ...item, kind, confidence: proposal.confidence, status: 'review',
    interpretation: { summary: proposal.summary, rationale: proposal.rationale,
      suggestedKind: kind, suggestedDate: proposal.suggestedDate, method: proposal.method } }
}
