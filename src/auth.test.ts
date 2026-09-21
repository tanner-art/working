import { describe, expect, it, vi } from 'vitest'
import { accountLabel, createAuthBoundary, createSupabaseAuthClient, dataOwnershipLabel, readAuthConfig, sessionState, type AuthClient, type AuthSession } from './auth'
import type { SupabaseClient } from '@supabase/supabase-js'
const config = readAuthConfig({ VITE_SUPABASE_URL: 'https://example.supabase.co', VITE_SUPABASE_ANON_KEY: 'public-key' })
const session = { user: { id: 'user-1', email: 'person@example.com' } }
function provider() {
  let listener: (session: AuthSession | null) => void = () => {}
  const unsubscribe = vi.fn()
  const client: AuthClient = {
    getSession: vi.fn(async () => null), sendEmailLink: vi.fn(async () => {}), verifyEmailCode: vi.fn(async () => session), signOut: vi.fn(async () => {}),
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
  it('does not pretend env setup alone creates a session without a provider client', async () => {
    const auth = createAuthBoundary(config)
    expect(auth.getState()).toMatchObject({ status: 'unconfigured', message: expect.stringContaining('provider setup') })
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
  it('does not claim account storage is active from identity alone', () => {
    expect(dataOwnershipLabel(sessionState(null))).toMatch(/^Local-only\./)
    expect(dataOwnershipLabel({ status: 'unconfigured', message: 'x' })).toMatch(/^Local-only\./)
    expect(dataOwnershipLabel({ status: 'loading' })).toMatch(/^Local-only\./)
    expect(dataOwnershipLabel({ status: 'error', message: 'x' })).toMatch(/^Local-only\./)
    expect(dataOwnershipLabel(sessionState(session))).toMatch(/^Signed in, but still local-only\./)
    for (const state of [sessionState(null), sessionState(session), { status: 'loading' } as const]) {
      expect(dataOwnershipLabel(state)).toContain('explicitly copy or load')
    }
  })
})
describe('guarded account actions', () => {
  it('never calls the provider without configuration or during session loading', async () => {
    const { client } = provider()
    const auth = createAuthBoundary(readAuthConfig({}), client)
    auth.connect(); await auth.act('login', 'person@example.com'); await auth.act('logout')
    expect(client.getSession).not.toHaveBeenCalled()
    expect(client.sendEmailLink).not.toHaveBeenCalled()
    expect(client.verifyEmailCode).not.toHaveBeenCalled()
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
    expect(auth.getState()).toMatchObject({ status: 'signed-out', emailCodeSent: true, message: expect.stringContaining('six-digit code') })
    emit(session); expect(auth.getState()).toEqual(sessionState(session))
    await auth.act('logout'); expect(client.signOut).toHaveBeenCalledOnce()
    expect(auth.getState().status).toBe('signed-out'); disconnect()
  })
  it('validates and verifies a six-digit email code while remaining signed out on failure', async () => {
    const { client } = provider()
    const auth = createAuthBoundary(config, client)
    const disconnect = auth.connect(); await flush()
    await auth.act('login', 'person@example.com')
    await auth.act('verify-code', 'person@example.com', '123')
    expect(client.verifyEmailCode).not.toHaveBeenCalled()
    expect(auth.getState()).toMatchObject({ status: 'signed-out', emailCodeSent: true, message: expect.stringContaining('six-digit') })

    client.verifyEmailCode = vi.fn(async () => { throw Error('private provider detail') })
    await auth.act('verify-code', 'person@example.com', '123456')
    expect(auth.getState()).toMatchObject({ status: 'signed-out', emailCodeSent: true, message: expect.stringContaining('invalid or expired') })
    expect(JSON.stringify(auth.getState())).not.toContain('private provider detail')

    client.verifyEmailCode = vi.fn(async () => session)
    await auth.act('verify-code', 'person@example.com', '654321')
    expect(client.verifyEmailCode).toHaveBeenCalledExactlyOnceWith('person@example.com', '654321')
    expect(auth.getState()).toEqual(sessionState(session))
    disconnect()
  })
  it('fails closed when the provider verifies a code without returning a session', async () => {
    const { client } = provider()
    client.verifyEmailCode = vi.fn(async () => null)
    const auth = createAuthBoundary(config, client)
    const disconnect = auth.connect(); await flush()
    await auth.act('verify-code', 'person@example.com', '123456')
    expect(auth.getState()).toMatchObject({ status: 'signed-out', emailCodeSent: true, message: expect.stringContaining('could not be verified') })
    disconnect()
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

describe('Supabase email auth adapter', () => {
  it('preserves the browser link and verifies an in-app email code', async () => {
    const signInWithOtp = vi.fn(async () => ({ error: null }))
    const verifyOtp = vi.fn(async () => ({ data: { session: { user: { id: 'user-1', email: 'person@example.com' } } }, error: null }))
    const provider = {
      auth: { signInWithOtp, verifyOtp },
    } as unknown as SupabaseClient
    const client = createSupabaseAuthClient(config as Extract<typeof config, { status: 'configured' }>, 'https://app.example.com', provider)

    await client.sendEmailLink('person@example.com')
    expect(signInWithOtp).toHaveBeenCalledExactlyOnceWith({ email: 'person@example.com', options: { emailRedirectTo: 'https://app.example.com' } })
    await expect(client.verifyEmailCode('person@example.com', '123456')).resolves.toEqual(session)
    expect(verifyOtp).toHaveBeenCalledExactlyOnceWith({ email: 'person@example.com', token: '123456', type: 'email' })
  })
})

it('reports active account storage without the local-only label', () => {
  expect(dataOwnershipLabel(sessionState(session), true)).toContain('Account storage active')
  expect(dataOwnershipLabel(sessionState(session), true)).not.toContain('still local-only')
})
