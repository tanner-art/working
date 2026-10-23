import { beforeEach, describe, expect, it, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { CaptureLibrary } from './CaptureLibraryView'
import { createSearchHandoffGuards, type RegisterSearchHandoffGuard } from './searchHandoffGuards'

const editorState = vi.hoisted(() => ({ value: null as unknown, calls: 0 }))
vi.mock('react', async importOriginal => {
  const actual = await importOriginal<typeof import('react')>()
  return { ...actual, useState: (initial: unknown) => {
    // The library's fourth state slot is its child-owned create/edit/move draft.
    editorState.calls += 1
    return actual.useState(editorState.calls === 4 ? editorState.value : initial)
  } }
})
vi.mock('./useSearchHandoffGuard', () => ({
  // Register during this static component test; mounted lifetime is browser-tested.
  useSearchHandoffGuard: (register: RegisterSearchHandoffGuard | undefined, id: string, canLeave: () => boolean) => register?.(id, canLeave),
}))

beforeEach(() => { editorState.calls = 0; editorState.value = null })
describe('capture folders composed with global Search', () => {
  const render = () => {
    const guards = createSearchHandoffGuards()
    renderToStaticMarkup(<CaptureLibrary objects={[]} library={{ folders: [], placements: [] }}
      onChange={() => undefined} onOpen={() => undefined} registerSearchHandoffGuard={guards.register} />)
    return guards
  }
  it('allows Search handoffs without an open folder editor', () => {
    expect(render().canLeave()).toBe(true)
  })
  it.each(['create', 'edit', 'move-folder', 'move-capture'])('protects an unfinished %s draft from Search result navigation', type => {
    editorState.value = { type, id: 'test', name: 'Unsaved folder', color: 'slate', emoji: '', destination: '' }
    expect(render().canLeave()).toBe(false)
  })
})
