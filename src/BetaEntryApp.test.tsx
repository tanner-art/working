import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { AuthState } from './auth'
import { App } from './App'
import { BetaWelcome } from './BetaWelcomeView'

const h = vi.hoisted(() => ({ index: 0, values: [] as any[], deps: [] as unknown[][], effects: [] as (() => void)[], auth: { status: 'signed-out' } as AuthState, notify: () => {}, read: vi.fn(), write: vi.fn() }))
vi.mock('react', async original => ({ ...await original<typeof import('react')>(),
  useState: (initial: any) => { const i = h.index++; if (!(i in h.values)) h.values[i] = typeof initial === 'function' ? initial() : initial; return [h.values[i], (next: any) => { h.values[i] = typeof next === 'function' ? next(h.values[i]) : next }] },
  useRef: (current: any) => { const i = h.index++; return h.values[i] ??= { current } },
  useEffect: (effect: () => void, deps: unknown[]) => { const i = h.index++; if (!h.deps[i] || deps.some((d, j) => !Object.is(d, h.deps[i][j]))) { h.deps[i] = deps; h.effects.push(effect) } },
}))
vi.mock('./auth', async original => ({ ...await original<typeof import('./auth')>(), supabase: undefined, auth: {
  getState: () => h.auth, subscribe: (listener: () => void) => { h.notify = listener; return () => {} }, connect: () => () => {},
  act: vi.fn(async () => { h.auth = { status: 'loading' }; h.notify() }),
} }))
vi.mock('./accountStorage', async original => ({ ...await original<typeof import('./accountStorage')>(), createAccountAdapter: () => ({ read: (...args: unknown[]) => h.read(...args), write: (...args: unknown[]) => h.write(...args) }) }))
const render = () => { h.index = 0; return App() }
const flush = async () => { const effects = h.effects.splice(0); effects.forEach(effect => effect()); await new Promise(resolve => setTimeout(resolve, 0)) }
beforeEach(() => {
  h.index = 0; h.values = []; h.deps = []; h.effects = []; h.auth = { status: 'signed-out' }; h.notify = () => {}
  h.read.mockReset().mockResolvedValue(null); h.write.mockReset()
  const data = new Map<string, string>()
  vi.stubGlobal('localStorage', { getItem: (key: string) => data.get(key) ?? null, setItem: (key: string, value: string) => data.set(key, value), removeItem: (key: string) => data.delete(key) })
  vi.stubGlobal('window', { location: { pathname: '/', search: '', origin: 'http://localhost' }, history: { replaceState: vi.fn() } })
})
afterEach(() => vi.unstubAllGlobals())
describe('actual App beta routing (synthetic hooks + account adapter)', () => {
  it('keeps BetaWelcome mounted while signup loads and fails', async () => {
    let tree = render(); await flush(); expect(tree.type).toBe(BetaWelcome)
    tree.props.onLogin('tester@example.com'); tree = render()
    expect(tree.type).toBe(BetaWelcome); expect(tree.props.state.status).toBe('loading')
    h.auth = { status: 'error', message: 'Offline' }; h.notify(); tree = render()
    expect(tree.type).toBe(BetaWelcome); expect(tree.props.state.status).toBe('error')
  })
  it('sends an authenticated installed/root window with no marker and empty account to setup', async () => {
    h.auth = { status: 'signed-in', session: { user: { id: 'tester' } } }
    render(); await flush()
    const tree = render()
    expect(h.read).toHaveBeenCalledOnce()
    expect(tree.type).toBe(BetaWelcome); expect(tree.props.state.status).toBe('signed-in')
    expect(h.write).not.toHaveBeenCalled()
    // Only the explicit Open Threadline click creates the blank account.
    h.write.mockImplementation(async (userId, data) => ({ user_id: userId, revision: 'new', data }))
    await tree.props.onOpen()
    const workspace = render()
    expect(workspace.type).not.toBe(BetaWelcome)
    expect(workspace.props.cloud.state.objects).toEqual([])
    expect(workspace.props.cloud.state.canvas).toEqual([])
  })
  it('preserves existing local workspace entry and does not initialize it into the account', async () => {
    h.auth = { status: 'signed-in', session: { user: { id: 'tester' } } }
    localStorage.setItem('thoughtflow-state-v1', '{malformed-but-preserved')
    render(); await flush(); const tree = render()
    expect(tree.type).not.toBe(BetaWelcome)
    expect(h.write).not.toHaveBeenCalled()
    expect(localStorage.getItem('thoughtflow-state-v1')).toBe('{malformed-but-preserved')
  })
})
