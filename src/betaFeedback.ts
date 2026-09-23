/** The deliberately small, local-only payload used by the friends-and-family test. */

export const BETA_FEEDBACK_CATEGORIES = ['bug', 'usability', 'performance', 'feature-request', 'other'] as const
export type BetaFeedbackCategory = typeof BETA_FEEDBACK_CATEGORIES[number]

export const BETA_FEEDBACK_SEVERITIES = ['low', 'medium', 'high', 'critical'] as const
export type BetaFeedbackSeverity = typeof BETA_FEEDBACK_SEVERITIES[number]

export const BETA_FEEDBACK_LIMITS = {
  description: { min: 1, max: 500 },
  reproductionSteps: { max: 2_000 },
} as const

export type DiagnosticsSnapshot = Record<string, unknown>

export interface BetaFeedbackInput {
  category: BetaFeedbackCategory
  severity: BetaFeedbackSeverity
  description: string
  reproductionSteps?: string
  diagnosticsSnapshot?: DiagnosticsSnapshot
  /** Diagnostics are included only when this is explicitly true. */
  includeDiagnostics?: boolean
  createdAt: string
}

export interface BetaFeedback {
  category: BetaFeedbackCategory
  severity: BetaFeedbackSeverity
  description: string
  reproductionSteps?: string
  diagnosticsSnapshot?: DiagnosticsSnapshot
  createdAt: string
}

const inputKeys = new Set(['category', 'severity', 'description', 'reproductionSteps', 'diagnosticsSnapshot', 'includeDiagnostics', 'createdAt'])
const sensitiveKey = /(?:capture|canvas|email|account|credential|password|secret|token|device(?:id|identifier)?|useragent|serial)/i

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value)

function assertSafe(value: unknown, path: string): void {
  if (Array.isArray(value)) {
    value.forEach((item, index) => assertSafe(item, `${path}[${index}]`))
    return
  }
  if (!isRecord(value)) return
  for (const [key, child] of Object.entries(value)) {
    if (sensitiveKey.test(key)) throw new Error(`Sensitive field is not allowed: ${path}.${key}`)
    assertSafe(child, `${path}.${key}`)
  }
}

function cloneAndSort(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(cloneAndSort)
  if (!isRecord(value)) return value
  return Object.fromEntries(Object.keys(value).sort().map(key => [key, cloneAndSort(value[key])]))
}

function assertStringLength(value: string, field: string, min: number, max: number): void {
  if (value.length < min || value.length > max) throw new Error(`${field} must be between ${min} and ${max} characters.`)
}

/** Validate and create a detached feedback record. This function never reads globals or performs I/O. */
export function createBetaFeedback(input: BetaFeedbackInput): BetaFeedback {
  if (!isRecord(input)) throw new Error('Feedback must be an object.')
  assertSafe(input, 'feedback')
  for (const key of Object.keys(input)) if (!inputKeys.has(key)) throw new Error(`Unknown feedback field: ${key}`)
  if (!BETA_FEEDBACK_CATEGORIES.includes(input.category)) throw new Error(`Invalid feedback category: ${String(input.category)}`)
  if (!BETA_FEEDBACK_SEVERITIES.includes(input.severity)) throw new Error(`Invalid feedback severity: ${String(input.severity)}`)
  if (typeof input.description !== 'string') throw new Error('description must be a string.')
  assertStringLength(input.description, 'description', BETA_FEEDBACK_LIMITS.description.min, BETA_FEEDBACK_LIMITS.description.max)
  if (input.reproductionSteps !== undefined) {
    if (typeof input.reproductionSteps !== 'string') throw new Error('reproductionSteps must be a string.')
    assertStringLength(input.reproductionSteps, 'reproductionSteps', 0, BETA_FEEDBACK_LIMITS.reproductionSteps.max)
  }
  if (input.diagnosticsSnapshot !== undefined && !isRecord(input.diagnosticsSnapshot)) throw new Error('diagnosticsSnapshot must be an object.')
  if (typeof input.createdAt !== 'string' || !Number.isFinite(Date.parse(input.createdAt))) throw new Error('createdAt must be a valid date string.')
  if (input.includeDiagnostics !== undefined && typeof input.includeDiagnostics !== 'boolean') throw new Error('includeDiagnostics must be a boolean.')

  const feedback: BetaFeedback = {
    category: input.category,
    severity: input.severity,
    description: input.description,
    ...(input.reproductionSteps === undefined ? {} : { reproductionSteps: input.reproductionSteps }),
    createdAt: input.createdAt,
  }
  if (input.includeDiagnostics === true && input.diagnosticsSnapshot !== undefined) {
    feedback.diagnosticsSnapshot = cloneAndSort(input.diagnosticsSnapshot) as DiagnosticsSnapshot
  }
  return feedback
}

export const validateBetaFeedback = createBetaFeedback

/** Stable JSON export. It is serialization only: no network or browser access occurs. */
export function exportBetaFeedback(feedback: BetaFeedbackInput | BetaFeedback): string {
  const validated = createBetaFeedback({
    ...feedback,
    // A diagnostics field here can only be present on a previously-created,
    // already opted-in record; raw input must use createBetaFeedback first.
    includeDiagnostics: 'diagnosticsSnapshot' in feedback ? true : (feedback as BetaFeedbackInput).includeDiagnostics,
  } as BetaFeedbackInput)
  return JSON.stringify(cloneAndSort(validated))
}

export const exportBetaFeedbackJson = exportBetaFeedback
