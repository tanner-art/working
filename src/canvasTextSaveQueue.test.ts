import { afterEach, describe, expect, it, vi } from 'vitest'
import { createCanvasTextSaveQueue } from './canvasTextSaveQueue'
import { accountData, createAccountSession, type AccountAdapter, type AccountRow } from './accountStorage'
import { defaultSettings } from './settings'
import type { AppState } from './domain'

const tick = async (ms: number) => { await vi.advanceTimersByTimeAsync(ms) }
afterEach(() => { vi.useRealTimers() })

describe('canvas account text saves', () => {
  it('coalesces a paragraph into one latest-snapshot save', async () => {
    vi.useFakeTimers()
    let latest = ''
    const saved: string[] = []
    const queue = createCanvasTextSaveQueue(async () => { saved.push(latest); return true })
    for (let index = 0; index < 100; index++) {
      latest += 'x'
      queue.edited()
      expect(queue.consumeStateUpdate()).toBe(true)
      await tick(10)
    }
    expect(saved).toEqual([])
    await tick(600)
    expect(saved).toEqual(['x'.repeat(100)])
    expect(queue.hasPending()).toBe(false)
  })

  it('keeps at most one in-flight write and saves the newest edit after it finishes', async () => {
    vi.useFakeTimers()
    let release: (() => void) | undefined
    let latest = 'first'
    const saved: string[] = []
    const queue = createCanvasTextSaveQueue(async () => {
      saved.push(latest)
      if (saved.length === 1) await new Promise<void>(resolve => { release = resolve })
      return true
    })
    queue.edited(); queue.consumeStateUpdate(); queue.flush()
    expect(saved).toEqual(['first'])
    for (let index = 0; index < 50; index++) { latest = `edit-${index}`; queue.edited(); queue.consumeStateUpdate() }
    await tick(600)
    expect(saved).toEqual(['first'])
    expect(queue.hasPending()).toBe(true)
    release!()
    await tick(0)
    expect(saved).toEqual(['first', 'edit-49'])
    expect(queue.hasPending()).toBe(false)
  })

  it('preserves a failed edit for explicit retry and flushes on editor exit', async () => {
    vi.useFakeTimers()
    let latest = 'unsaved'
    const saved: string[] = []
    const save = vi.fn(async (retry: boolean) => { if (!retry) return false; saved.push(latest); return true })
    const queue = createCanvasTextSaveQueue(save)
    queue.edited(); queue.consumeStateUpdate(); queue.flush()
    await Promise.resolve(); await Promise.resolve()
    expect(queue.hasPending()).toBe(true)
    expect(saved).toEqual([])
    latest = 'latest unsaved'
    queue.edited(); queue.consumeStateUpdate(); queue.retry()
    await Promise.resolve(); await Promise.resolve()
    expect(saved).toEqual(['latest unsaved'])
    expect(queue.hasPending()).toBe(false)
  })

  it('covers related state updates while text is pending without scheduling another direct save', async () => {
    vi.useFakeTimers()
    const save = vi.fn(async () => true)
    const queue = createCanvasTextSaveQueue(save)
    queue.edited(); expect(queue.consumeStateUpdate()).toBe(true)
    await tick(300)
    expect(queue.consumeStateUpdate()).toBe(true)
    await tick(300)
    expect(save).not.toHaveBeenCalled()
    await tick(300)
    expect(save).toHaveBeenCalledTimes(1)
    expect(queue.consumeStateUpdate()).toBe(false)
  })

  it('writes one account revision for a typing burst and reloads the latest text', async () => {
    vi.useFakeTimers()
    let row: AccountRow | null = null
    let writes = 0
    const adapter: AccountAdapter = {
      read: async () => row,
      write: async (userId, data) => {
        writes++
        row = { user_id: userId, revision: String(writes), data: structuredClone(data) }
        return row
      },
    }
    const session = createAccountSession(adapter, 'canvas-user', () => 'canvas-user')
    let state: AppState = { objects: [], canvas: [{ id: 'node', type: 'text' as const, text: '', x: 1, y: 2 }] }
    const digest = { enabled: false }
    state = (await session.open(accountData(state, defaultSettings, digest))).state
    const queue = createCanvasTextSaveQueue(async retry => {
      await session.save(session.snapshot(state, defaultSettings, digest), retry)
      return true
    })
    for (let index = 0; index < 80; index++) {
      state.canvasBank!.canvases[0].elements[0].text += 'x'
      queue.edited()
      expect(queue.consumeStateUpdate()).toBe(true)
      await tick(10)
    }
    expect(writes).toBe(1)
    queue.flush()
    await tick(0)
    expect(writes).toBe(2)
    expect(queue.hasPending()).toBe(false)
    const reloaded = await createAccountSession(adapter, 'canvas-user', () => 'canvas-user').open()
    expect(reloaded.state.canvasBank!.canvases[0].elements[0].text).toBe('x'.repeat(80))
  })
})
