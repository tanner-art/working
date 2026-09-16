// Vercel Edge Function backing src/aiInterpretation.ts's provider client. This file is
// deployed independently of the Vite SPA bundle (see docs/AI_INTERPRETATION.md), so it
// intentionally does not import from src/: src/ modules read Vite's import.meta.env at
// load time, which is not defined in this runtime and would crash the function on cold
// start. Validation logic below mirrors src/aiInterpretation.ts by design, not by import.
export const config = { runtime: 'edge' }

declare const process: { env: Record<string, string | undefined> }

type CaptureSource = 'text' | 'voice' | 'canvas'
interface CaptureInput {
  id: string
  source: CaptureSource
  createdAt: string
  originalContent: string
  context?: string
  evidence: 'text-only'
}

const ALLOWED_SOURCES = new Set(['text', 'voice', 'canvas'])
const RESOLVED_KINDS = new Set(['idea', 'project', 'commitment', 'person', 'reference', 'objective'])
const MAX_CONTENT_LENGTH = 4000
const PROVIDER_TIMEOUT_MS = 15_000
const DEFAULT_MODEL = 'claude-sonnet-5'

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } })
}

function validateCapture(body: unknown): CaptureInput | null {
  if (!body || typeof body !== 'object') return null
  const capture = (body as Record<string, unknown>).capture
  if (!capture || typeof capture !== 'object') return null
  const c = capture as Record<string, unknown>
  if (typeof c.id !== 'string' || !c.id.trim()) return null
  if (typeof c.source !== 'string' || !ALLOWED_SOURCES.has(c.source)) return null
  if (typeof c.createdAt !== 'string' || Number.isNaN(Date.parse(c.createdAt))) return null
  if (typeof c.originalContent !== 'string' || !c.originalContent.trim() || c.originalContent.length > MAX_CONTENT_LENGTH) return null
  if (c.context !== undefined && typeof c.context !== 'string') return null
  if (c.evidence !== 'text-only') return null
  return {
    id: c.id, source: c.source as CaptureSource, createdAt: c.createdAt,
    originalContent: c.originalContent, context: c.context as string | undefined, evidence: 'text-only',
  }
}

const SYSTEM_PROMPT = `You interpret one short captured thought for Threadline, a personal
thought-to-execution app. Classify it and propose meaning; you never confirm, schedule, or
execute anything yourself — a human always reviews your proposal before it becomes real work.
Call the propose_interpretation tool exactly once. Rules:
- "action" is only for a clear, concrete next step the user could actually do.
- "unresolved" is for anything implying timing, a reminder, a meeting, or a deadline where the
  exact commitment is not yet confirmed. Never invent a specific date; only note that timing
  needs confirmation.
- "commitment" is only for an already-explicit promise or obligation, not a mere possibility.
- Use "idea", "project", "person", "reference", or "objective" for other content.
- If the text is uncertain, conditional, a question, or expresses hesitation (e.g. "maybe",
  "might", "could", "not sure", "cancel"), set confidence to 0.64 or lower.
- confidence is a number between 0 and 1. Never return confidence above 0.95.
- Keep rationale to one or two short sentences and summary under 120 characters.`

const PROPOSE_INTERPRETATION_TOOL = {
  name: 'propose_interpretation',
  description: 'Propose a reviewable interpretation of a single captured thought. Never confirms or schedules anything.',
  input_schema: {
    type: 'object',
    additionalProperties: false,
    required: ['summary', 'rationale', 'confidence', 'proposedKind'],
    properties: {
      summary: { type: 'string', maxLength: 200 },
      rationale: { type: 'string', maxLength: 400 },
      confidence: { type: 'number', minimum: 0, maximum: 1 },
      proposedKind: { type: 'string', enum: ['idea', 'action', 'project', 'commitment', 'person', 'reference', 'objective', 'unresolved'] },
      suggestedDate: { type: 'string' },
    },
  },
}

function buildUserPrompt(capture: CaptureInput): string {
  return [
    `Captured thought (verbatim, do not alter or continue it): """${capture.originalContent}"""`,
    `Source: ${capture.source}`,
    `Context (if any): ${capture.context?.trim() || 'none'}`,
  ].join('\n')
}

