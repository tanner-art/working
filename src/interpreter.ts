import type { LegacyInterpretation, ObjectKind } from './domain'

const lower = (value: string) => value.toLowerCase()
export function interpret(content: string): { kind: ObjectKind; confidence: number; interpretation: LegacyInterpretation } {
  const value = lower(content)
  const date = /\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday|today|tomorrow|\d{1,2}\/\d{1,2})\b/.test(value)
  let kind: ObjectKind = 'idea'; let confidence = .66; let rationale = 'This reads like a possibility to explore.'
  if (/\b(remind|remember|follow up|call|email|buy|give|send|finish|prepare)\b/.test(value)) { kind = 'action'; confidence = .86; rationale = 'The language describes a concrete next action.' }
  if (/\b(meeting|appointment|scheduled|call at|deadline)\b/.test(value) || (date && /\b(call|meet|convo)\b/.test(value))) { kind = 'reminder'; confidence = .74; rationale = 'A timing cue is present, but the exact commitment needs confirmation.' }
  if (/\b(build|launch|create|redesign|plan)\b/.test(value) && value.split(' ').length > 4) { kind = 'project'; confidence = .71; rationale = 'This suggests a multi-step outcome; confirm whether it is a project.' }
  return { kind, confidence, interpretation: { summary: content.length > 84 ? `${content.slice(0, 81)}…` : content, suggestedKind: kind, rationale, suggestedDate: date ? 'Needs a date' : undefined } }
}
