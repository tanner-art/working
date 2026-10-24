/** Shared, server-only budget gate. Missing/ambiguous accounting never permits AI. */
declare const process: { env: Record<string, string | undefined> }
export const BUDGET_MODEL = 'anthropic/claude-haiku-4.5'
const MAX_CONTEXT = 200_000
const INPUT_MICROS = 3
const OUTPUT_MICROS = 10
export class AiBudgetError extends Error {
  constructor(public readonly status: 402 | 503, public readonly code: string) { super(code) }
}

function configuration() {
  const raw = process.env.AI_BUDGET_SUPABASE_URL
  const key = process.env.AI_BUDGET_SERVICE_ROLE_KEY
  if (!raw || !key) throw new AiBudgetError(503, 'budget_unavailable')
  const url = new URL(raw)
  if (url.protocol !== 'https:' || url.username || url.password || url.pathname !== '/' || url.search || url.hash) throw new AiBudgetError(503, 'budget_unavailable')
  return { url: url.origin, key }
}

async function rpc(name: string, body: unknown, signal: AbortSignal) {
  const { url, key } = configuration()
  const response = await fetch(`${url}/rest/v1/rpc/${name}`, {
    method: 'POST', redirect: 'error', signal, cache: 'no-store',
    headers: { apikey: key, authorization: `Bearer ${key}`, 'content-type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!response.ok) throw new AiBudgetError(503, 'budget_unavailable')
  return response.json() as Promise<unknown>
}

/** Check the exact provider, including non-token fees, before every reservation.
 * Prices are deliberately rounded UP; no prompt-token estimate is used. */
export function certifiedPrice(value: unknown): boolean {
  const data = (value as { data?: { id?: unknown; endpoints?: unknown[] } })?.data
  if (data?.id !== BUDGET_MODEL || !Array.isArray(data.endpoints)) return false
  const endpoints = data.endpoints as Record<string, unknown>[]
  const matches = endpoints.filter(e => e.provider_name === 'anthropic')
  if (matches.length !== 1) return false
  const e = matches[0], p = e.pricing as Record<string, unknown> | undefined
  if (e.context_length !== MAX_CONTEXT || !p || e.inference_regions !== undefined) return false
  const ceilings: Record<string, number> = { prompt: .000003, completion: .00001, request: 0, image: 0, image_output: 0, internal_reasoning: 0, input_cache_read: .000003, input_cache_write: .000003 }
  for (const [key, ceiling] of Object.entries(ceilings)) {
    const n = typeof p[key] === 'string' && p[key] !== '' ? Number(p[key]) : NaN
    if (!Number.isFinite(n) || n < 0 || n > ceiling) return false
  }
  // Web search is never sent; discount can only reduce cost. Unknown billing dimensions fail closed.
  return Object.keys(p).every(k => k in ceilings || k === 'web_search' || k === 'discount')
}

export function usageCharge(data: unknown, outputLimit: number): number | undefined {
  const usage = (data as { usage?: Record<string, unknown> })?.usage
  if (!usage || typeof usage !== 'object') return
  const integer = (n: unknown) => typeof n === 'number' && Number.isSafeInteger(n) && n >= 0
  if (!integer(usage.input_tokens) || !integer(usage.output_tokens)) return
  const read = usage.cache_read_input_tokens ?? 0, write = usage.cache_creation_input_tokens ?? 0
  if (!integer(read) || !integer(write)) return
  const input = Number(usage.input_tokens) + Number(read) + Number(write)
  const output = Number(usage.output_tokens)
  if (input > MAX_CONTEXT || output > outputLimit) return
  // Unknown billable dimensions retain the entire reservation, not a guessed refund.
  const allowed = new Set(['input_tokens', 'output_tokens', 'cache_read_input_tokens', 'cache_creation_input_tokens', 'cache_creation', 'service_tier'])
  if (Object.keys(usage).some(k => !allowed.has(k))) return
  if (usage.service_tier !== undefined && usage.service_tier !== 'standard') return
  return input * INPUT_MICROS + output * OUTPUT_MICROS
}

export async function budgetedMessage(token: string, payload: Record<string, unknown>, parentSignal?: AbortSignal): Promise<Response> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), 20_000)
  const abort = () => controller.abort()
  parentSignal?.addEventListener('abort', abort, { once: true })
  if (parentSignal?.aborted) controller.abort()
  try {
    configuration()
    const max = payload.max_tokens
    if (payload.model !== BUDGET_MODEL || typeof max !== 'number' || !Number.isInteger(max) || max < 1 || max > 1200) throw new AiBudgetError(503, 'budget_unavailable')
    // Callers build this object, but explicitly forbid alternate paid modalities/routing.
    if (Object.keys(payload).some(k => !['model', 'max_tokens', 'system', 'messages', 'tools', 'tool_choice'].includes(k))) throw new AiBudgetError(503, 'budget_unavailable')
    if (typeof payload.system !== 'string' || !Array.isArray(payload.messages) || payload.messages.some(m => !m || typeof m.content !== 'string' || !['user', 'assistant'].includes(m.role) || Object.keys(m).some(k => !['role', 'content'].includes(k)))) throw new AiBudgetError(503, 'budget_unavailable')
    if (payload.tools !== undefined && (!Array.isArray(payload.tools) || payload.tools.some(t => !t || t.name !== 'propose_interpretation' || Object.keys(t).some(k => !['name', 'description', 'input_schema'].includes(k))))) throw new AiBudgetError(503, 'budget_unavailable')
    const price = await fetch(`https://ai-gateway.vercel.sh/v1/models/${BUDGET_MODEL}/endpoints`, { signal: controller.signal, redirect: 'error', cache: 'no-store' })
    if (!price.ok || !certifiedPrice(await price.json())) throw new AiBudgetError(503, 'budget_price_unverified')
    if (controller.signal.aborted) throw new AiBudgetError(503, 'budget_unavailable')
    const id = crypto.randomUUID()
    const reserved = MAX_CONTEXT * INPUT_MICROS + max * OUTPUT_MICROS
    const receipt = await rpc('threadline_reserve_ai_spend', { p_id: id, p_micros: reserved }, controller.signal)
    if (receipt === 'exhausted') throw new AiBudgetError(402, 'budget_exhausted')
    if (receipt !== 'reserved' || controller.signal.aborted) throw new AiBudgetError(503, 'budget_unavailable')
    // No retries. Once reserved, crashes/timeouts/invalid responses keep the full hold.
    const response = await fetch('https://ai-gateway.vercel.sh/v1/messages', {
      method: 'POST', signal: controller.signal, redirect: 'error',
      headers: { 'content-type': 'application/json', authorization: `Bearer ${token}` },
      body: JSON.stringify({ ...payload, providerOptions: { gateway: { only: ['anthropic'] } } }),
    })
    const text = await response.text()
    if (response.ok) {
      try {
        const charge = usageCharge(JSON.parse(text), max)
        if (charge !== undefined) await rpc('threadline_settle_ai_spend', { p_id: id, p_micros: charge }, controller.signal)
      } catch { /* Uncertain settlement retains the hold. Never release speculatively. */ }
    }
    return new Response(text, { status: response.status, headers: { 'content-type': 'application/json' } })
  } catch (error) {
    if (error instanceof AiBudgetError) throw error
    throw new AiBudgetError(503, 'budget_unavailable')
  } finally { clearTimeout(timer); parentSignal?.removeEventListener('abort', abort) }
}
