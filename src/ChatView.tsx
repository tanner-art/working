import { useEffect, useRef, useState, useSyncExternalStore } from 'react'
import type { WorkspaceSurfaceProps } from './appSurfaceRegistry'
import { auth, supabase } from './auth'
import { chatRequestMessages, sendChat, type ChatMessage } from './chatClient'
import './brainChat.css'

type ChatProps = Pick<WorkspaceSurfaceProps, 'navigate' | 'registerExitGuard'>
export function ChatView({ navigate, registerExitGuard }: ChatProps) {
  const account = useSyncExternalStore(auth.subscribe, auth.getState, auth.getState)
  const id = account.status === 'signed-in' ? account.session.user.id : ''
  // Identity-keyed remount prevents one account's transcript appearing after a session change.
  return <Conversation key={id || 'signed-out'} userId={id} navigate={navigate} registerExitGuard={registerExitGuard} />
}

function Conversation({ userId, navigate, registerExitGuard }: { userId: string } & ChatProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [truncated, setTruncated] = useState(false)
  const request = useRef<AbortController | null>(null)
  const end = useRef<HTMLDivElement>(null)
  const dirty = useRef(false)
  dirty.current = !!(messages.length || draft.trim() || busy)
  useEffect(() => registerExitGuard?.(() => !dirty.current || window.confirm('Leave this chat? This conversation is not saved.')), [registerExitGuard])
  useEffect(() => {
    const beforeUnload = (event: BeforeUnloadEvent) => { if (dirty.current) { event.preventDefault(); event.returnValue = '' } }
    window.addEventListener('beforeunload', beforeUnload)
    return () => window.removeEventListener('beforeunload', beforeUnload)
  }, [])
  useEffect(() => () => { request.current?.abort(); request.current = null }, [])
  useEffect(() => { end.current?.scrollIntoView({ block: 'nearest' }) }, [messages, busy])
  const send = async () => {
    if (request.current || !userId || !draft.trim()) return
    let next: ChatMessage[]
    try { next = chatRequestMessages(messages, draft) } catch (e) { setError((e as Error).message); return }
    const controller = new AbortController()
    request.current = controller
    setBusy(true); setError(''); setTruncated(false)
    const timeout = setTimeout(() => controller.abort(), 30_000)
    try {
      const reply = await sendChat(next, userId, async () => {
        const current = auth.getState()
        if (current.status !== 'signed-in' || current.session.user.id !== userId || !supabase) return
        const { data, error } = await supabase.auth.getSession()
        if (error || !data.session) return
        return { userId: data.session.user.id, token: data.session.access_token }
      }, controller.signal)
      const current = auth.getState()
      if (request.current !== controller || current.status !== 'signed-in' || current.session.user.id !== userId) return
      setMessages([...messages, next[next.length - 1], { role: 'assistant', content: reply.text }]); setDraft(''); setTruncated(reply.truncated)
    } catch (e) {
      if (request.current === controller) setError(controller.signal.aborted ? 'Reply stopped. Your message is still here.' : (e instanceof Error ? e.message : 'Chat is unavailable. Try again.'))
    } finally {
      clearTimeout(timeout)
      if (request.current === controller) { request.current = null; setBusy(false) }
    }
  }
  const close = () => {
    const result = navigate({ type: 'close-surface' })
    if (!result.ok) setError(result.message)
  }
  return <main className="page chat-page" data-swipe-ignore aria-labelledby="chat-title">
    <header className="page-header"><div><p className="eyebrow">A little room to think</p><h1 id="chat-title">Chat</h1></div><button className="secondary" onClick={close}>Close</button></header>
    <p className="chat-privacy">Chat with Threadline AI. Only messages you send here go to the AI provider. Your saved thoughts aren’t shared automatically. This conversation stays on this page and isn’t saved.</p>
    {!userId && <p role="status" className="chat-signin">Sign in through Home → Settings to chat with AI.</p>}
    <section className="chat-transcript" aria-label="Conversation" aria-busy={busy}>
      {!messages.length && <div className="chat-welcome"><span aria-hidden="true">⊹</span><h2>What’s on your mind?</h2><p>Untangle an idea. Think through a decision. Find a place to start.</p></div>}
      {messages.map((message, i) => <article key={i} className={`chat-message ${message.role}`}><strong>{message.role === 'user' ? 'You' : 'Threadline'}</strong><p>{message.content}</p></article>)}
      {busy && <p role="status">Thinking…</p>}{truncated && <p role="status">The reply reached its length limit. Ask the AI to continue.</p>}<div ref={end} />
    </section>
    {error && <p role="alert" className="chat-error">{error}</p>}
    <form className="chat-composer" onSubmit={e => { e.preventDefault(); void send() }}><label htmlFor="chat-message">Message</label><textarea id="chat-message" placeholder="Ask, explore, think aloud…" rows={3} maxLength={4000} value={draft} disabled={busy} onChange={e => setDraft(e.target.value)} onKeyDown={e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey) && !e.nativeEvent.isComposing) { e.preventDefault(); void send() } }} /><div><small>AI can be wrong. It cannot edit or schedule anything.</small>{busy ? <button type="button" className="secondary" onClick={() => request.current?.abort()}>Stop</button> : <button className="primary" disabled={!userId || !draft.trim()}>Send</button>}</div></form>
  </main>
}