/** Forces reviewState to "review" and derives proposedAction/proposedReminder from the
 * capture itself, never from the model's free-form fields, so the endpoint structurally
 * cannot return anything that bypasses D-009 review/confirmation. */
function coerceProposal(capture: CaptureInput, input: Record<string, unknown>) {
  const summary = typeof input.summary === 'string' && input.summary.trim()
    ? input.summary.trim().slice(0, 200)
    : capture.originalContent.slice(0, 84)
  const rationale = typeof input.rationale === 'string' && input.rationale.trim()
    ? input.rationale.trim().slice(0, 400)
    : 'The provider did not include a rationale.'
  const confidence = typeof input.confidence === 'number' && Number.isFinite(input.confidence)
    ? Math.min(Math.max(input.confidence, 0), 1)
    : 0
  const suggestedDate = typeof input.suggestedDate === 'string' && input.suggestedDate.trim() ? input.suggestedDate.trim() : undefined
  const base = { summary, rationale, confidence, reviewState: 'review' as const, suggestedDate }
  const kind = typeof input.proposedKind === 'string' ? input.proposedKind : ''
  if (kind === 'unresolved') {
    return { ...base, proposedKind: 'unresolved', proposedReminder: {
      captureIds: [capture.id], deliveryState: 'needs-review',
      trigger: { kind: 'unresolved', wording: capture.originalContent, legacyDate: suggestedDate },
    } }
  }
  if (kind === 'action') return { ...base, proposedKind: 'action', proposedAction: { summary } }
  if (RESOLVED_KINDS.has(kind)) return { ...base, proposedKind: kind }
  throw new Error(`Provider returned an unsupported proposedKind: ${kind || 'missing'}`)
}

async function requestProviderInterpretation(capture: CaptureInput, apiKey: string, model: string) {
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), PROVIDER_TIMEOUT_MS)
  let response: Response
  try {
    response = await fetch('https://api.anthropic.com/v1/messages', {
      method: 'POST',
      headers: { 'content-type': 'application/json', 'x-api-key': apiKey, 'anthropic-version': '2023-06-01' },
      body: JSON.stringify({
        model,
        max_tokens: 400,
        system: SYSTEM_PROMPT,
        messages: [{ role: 'user', content: buildUserPrompt(capture) }],
        tools: [PROPOSE_INTERPRETATION_TOOL],
        tool_choice: { type: 'tool', name: 'propose_interpretation' },
      }),
      signal: controller.signal,
    })
  } finally { clearTimeout(timeout) }
  if (!response.ok) throw new Error(`Provider request failed with status ${response.status}.`)
  const data = await response.json() as { content?: Array<{ type: string; input?: unknown }> }
  const toolUse = Array.isArray(data.content) ? data.content.find(block => block.type === 'tool_use') : undefined
  if (!toolUse || !toolUse.input || typeof toolUse.input !== 'object') throw new Error('Provider response did not include structured output.')
  return coerceProposal(capture, toolUse.input as Record<string, unknown>)
}

export default async function handler(request: Request): Promise<Response> {
  if (request.method !== 'POST') return json(405, { error: 'method_not_allowed' })
  let body: unknown
  try { body = await request.json() } catch { return json(400, { error: 'invalid_json' }) }
  const capture = validateCapture(body)
  if (!capture) return json(400, { error: 'invalid_capture' })

  // Server-only secret. Must never carry a VITE_ prefix, which Vite would expose to the
  // client bundle; see docs/AI_INTERPRETATION.md for the deployment contract.
  const apiKey = process.env.AI_INTERPRETATION_API_KEY
  if (!apiKey) return json(503, { error: 'not_configured', message: 'AI_INTERPRETATION_API_KEY is not set.' })
  const model = process.env.AI_INTERPRETATION_MODEL?.trim() || DEFAULT_MODEL

  try {
    const proposal = await requestProviderInterpretation(capture, apiKey, model)
    return json(200, proposal)
  } catch (error) {
    return json(502, { error: 'provider_error', message: error instanceof Error ? error.message : 'Unknown provider error.' })
  }
}
