import type { InterpretationService } from './interpretationService'
import type { Interpretation } from './domain'

const lower = (value: string) => value.toLowerCase()
export const deterministicInterpretationService: InterpretationService = {
  async interpret(capture) {
    const content = capture.originalContent
    const value = lower(content)
    const date = /\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday|today|tomorrow|\d{1,2}\/\d{1,2})\b/.test(value)
    let kind: Interpretation['proposedKind'] = 'idea'; let confidence = .66; let rationale = 'This reads like a possibility to explore.'
    if (/\b(remind|remember|follow up|call|email|buy|give|send|finish|prepare)\b/.test(value)) { kind = 'action'; confidence = .86; rationale = 'The language describes a concrete next action.' }
    if (/\b(meeting|appointment|scheduled|call at|deadline)\b/.test(value) || (date && /\b(call|meet|convo)\b/.test(value))) { kind = 'unresolved'; confidence = .74; rationale = 'A timing cue is present, but the exact commitment needs confirmation.' }
    if (value.split(/,|\s+\/\s+/).filter(part => part.trim().length > 2).length > 1) { kind = 'project'; confidence = .68; rationale = 'This looks like a cluster of related thoughts; review before turning it into a project.' }
    if (/\b(build|launch|create|redesign|plan)\b/.test(value) && value.split(' ').length > 4) { kind = 'project'; confidence = .71; rationale = 'This suggests a multi-step outcome; confirm whether it is a project.' }
    if (/\b(remind me|reminder|remember to)\b/.test(value)) { kind = 'unresolved'; confidence = .74; rationale = 'This asks for a reminder; confirm the timing before scheduling it.' }
    if (/\b(maybe|might|could|perhaps|consider|if|should|do not|don['’]t|not sure|cancel|cancelled|canceled)\b/.test(value) || value.includes('?')) {
      confidence = Math.min(confidence, .64)
      rationale = 'This includes uncertainty, a condition, a question, or a change of intent. Review before treating it as work to execute.'
    }
    const summary = content.length > 84 ? `${content.slice(0, 81)}…` : content
    const base = { summary, rationale, confidence, reviewState: 'review' as const, method: 'built-in' as const,
      suggestedDate: date ? 'Needs a date' : undefined }
    if (kind === 'unresolved') return { ...base, proposedKind: kind,
      proposedReminder: { captureIds: [capture.id], deliveryState: 'needs-review',
        trigger: { kind: 'unresolved', wording: content, legacyDate: base.suggestedDate } } }
    if (kind === 'action') return { ...base, proposedKind: kind, proposedAction: { summary } }
    return { ...base, proposedKind: kind }
  }
}
