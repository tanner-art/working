import type { CaptureRecord, Interpretation, ReminderInstruction } from './domain'
import { deterministicInterpretationService } from './interpreter'

/** Meaning only: persistence owns identity, versions, history and acceptance.
 * This slice supports one proposal per capture. Providers never confirm work.
 * An action uses the proposal summary. Unresolved reminders retain this capture's
 * wording/reference and the same suggestedDate; the compatibility writer cannot
 * yet represent separate action summaries or independently rewritten triggers.
 * Unresolved reminder targets stay in Review until reminder semantics are decided.
 */
export type InterpretationProposal = Pick<Interpretation,
  'summary' | 'rationale' | 'confidence'> & {
  reviewState: 'review'
  /** Original timing wording is evidence, never a scheduled date. */
  suggestedDate?: string
} & (
  | { proposedKind: 'unresolved'; proposedReminder: Omit<ReminderInstruction, 'id'>; proposedAction?: never }
  | { proposedKind: 'action'; proposedAction: NonNullable<Interpretation['proposedAction']>; proposedReminder?: never }
  | { proposedKind: Exclude<Interpretation['proposedKind'], 'unresolved' | 'action'>; proposedAction?: never; proposedReminder?: never }
)

export interface InterpretationService {
  interpret(capture: CaptureRecord): Promise<InterpretationProposal>
}

/** Composition point: replace this implementation without changing consumers. */
export const interpretationService: InterpretationService = deterministicInterpretationService
