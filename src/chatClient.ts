export interface ChatMessage { role: 'user' | 'assistant'; content: string }
export interface ChatIdentity { userId: string; token: string }

export function chatRequestMessages(messages: readonly ChatMessage[], prompt: string): ChatMessage[] {
  const text = prompt.trim()
  if (!text || text.length > 4000) throw Error('Write a message of up to 4,000 characters.')
  let history = messages.slice(-20)
  while (history.length && history[0].role !== 'user') history = history.slice(1)
  const bytes = () => new TextEncoder().encode(JSON.stringify({ messages: [...history, { role: 'user', content: text }] })).byteLength
  while (history.length && (history.reduce((n, m) => n + m.content.length, text.length) > 28_000 || bytes() > 47_000)) history = history.slice(2)
  return [...history, { role: 'user', content: text }]
}

export async function sendChat(messages: ChatMessage[], expectedUserId: string, identity: () => Promise<ChatIdentity | undefined>, signal: AbortSignal, fetcher: typeof fetch = fetch) {
  let cancel: () => void = () => undefined
  const cancelled = new Promise<never>((_, reject) => {
    cancel = () => reject(Error('Request cancelled.'))
    if (signal.aborted) cancel()
    else signal.addEventListener('abort', cancel, { once: true })
  })
  try { return await Promise.race([run(), cancelled]) }
  finally { signal.removeEventListener('abort', cancel) }
  async function run() {
  const account = await identity()
  if (signal.aborted) throw Error('Request cancelled.')
  if (!account || account.userId !== expectedUserId) throw Error('Sign in again before sending this message.')
  const response = await fetcher('/api/chat', { method: 'POST', signal, headers: { 'content-type': 'application/json', authorization: `Bearer ${account.token}` }, body: JSON.stringify({ messages }) })
  if (response.status === 402) throw Error('The monthly AI budget is used or reserved by pending replies. Your message is still here.')
  if (!response.ok) throw Error(response.status === 401 || response.status === 403 ? 'Your session expired. Sign in again.' : response.status === 429 ? 'AI is busy with your requests. Please try again shortly.' : response.status === 503 ? 'AI chat is unavailable on this deployment. Your message is still here.' : response.status === 504 ? 'The reply took too long. Please try again.' : 'The reply could not be loaded. Please try again.')
  const result = await response.json()
  if (!result || typeof result.text !== 'string' || !result.text.trim() || result.text.length > 6000) throw Error('The AI returned an empty or invalid reply. Please try again.')
  return { text: result.text, truncated: result.truncated === true }
  }
}
