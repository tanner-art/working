import { describe, expect, it, vi } from 'vitest'
import { accountLabel, createAuthBoundary, readAuthConfig, sessionState, type AuthClient, type AuthSession } from './auth'
const config = readAuthConfig({ VITE_SUPABASE_URL: 'https://example.supabase.co', VITE_SUPABASE_ANON_KEY: 'public-key' })
const session = { user: { id: 'user-1', email: 'person@example.com' } }
function provider() {
  let listener: (session: AuthSession | null) => void = () => {}
  const unsubscribe = vi.fn()
  const client: AuthClient = {
    getSession: vi.fn(async () => null), sendEmailLink: vi.fn(async () => {}), signOut: vi.fn(async () => {}),
    onSessionChange: vi.fn(callback => { listener = callback; return unsubscribe }),
  }
  return { client, unsubscribe, emit: (value: AuthSession | null) => listener(value) }
}
const flush = async () => { await Promise.resolve(); await Promise.resolve() }
describe('auth configuration and presentation', () => {
  it.each([{}, { VITE_SUPABASE_URL: 'https://example.com' }, { VITE_SUPABASE_URL: 'javascript:bad', VITE_SUPABASE_ANON_KEY: 'key' }, { VITE_SUPABASE_URL: 'http://example.com', VITE_SUPABASE_ANON_KEY: 'key' }])('fails closed for missing or invalid configuration', env => {
    expect(readAuthConfig(env).status).toBe('unconfigured')
  })
  it('accepts configured HTTPS and local development URLs', () => {
    expect(config.status).toBe('configured')
    expect(readAuthConfig({ VITE_SUPABASE_URL: 'http://localhost:54321', VITE_SUPABASE_ANON_KEY: 'key' }).status).toBe('configured')
  })
  it('does not pretend env setup installs a provider', async () => {
    const auth = createAuthBoundary(config)
    expect(auth.getState()).toMatchObject({ status: 'unconfigured', message: expect.stringContaining('SDK') })
    await auth.act('login', 'person@example.com')
    expect(auth.getState().status).toBe('unconfigured')
  })
  it('labels actual session states without claiming synchronization', () => {
    expect(accountLabel(sessionState(null))).toBe('Signed out')
    expect(accountLabel(sessionState(session))).toBe('Signed in as person@example.com')
    expect(sessionState({ user: { id: '' } }).status).toBe('error')
    expect(accountLabel({ status: 'loading' })).toBe('Checking account…')
    expect(accountLabel({ status: 'error', message: 'failed' })).toContain('could not be confirmed')
  })
})
describe('guarded account actions', () => {
  it('never calls the provider without configuration or during session loading', async () => {
    const { client } = provider()
    const auth = createAuthBoundary(readAuthConfig({}), client)
    auth.connect(); await auth.act('login', 'person@example.com'); await auth.act('logout')
    expect(client.getSession).not.toHaveBeenCalled()
    expect(client.sendEmailLink).not.toHaveBeenCalled()
    const loading = createAuthBoundary(config, client)
    await loading.act('login', 'person@example.com')
    expect(client.sendEmailLink).not.toHaveBeenCalled()
  })
  it('validates email, prevents duplicates and requires a provider session before logout', async () => {
    const { client, emit } = provider()
    const auth = createAuthBoundary(config, client)
    const disconnect = auth.connect(); await flush()
    await auth.act('logout'); expect(client.signOut).not.toHaveBeenCalled()
    await auth.act('login', 'bad'); expect(client.sendEmailLink).not.toHaveBeenCalled()
    const first = auth.act('login', ' person@example.com ')
    await auth.act('login', 'person@example.com'); await first
    expect(client.sendEmailLink).toHaveBeenCalledExactlyOnceWith('person@example.com')
    expect(auth.getState()).toMatchObject({ status: 'signed-out', message: expect.stringContaining('not signed in yet') })
    emit(session); expect(auth.getState()).toEqual(sessionState(session))
    await auth.act('logout'); expect(client.signOut).toHaveBeenCalledOnce()
    expect(auth.getState().status).toBe('signed-out'); disconnect()
  })
  it('ignores stale initial results and unsubscribes on disconnect', async () => {
    const { client, emit, unsubscribe } = provider()
    let resolve!: (session: AuthSession | null) => void
    client.getSession = () => new Promise(done => { resolve = done })
    const auth = createAuthBoundary(config, client)
    const disconnect = auth.connect(); emit(session); resolve(null); await flush()
    expect(auth.getState()).toEqual(sessionState(session))
    disconnect(); emit(null)
    expect(unsubscribe).toHaveBeenCalledOnce()
    expect(auth.getState()).toEqual(sessionState(session))
  })
  it('surfaces failures without claiming logout succeeded and can recheck', async () => {
    const { client, emit } = provider()
    const auth = createAuthBoundary(config, client)
    let disconnect = auth.connect(); await flush(); emit(session)
    client.signOut = vi.fn(async () => { throw Error('private provider detail') })
    await auth.act('logout')
    expect(auth.getState()).toMatchObject({ status: 'error' })
    expect(JSON.stringify(auth.getState())).not.toContain('private provider detail')
    disconnect(); disconnect = auth.connect(); await flush()
    expect(auth.getState().status).toBe('signed-out'); disconnect()
  })
})
