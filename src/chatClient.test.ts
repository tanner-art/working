import { describe, expect, it, vi } from 'vitest'
import { chatRequestMessages, sendChat, type ChatMessage } from './chatClient'
describe('Chat transport', () => {
  const identity = async () => ({ userId: 'a', token: 'synthetic' })
  it('keeps bounded complete pairs and rejects empty/oversize prompts', () => {
    const pairs: ChatMessage[] = Array.from({ length: 30 }, (_, i) => ({ role: i % 2 ? 'assistant' : 'user', content: 'x'.repeat(3000) }))
    const messages = chatRequestMessages(pairs, 'hello')
    expect(messages[0].role).toBe('user'); expect(messages.at(-1)?.content).toBe('hello')
    expect(messages.reduce((n, m) => n + m.content.length, 0)).toBeLessThanOrEqual(28000)
    expect(() => chatRequestMessages([], '')).toThrow(); expect(() => chatRequestMessages([], 'x'.repeat(4001))).toThrow()
  })
  it('sends only the conversation to a same-origin endpoint', async () => {
    const fetcher = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => new Response(JSON.stringify({ text: 'A reply.' })))
    expect(await sendChat([{ role: 'user', content: 'Hi' }], 'a', identity, new AbortController().signal, fetcher)).toEqual({ text: 'A reply.', truncated: false })
    expect(fetcher.mock.calls[0][0]).toBe('/api/chat')
    expect(JSON.parse((fetcher.mock.calls[0] as unknown as [string, RequestInit])[1].body as string)).toEqual({ messages: [{ role: 'user', content: 'Hi' }] })
  })
  it.each(['漢', '🌱', '\u0001'])('bounds serialized UTF-8 history for %s without breaking pairs', character => {
    const pairs: ChatMessage[] = Array.from({ length: 20 }, (_, i) => ({ role: i % 2 ? 'assistant' : 'user', content: character.repeat(2000) }))
    const messages = chatRequestMessages(pairs, 'next')
    expect(new TextEncoder().encode(JSON.stringify({ messages })).byteLength).toBeLessThanOrEqual(47000)
    expect(messages.length % 2).toBe(1)
    expect(messages.every((m, i) => m.role === (i % 2 ? 'assistant' : 'user'))).toBe(true)
    expect(messages.at(-1)?.content).toBe('next')
  })
  it('rejects an account switch before any request', async () => {
    const fetcher = vi.fn()
    await expect(sendChat([], 'b', identity, new AbortController().signal, fetcher)).rejects.toThrow('Sign in again')
    expect(fetcher).not.toHaveBeenCalled()
  })
  it('can cancel while waiting for account credentials and never sends later', async () => {
    let resolve!: (value: { userId: string; token: string }) => void
    const fetcher = vi.fn(), controller = new AbortController()
    const pending = sendChat([], 'a', () => new Promise(r => { resolve = r }), controller.signal, fetcher)
    controller.abort(); await expect(pending).rejects.toThrow('cancelled')
    resolve({ userId: 'a', token: 'test' }); await Promise.resolve(); expect(fetcher).not.toHaveBeenCalled()
  })
  it.each([401, 402, 403, 429, 502, 503, 504])('surfaces %s as a failure, never an assistant message', async status => {
    await expect(sendChat([], 'a', identity, new AbortController().signal, async () => new Response('{}', { status }))).rejects.toThrow()
  })
  it('rejects malformed provider output', async () => {
    await expect(sendChat([], 'a', identity, new AbortController().signal, async () => new Response('{"text":""}'))).rejects.toThrow('invalid')
  })
})
