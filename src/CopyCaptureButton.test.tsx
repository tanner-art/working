import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactElement } from 'react'
import { CopyCaptureButton } from './CopyCaptureButton'

const hooks = vi.hoisted(() => ({ notice: null as unknown, request: { current: 0 } }))
vi.mock('react', async importOriginal => {
  const actual = await importOriginal<typeof import('react')>()
  return { ...actual, useRef: () => hooks.request, useState: () => [hooks.notice, (value: unknown) => { hooks.notice = value }] }
})
const render = (text: string) => {
  const tree = CopyCaptureButton({ text })
  const children = tree.props.children as ReactElement<{ onClick?: () => Promise<void>; children?: string }>[]
  return { copy: children[0].props.onClick!, notice: children[1].props.children }
}
beforeEach(() => { hooks.notice = null; hooks.request.current = 0 })
afterEach(() => vi.unstubAllGlobals())
describe('copy feedback belongs to the copied text', () => {
  it('hides a previous success when another capture or edited text is displayed', async () => {
    vi.stubGlobal('navigator', { clipboard: { writeText: vi.fn().mockResolvedValue(undefined) } })
    await render('First capture').copy()
    expect(render('First capture').notice).toBe('Copied')
    expect(render('Edited capture').notice).toBe('')
  })
  it('does not show an old asynchronous success on newly displayed text', async () => {
    let resolve!: () => void
    vi.stubGlobal('navigator', { clipboard: { writeText: () => new Promise<void>(done => { resolve = done }) } })
    const pending = render('Old text').copy()
    expect(render('New text').notice).toBe('')
    resolve(); await pending
    expect(render('New text').notice).toBe('')
  })
  it('clears a previous success while retrying and reports a failed retry honestly', async () => {
    const writeText = vi.fn().mockResolvedValueOnce(undefined).mockRejectedValueOnce(Error('denied'))
    vi.stubGlobal('navigator', { clipboard: { writeText } })
    await render('Text').copy()
    const retry = render('Text').copy()
    expect(render('Text').notice).toBe('')
    await retry
    expect(render('Text').notice).toBe('Select the text to copy it manually.')
  })
  it('does not let an older request overwrite the most recent failure', async () => {
    let resolve!: () => void
    const writeText = vi.fn().mockImplementationOnce(() => new Promise<void>(done => { resolve = done })).mockRejectedValueOnce(Error('denied'))
    vi.stubGlobal('navigator', { clipboard: { writeText } })
    const old = render('Text').copy()
    await render('Text').copy()
    resolve(); await old
    expect(render('Text').notice).toBe('Select the text to copy it manually.')
  })
})
