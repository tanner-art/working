import { unstable_checkRateLimit as checkRateLimit } from '@vercel/firewall'

export type InterpretationRateLimit =
  | { ok: true; rateLimited: boolean }
  | { ok: false }

/**
 * Checks the matching Vercel Firewall rule using the verified account id as the key.
 * A missing or blocked rule fails closed so an AI deployment cannot silently become
 * unmetered if its firewall configuration drifts.
 */
export async function checkInterpretationRateLimit(request: Request, userId: string): Promise<InterpretationRateLimit> {
  try {
    const result = await checkRateLimit('threadline-ai-interpret', { request, rateLimitKey: userId })
    if (result.error) return { ok: false }
    return { ok: true, rateLimited: result.rateLimited }
  } catch { return { ok: false } }
}
