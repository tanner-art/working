import { afterEach, describe, expect, it, vi } from 'vitest'
import { unstable_checkRateLimit as checkRateLimit } from '@vercel/firewall'
import { checkInterpretationRateLimit } from './interpretRateLimit'

vi.mock('@vercel/firewall', () => ({ unstable_checkRateLimit: vi.fn() }))
const checkRateLimitMock = vi.mocked(checkRateLimit)
const request = new Request('https://threadline.test/api/interpret', { method: 'POST' })

afterEach(() => { checkRateLimitMock.mockReset() })

describe('checkInterpretationRateLimit', () => {
  it('uses the verified account id as the firewall key', async () => {
    checkRateLimitMock.mockResolvedValue({ rateLimited: false })
    await expect(checkInterpretationRateLimit(request, 'account-1')).resolves.toEqual({ ok: true, rateLimited: false })
    expect(checkRateLimitMock).toHaveBeenCalledWith('threadline-ai-interpret', { request, rateLimitKey: 'account-1' })
  })

  it('reports a matched limit', async () => {
    checkRateLimitMock.mockResolvedValue({ rateLimited: true })
    await expect(checkInterpretationRateLimit(request, 'account-1')).resolves.toEqual({ ok: true, rateLimited: true })
  })

  it('fails closed when the firewall rule is missing, blocked, or unavailable', async () => {
    checkRateLimitMock.mockResolvedValueOnce({ rateLimited: false, error: 'not-found' })
    await expect(checkInterpretationRateLimit(request, 'account-1')).resolves.toEqual({ ok: false })
    checkRateLimitMock.mockResolvedValueOnce({ rateLimited: true, error: 'blocked' })
    await expect(checkInterpretationRateLimit(request, 'account-1')).resolves.toEqual({ ok: false })
    checkRateLimitMock.mockRejectedValueOnce(new Error('unavailable'))
    await expect(checkInterpretationRateLimit(request, 'account-1')).resolves.toEqual({ ok: false })
  })
})
