import { beforeEach, describe, expect, it, vi } from 'vitest'
import { isValidElement, type ReactElement } from 'react'
import { BetaWelcome, type BetaWelcomeProps } from './BetaWelcomeView'

const hooks = vi.hoisted(() => ({ index: 0, values: [] as unknown[] }))
vi.mock('react', async original => ({ ...await original<typeof import('react')>(),
  useEffect: () => undefined,
  useRef: () => ({ current: null }),
  useState: (initial: unknown) => {
    const index = hooks.index++
    if (!(index in hooks.values)) hooks.values[index] = typeof initial === 'function' ? initial() : initial
    return [hooks.values[index], (next: unknown) => { hooks.values[index] = typeof next === 'function' ? next(hooks.values[index]) : next }]
  },
}))
type Element = ReactElement<Record<string, any>>
function find(tree: unknown, predicate: (element: Element) => boolean): Element {
  if (Array.isArray(tree)) { for (const child of tree) { const found = find(child, predicate); if (found) return found } }
  if (isValidElement<Record<string, any>>(tree)) return predicate(tree) ? tree : find(tree.props.children, predicate)
  return undefined as never
}
function setup() {
  const props: BetaWelcomeProps = { state: { status: 'signed-out' }, onLogin: vi.fn(), onVerify: vi.fn(), onRetry: vi.fn(), onLocal: vi.fn(), onOpen: vi.fn(async () => {}) }
  const render = () => { hooks.index = 0; return BetaWelcome(props) }
  const element = (id: string) => find(render(), e => e.props.id === id)
  const button = (text: string) => find(render(), e => e.type === 'button' && e.props.children === text)
  const submit = () => find(render(), e => e.type === 'form').props.onSubmit({ preventDefault: vi.fn() })
  return { props, render, element, button, submit }
}
beforeEach(() => { hooks.index = 0; hooks.values = [] })
describe('signup interaction handlers (synthetic hook render)', () => {
  it('retains email and code across loading, invalid code, connection retry and resending', () => {
    const ui = setup()
    ui.element('beta-email').props.onChange({ target: { value: 'tester@example.com' } })
    ui.submit(); expect(ui.props.onLogin).toHaveBeenCalledWith('tester@example.com')
    ui.props.state = { status: 'loading' }
    expect(ui.element('beta-email').props.value).toBe('tester@example.com')
    expect(ui.element('beta-email').props.disabled).toBe(true)
    ui.submit(); expect(ui.props.onLogin).toHaveBeenCalledTimes(1)
    ui.props.state = { status: 'signed-out', emailCodeSent: true }
    ui.button('Already have an email code?').props.onClick()
    ui.element('beta-code').props.onChange({ target: { value: '12a345678' } })
    const tree = ui.render()
    const forms: Element[] = []
    const walk = (node: unknown) => { if (Array.isArray(node)) node.forEach(walk); else if (isValidElement<Record<string, any>>(node)) { if (node.type === 'form') forms.push(node); walk(node.props.children) } }
    walk(tree); forms[1].props.onSubmit({ preventDefault: vi.fn() })
    expect(ui.props.onVerify).toHaveBeenCalledWith('tester@example.com', '12345678')
    ui.props.state = { status: 'signed-out', emailCodeSent: true, message: 'Invalid code' }
    expect(ui.element('beta-code').props.value).toBe('12345678')
    ui.props.state = { status: 'error', message: 'Offline' }
    ui.button('Retry connection').props.onClick(); expect(ui.props.onRetry).toHaveBeenCalledOnce()
    expect(ui.element('beta-email').props.value).toBe('tester@example.com')
  })
  it('never invokes authentication from the design preview', () => {
    const ui = setup(); ui.props.preview = true
    ui.submit()
    expect(ui.props.onLogin).not.toHaveBeenCalled()
    expect(ui.element('beta-setup-title')).toBeDefined()
    expect(ui.props.onOpen).not.toHaveBeenCalled()
  })
  it('only opens the account through an explicit action, and exposes a failed opening for retry', async () => {
    const ui = setup(); ui.props.state = { status: 'signed-in', session: { user: { id: 'tester' } } }
    ui.props.onOpen = vi.fn().mockRejectedValueOnce(Error('offline')).mockResolvedValueOnce(undefined)
    const open = () => find(ui.render(), e => e.type === 'button' && e.props.className === 'beta-cta')
    expect(ui.props.onOpen).not.toHaveBeenCalled()
    open().props.onClick(); await new Promise(resolve => setTimeout(resolve, 0))
    expect(find(ui.render(), e => e.props.role === 'alert').props.children).toContain('Nothing on this device')
    open().props.onClick(); await new Promise(resolve => setTimeout(resolve, 0))
    expect(ui.props.onOpen).toHaveBeenCalledTimes(2)
  })
})
