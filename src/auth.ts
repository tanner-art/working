import { createClient, type Session } from '@supabase/supabase-js'

/** Provider-neutral account boundary. Never reads or writes application storage. */
export interface AuthSession { user: { id: string; email?: string } }
export interface AuthClient {
  getSession(): Promise<AuthSession | null>
  sendEmailLink(email: string): Promise<void>
  signOut(): Promise<void>
  onSessionChange(listener: (session: AuthSession | null) => void): () => void
}
export type AuthConfig = { status: 'configured'; url: string; anonKey: string } | { status: 'unconfigured'; message: string }
export function readAuthConfig(env: { VITE_SUPABASE_URL?: string; VITE_SUPABASE_ANON_KEY?: string }): AuthConfig {
  const url = env.VITE_SUPABASE_URL?.trim()
  const anonKey = env.VITE_SUPABASE_ANON_KEY?.trim()
  if (!url || !anonKey) return { status: 'unconfigured', message: 'Auth is not configured. The deployment needs VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY.' }
  try {
    const parsed = new URL(url)
    if ((parsed.protocol !== 'https:' && !(parsed.protocol === 'http:' && ['localhost', '127.0.0.1'].includes(parsed.hostname))) || parsed.username || parsed.password || parsed.search || parsed.hash) throw Error()
  } catch { return { status: 'unconfigured', message: 'Auth is not configured: the Supabase URL is invalid.' } }
  return { status: 'configured', url, anonKey }
}
export type AuthState =
  | { status: 'unconfigured'; message: string }
  | { status: 'loading' }
  | { status: 'signed-out'; message?: string }
  | { status: 'signed-in'; session: AuthSession }
  | { status: 'error'; message: string }

function authSession(session: Session | null): AuthSession | null {
  if (!session) return null
  return { user: { id: session.user.id, email: session.user.email ?? undefined } }
}
export function createSupabaseAuthClient(config: Extract<AuthConfig, { status: 'configured' }>, redirectTo = window.location.origin): AuthClient {
  const supabase = createClient(config.url, config.anonKey, { auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: true } })
  return {
    async getSession() {
      const { data, error } = await supabase.auth.getSession()
      if (error) throw error
      return authSession(data.session)
    },
    async sendEmailLink(email: string) {
      const { error } = await supabase.auth.signInWithOtp({ email, options: { emailRedirectTo: redirectTo } })
      if (error) throw error
    },
    async signOut() {
      const { error } = await supabase.auth.signOut()
      if (error) throw error
    },
    onSessionChange(listener: (session: AuthSession | null) => void) {
      const { data: { subscription } } = supabase.auth.onAuthStateChange((_event, session) => listener(authSession(session)))
      return () => subscription.unsubscribe()
    },
  }
}
export function sessionState(session: AuthSession | null): AuthState {
  if (session === null) return { status: 'signed-out' }
  if (!session.user?.id?.trim()) return { status: 'error', message: 'The account session is invalid. Retry checking your account.' }
  return { status: 'signed-in', session }
}
export function accountLabel(state: AuthState): string {
  switch (state.status) {
    case 'unconfigured': return 'Auth unconfigured'
    case 'loading': return 'Checking account…'
    case 'signed-out': return 'Signed out'
    case 'signed-in': return `Signed in as ${state.session.user.email || state.session.user.id}`
    case 'error': return 'Account error — session could not be confirmed'
  }
}
/** Honest data-ownership status for nontechnical Settings copy: no state currently
 *  implies cloud storage, since that is separately scoped (D-011/TASK-034). */
export function dataOwnershipLabel(state: AuthState): string {
  const base = 'Everything lives in this browser on this device — there is no cloud sync yet.'
  return state.status === 'signed-in' ? `Signed in, but still local-only. ${base}` : `Local-only. ${base}`
}
export function createAuthBoundary(config: AuthConfig, client?: AuthClient) {
  let state: AuthState = config.status === 'unconfigured' ? config : client ? { status: 'loading' } : {
    status: 'unconfigured', message: 'Login is unavailable in this build. Supabase provider setup is still required.',
  }
  const listeners = new Set<() => void>()
  let revision = 0
  let pending = false
  const publish = (next: AuthState) => { state = next; listeners.forEach(listener => listener()) }
  return {
    getState: () => state,
    subscribe(listener: () => void) { listeners.add(listener); return () => { listeners.delete(listener) } },
    connect() {
      if (!client || config.status !== 'configured') return () => {}
      let active = true
      const unsubscribe = client.onSessionChange(session => { if (active) { revision++; publish(sessionState(session)) } })
      const current = ++revision
      publish({ status: 'loading' })
      void client.getSession().then(session => { if (active && current === revision) publish(sessionState(session)) }, () => {
        if (active && current === revision) publish({ status: 'error', message: 'Unable to check your account. Check your connection and retry.' })
      })
      return () => { active = false; revision++; unsubscribe() }
    },
    async act(action: 'login' | 'logout', email = '') {
      if (!client || config.status !== 'configured' || pending || (action === 'login' ? state.status !== 'signed-out' : state.status !== 'signed-in')) return
      if (action === 'login' && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())) {
        publish({ status: 'signed-out', message: 'Enter a valid email address.' }); return
      }
      pending = true
      const current = ++revision
      publish({ status: 'loading' })
      try {
        if (action === 'login') await client.sendEmailLink(email.trim())
        else await client.signOut()
        if (current === revision) publish({ status: 'signed-out', message: action === 'login' ? 'Check your email for a sign-in link. You are not signed in yet.' : undefined })
      } catch {
        if (current === revision) publish({ status: 'error', message: 'Account action failed. Check your connection and retry checking your account.' })
      } finally { pending = false }
    },
  }
}
const authConfig = readAuthConfig({
  VITE_SUPABASE_URL: import.meta.env.VITE_SUPABASE_URL,
  VITE_SUPABASE_ANON_KEY: import.meta.env.VITE_SUPABASE_ANON_KEY,
})
export const auth = createAuthBoundary(authConfig, authConfig.status === 'configured' ? createSupabaseAuthClient(authConfig) : undefined)
